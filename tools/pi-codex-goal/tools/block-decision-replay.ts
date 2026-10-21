import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import {
  getCurrentTools,
  validateToolCall,
  type AssistantMessage,
  type Context,
  type Tool,
  type ToolCall,
} from "@earendil-works/pi-ai";
import type * as Pi from "@earendil-works/pi-coding-agent";

import { toToolText } from "../src/format.ts";
import { reconstructGoal } from "../src/state.ts";
import type { ThreadGoal } from "../src/types.ts";

export type ReplayHost = Pick<typeof Pi, "SessionManager" | "convertToLlm">;
export interface DecisionSeed {
  context: Context;
  goal: ThreadGoal;
  model: { provider: string; modelId: string };
  thinkingLevel: string;
  cutoff: { excludedEntryId: string; prefixSha256: string; prefixBytes: number; lastEntryId: string };
}
export interface Guidance {
  guidelines: string[];
  tools: Tool[];
}
export type DecisionKind = "block_requested" | "action_requested" | "completion_requested" |
  "goal_change_requested" | "answer_only" | "inconclusive";
export interface Decision {
  kind: DecisionKind;
  calls: ToolCall[];
  reason: string;
  responses: AssistantMessage[];
}
export type Complete = (context: Context) => Promise<AssistantMessage>;

function goalTool(name: string): string {
  return name.split(".").at(-1) ?? name;
}

/** Only framing is parsed here; Pi owns branch selection, compaction and message conversion. */
export function prepareSeed(sessionPath: string, before: string, directory: string, host: ReplayHost): DecisionSeed {
  const bytes = readFileSync(sessionPath);
  let offset = 0;
  let excluded: { id: string; parentId?: string; message?: AssistantMessage } | undefined;
  while (offset < bytes.length) {
    const end = bytes.indexOf(10, offset);
    const next = end < 0 ? bytes.length : end + 1;
    const line = bytes.subarray(offset, next).toString("utf8").trim();
    if (line) {
      const entry = JSON.parse(line) as { id: string; parentId?: string; message?: AssistantMessage };
      if (entry.id === before) { excluded = entry; break; }
    }
    offset = next;
  }
  if (!excluded) throw new Error(`Cutoff entry not found: ${before}`);
  if (excluded.message?.role !== "assistant" || !excluded.message.content.some(part =>
    part.type === "toolCall" && goalTool(part.name) === "update_goal" && part.arguments.status === "blocked")) {
    throw new Error("Cutoff must identify the assistant message requesting the historical block, not its tool result.");
  }
  const prefix = bytes.subarray(0, offset);
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const seedPath = join(directory, "session-prefix.jsonl");
  writeFileSync(seedPath, prefix, { flag: "wx", mode: 0o600 });
  const manager = host.SessionManager.open(seedPath, join(directory, "session-state"));
  if (!excluded.parentId || !manager.getEntry(excluded.parentId)) throw new Error("Cutoff has no recorded native parent entry.");
  manager.branch(excluded.parentId);
  const leaf = manager.getLeafId();
  if (!leaf) throw new Error("Cutoff parent did not select a native branch.");
  const restored = manager.buildSessionContext();
  const context = { messages: host.convertToLlm(restored.messages) };
  const goal = reconstructGoal(manager.getBranch()).goal;
  if (!goal || goal.status !== "active") throw new Error("Pre-block branch must contain an active goal.");
  if (!restored.model) throw new Error("Session does not record a selected model.");
  if (!context.messages.some(message => message.role === "system" && typeof message.sections?.rules === "string")) {
    throw new Error("Session lacks recorded system rules; do not substitute today's system prompt.");
  }
  const tools = getCurrentTools(context.messages);
  if (!tools.some(tool => goalTool(tool.name) === "update_goal")) throw new Error("Session lacks the recorded goal tool definitions.");
  return {
    context, goal, model: restored.model, thinkingLevel: restored.thinkingLevel,
    cutoff: {
      excludedEntryId: before, prefixSha256: createHash("sha256").update(prefix).digest("hex"),
      prefixBytes: prefix.length, lastEntryId: leaf,
    },
  };
}

/** Read the source's public registration declarations; never invoke its execute callbacks. */
export async function loadGuidance(source: string): Promise<Guidance> {
  const prompts = await import(pathToFileURL(join(source, "prompts.ts")).href) as {
    TOOL_PROMPT_GUIDELINES: string[];
  };
  const module = await import(pathToFileURL(join(source, "tools.ts")).href) as {
    registerGoalTools: (pi: unknown, host: unknown) => void;
  };
  if (!Array.isArray(prompts.TOOL_PROMPT_GUIDELINES) || !prompts.TOOL_PROMPT_GUIDELINES.every(line => typeof line === "string")) {
    throw new Error("Source must export TOOL_PROMPT_GUIDELINES from prompts.ts.");
  }
  const tools: Tool[] = [];
  module.registerGoalTools({ registerTool: (tool: Tool) => {
    tools.push({ name: tool.name, description: tool.description, parameters: tool.parameters });
  } }, {});
  return { guidelines: [...prompts.TOOL_PROMPT_GUIDELINES], tools: JSON.parse(JSON.stringify(tools)) as Tool[] };
}

/** Change only standing goal guidance and goal declarations, retaining historical conversation messages. */
export function applyGuidance(context: Context, baseline: Guidance, selected: Guidance): Context {
  const result = structuredClone(context);
  const oldLines = new Set(baseline.guidelines);
  for (const message of result.messages) {
    if (message.role !== "system") continue;
    if (typeof message.sections?.rules === "string") {
      const retained = message.sections.rules.split("\n").filter(line => !oldLines.has(line.replace(/^[-*] /, "")));
      message.sections.rules = `${retained.join("\n")}\n${selected.guidelines.map(line => `- ${line}`).join("\n")}\n`;
    }
    if (message.toolsAdded) message.toolsAdded = message.toolsAdded.map(recorded => {
      const replacement = selected.tools.find(tool => tool.name === goalTool(recorded.name));
      return replacement ? { ...recorded, description: replacement.description, parameters: replacement.parameters } : recorded;
    });
  }
  return result;
}

/** No tool implementations or agent loop are available here. Only frozen get_goal results can be supplied. */
export async function replayDecision(context: Context, goal: ThreadGoal, complete: Complete, maxQueries = 3): Promise<Decision> {
  if (!Number.isSafeInteger(maxQueries) || maxQueries < 0) throw new Error("maxQueries must be a nonnegative integer.");
  const input = structuredClone(context);
  const responses: AssistantMessage[] = [];
  let queries = 0;
  const finish = (kind: DecisionKind, calls: ToolCall[], reason: string): Decision => ({ kind, calls, reason, responses });
  for (;;) {
    let message: AssistantMessage;
    try { message = await complete(structuredClone(input)); }
    catch (error) { return finish("inconclusive", [], `Provider failed: ${String(error)}`); }
    responses.push(message);
    if (message.stopReason === "error" || message.stopReason === "aborted" || message.stopReason === "length") {
      return finish("inconclusive", [], `Provider stopped with ${message.stopReason}: ${message.errorMessage ?? ""}`);
    }
    const calls = message.content.filter((part): part is ToolCall => part.type === "toolCall");
    if (!calls.length) return message.stopReason === "toolUse"
      ? finish("inconclusive", [], "Provider requested tool use without supplying a tool call.")
      : finish("answer_only", [], "No actionable tool decision; this is not block avoidance evidence.");
    try { for (const call of calls) validateToolCall(getCurrentTools(input.messages), call); }
    catch (error) { return finish("inconclusive", calls, `Invalid or unavailable tool call: ${String(error)}`); }
    const updates = calls.filter(call => goalTool(call.name) === "update_goal");
    const blocks = updates.filter(call => call.arguments.status === "blocked");
    if (blocks.length) {
      if (blocks.some(call => typeof call.arguments.reason !== "string" || !call.arguments.reason.trim())) {
        return finish("inconclusive", calls, "Blocked request lacks the required dependency reason.");
      }
      return finish("block_requested", calls, "Model requested a whole-goal block; request was not executed.");
    }
    if (updates.some(call => call.arguments.status === "complete")) {
      return finish("completion_requested", calls, "Completion is not a successful alternative to blocking.");
    }
    if (calls.some(call => goalTool(call.name) === "create_goal")) {
      return finish("goal_change_requested", calls, "Changing the objective is not block avoidance evidence.");
    }
    // Replay seeds are active: paused only annotates an already-paused goal,
    // and active only unblocks a blocked goal. Neither is an eligible action here.
    if (updates.some(call => call.arguments.status === "paused" || call.arguments.status === "active")) {
      return finish("inconclusive", calls, "Paused annotation and blocked-goal activation are ineligible on the active replay seed.");
    }
    if (calls.some(call => goalTool(call.name) !== "get_goal")) {
      return finish("action_requested", calls, "Model proposed a different action; no external tool was executed.");
    }
    if (queries + calls.length > maxQueries) return finish("inconclusive", calls, "Frozen goal-query limit reached.");
    input.messages.push(message);
    for (const call of calls) {
      queries++;
      input.messages.push({
        role: "toolResult", toolCallId: call.id, toolName: call.name,
        content: [{ type: "text", text: toToolText(goal) }], isError: false,
        timestamp: goal.updatedAt * 1000,
      });
    }
  }
}

export function compareDecisions(baseline: Decision, candidate: Decision): {
  outcome: "avoided_at_decision_point" | "block_reproduced" | "inconclusive";
  reason: string;
} {
  if (baseline.kind !== "block_requested") return { outcome: "inconclusive", reason: "Baseline did not reproduce the historical block." };
  if (candidate.kind === "block_requested") return { outcome: "block_reproduced", reason: "Both arms requested a block." };
  if (candidate.kind === "action_requested") return { outcome: "avoided_at_decision_point", reason: "Candidate proposed a different action; later blocking and progress are untested." };
  return { outcome: "inconclusive", reason: `Candidate produced ${candidate.kind}, not a demonstrated alternative action.` };
}
