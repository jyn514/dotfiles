import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, existsSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test, { type TestContext } from "node:test";

import {
  createAssistantMessageEventStream, InMemoryCredentialStore, InMemoryModelsStore, Type,
  type AssistantMessage, type Tool, type ToolCall,
} from "@earendil-works/pi-ai";
import * as sdk from "@earendil-works/pi-coding-agent";

import { createGoal } from "../src/state.ts";
import { CUSTOM_ENTRY_TYPE, type ThreadGoal } from "../src/types.ts";
import {
  applyGuidance, compareDecisions, loadGuidance, prepareSeed, replayDecision, type DecisionKind,
} from "../tools/block-decision-replay.ts";

const tools: Tool[] = [
  { name: "get_goal", description: "Inspect frozen goal", parameters: Type.Object({}) },
  { name: "update_goal", description: "Set goal status", parameters: Type.Object({ status: Type.Union([Type.Literal("blocked"), Type.Literal("complete")]), reason: Type.Optional(Type.String()) }) },
  { name: "create_goal", description: "Create goal", parameters: Type.Object({ objective: Type.String() }) },
  { name: "bash", description: "Ordinary bash", parameters: Type.Object({ command: Type.String() }) },
  { name: "read", description: "Ordinary read", parameters: Type.Object({ path: Type.String() }) },
];
const system = { role: "system" as const, content: "Recorded host instructions", sections: { rules: "Keep this host rule.\n- Old goal guidance\n" }, toolsAdded: tools, timestamp: 1000 };
const context = { messages: [system, { role: "user" as const, content: "Continue the objective", timestamp: 1001 }] };
const goal = createGoal(null, "Compare omission mechanisms", null).goal!;
function call(name: string, args: ToolCall["arguments"] = {}): ToolCall {
  return { type: "toolCall", id: `${name}-call`, name, arguments: args };
}
function response(calls: ToolCall[] = [], stopReason: AssistantMessage["stopReason"] = "toolUse"): AssistantMessage {
  return {
    role: "assistant", content: calls.length ? calls : [{ type: "text", text: "No action" }],
    api: "openai-completions", provider: "fixture", model: "fixture", timestamp: 1002, stopReason,
    usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
  };
}
function temporary(t: TestContext): string {
  const dir = mkdtempSync(join(tmpdir(), "goal-decision-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}
function recordedSession(dir: string, frozen: ThreadGoal): string {
  const entries = [
    { type: "session", version: 3, id: "11111111-1111-4111-8111-111111111111", timestamp: "2026-10-08T00:00:00Z", cwd: "/nonexistent/historical/workspace" },
    { type: "model_change", id: "model", parentId: null, timestamp: "2026-10-08T00:00:00Z", provider: "fixture", modelId: "fixture" },
    { type: "thinking_level_change", id: "thinking", parentId: "model", timestamp: "2026-10-08T00:00:00Z", thinkingLevel: "high" },
    { type: "custom", id: "goal", parentId: "thinking", timestamp: "2026-10-08T00:00:00Z", customType: CUSTOM_ENTRY_TYPE, data: { version: 1, kind: "set", source: "command", goal: frozen, at: 1000 } },
    { type: "message", id: "user", parentId: "goal", timestamp: "2026-10-08T00:00:01Z", message: { role: "user", content: "Original pre-failure instructions", timestamp: 1001 } },
    { type: "compaction", id: "compact", parentId: "user", timestamp: "2026-10-08T00:00:02Z", summary: "Recorded failure evidence", firstKeptEntryId: "user", tokensBefore: 123, systemMessage: system },
    { type: "message", id: "inspect", parentId: "compact", timestamp: "2026-10-08T00:00:03Z", message: response([call("read", { path: "/nonexistent/historical/result.json" })]) },
    { type: "message", id: "last", parentId: "inspect", timestamp: "2026-10-08T00:00:04Z", message: { role: "toolResult", toolCallId: "read-call", toolName: "read", content: [{ type: "text", text: "The experiment failed" }], isError: false, timestamp: 1004 } },
    { type: "message", id: "block", parentId: "last", timestamp: "2026-10-08T00:00:05Z", message: response([call("update_goal", { status: "blocked", reason: "Need a new comparison" })]) },
    { type: "message", id: "later", parentId: "block", timestamp: "2026-10-08T00:00:06Z", message: { role: "user", content: "POST_BLOCK_CORRECTION_DO_NOT_INCLUDE", timestamp: 1006 } },
  ];
  const path = join(dir, "historical.jsonl");
  writeFileSync(path, entries.map(entry => JSON.stringify(entry)).join("\n") + "\n");
  return path;
}

test("native restoration excludes the block and later corrections without a historical workspace", t => {
  const dir = temporary(t);
  const file = recordedSession(dir, goal);
  const original = readFileSync(file);
  const seed = prepareSeed(file, "block", join(dir, "seed"), sdk);
  assert.equal(seed.goal.goalId, goal.goalId);
  assert.equal(seed.cutoff.lastEntryId, "last");
  assert.equal(seed.thinkingLevel, "high");
  assert.equal(seed.context.messages[0]?.role, "system");
  const visible = JSON.stringify(seed.context);
  assert.match(visible, /Recorded failure evidence/);
  assert.match(visible, /nonexistent\/historical\/result.json/);
  assert.doesNotMatch(visible, /Need a new comparison|POST_BLOCK_CORRECTION/);
  assert.deepEqual(readFileSync(file), original, "original session is not migrated or modified");
  assert.throws(() => prepareSeed(file, "later", join(dir, "invalid"), sdk), /assistant message requesting/);
});

test("native restoration selects the block's parent branch rather than an abandoned branch", t => {
  const dir = temporary(t);
  const file = recordedSession(dir, goal);
  const entries = readFileSync(file, "utf8").trim().split("\n").map(line => JSON.parse(line) as Record<string, unknown>);
  const cutoff = entries.findIndex(entry => entry.id === "block");
  entries.splice(cutoff, 0,
    { type: "model_change", id: "other-model", parentId: "last", timestamp: "2026-10-08T00:00:04Z", provider: "wrong-branch", modelId: "wrong-model" },
    { type: "custom", id: "other-goal", parentId: "other-model", timestamp: "2026-10-08T00:00:04Z", customType: CUSTOM_ENTRY_TYPE, data: { version: 1, kind: "set", source: "command", goal: { ...goal, objective: "ABANDONED_BRANCH_OBJECTIVE" }, at: 1004 } },
    { type: "message", id: "abandoned", parentId: "other-goal", timestamp: "2026-10-08T00:00:04Z", message: { role: "user", content: "ABANDONED_BRANCH_INSTRUCTIONS", timestamp: 1004 } },
  );
  writeFileSync(file, entries.map(entry => JSON.stringify(entry)).join("\n") + "\n");
  const seed = prepareSeed(file, "block", join(dir, "seed"), sdk);
  assert.equal(seed.cutoff.lastEntryId, "last");
  assert.equal(seed.goal.objective, goal.objective);
  assert.deepEqual(seed.model, { provider: "fixture", modelId: "fixture" });
  assert.doesNotMatch(JSON.stringify(seed.context), /ABANDONED_BRANCH/);
});

test("guidance replacement preserves historical messages, ordinary schemas, paths and host instructions", () => {
  const baseline = { guidelines: ["Old goal guidance"], tools: [tools[0]!] };
  const candidate = { guidelines: ["New scope guidance"], tools: [{ ...tools[0]!, description: "Candidate goal description" }] };
  const result = applyGuidance(context, baseline, candidate);
  const first = result.messages[0];
  assert.equal(first?.role, "system");
  if (first?.role !== "system") throw new Error("Missing system");
  assert.match(first.sections!.rules!, /Keep this host rule/);
  assert.match(first.sections!.rules!, /New scope guidance/);
  assert.doesNotMatch(first.sections!.rules!, /Old goal guidance/);
  assert.equal(first.toolsAdded![0]!.description, "Candidate goal description");
  assert.deepEqual(first.toolsAdded![3], tools[3]);
  assert.deepEqual(result.messages.slice(1), context.messages.slice(1));
  assert.match(system.sections.rules, /Old goal guidance/);
});

test("current goal declarations come from registration, not a copied schema", async () => {
  const guidance = await loadGuidance(resolve("src"));
  assert.deepEqual(guidance.tools.map(tool => tool.name), ["get_goal", "create_goal", "update_goal"]);
  assert.ok(guidance.guidelines.length > 0);
});

const cases: [string, ToolCall[], AssistantMessage["stopReason"], DecisionKind][] = [
  ["valid block", [call("update_goal", { status: "blocked", reason: "External dependency" })], "toolUse", "block_requested"],
  ["complete is not avoidance", [call("update_goal", { status: "complete" })], "toolUse", "completion_requested"],
  ["goal replacement is not avoidance", [call("create_goal", { objective: "Different task" })], "toolUse", "goal_change_requested"],
  ["read requests need no existing file", [call("read", { path: "/missing/ignored.json" })], "toolUse", "action_requested"],
  ["answer-only is not a demonstrated action", [], "stop", "answer_only"],
  ["missing tool call at a tool-use boundary", [], "toolUse", "inconclusive"],
  ["invalid status", [call("update_goal", { status: "paused" })], "toolUse", "inconclusive"],
  ["missing block reason", [call("update_goal", { status: "blocked" })], "toolUse", "inconclusive"],
  ["unknown tool", [call("unavailable")], "toolUse", "inconclusive"],
  ["truncated response", [call("read", { path: "x" })], "length", "inconclusive"],
  ["block in mixed batch is not hidden by another action", [call("read", { path: "x" }), call("update_goal", { status: "blocked", reason: "Need input" })], "toolUse", "block_requested"],
];
for (const [name, calls, stopReason, expected] of cases) {
  test(name, async () => {
    const result = await replayDecision(context, goal, async () => response(calls, stopReason));
    assert.equal(result.kind, expected);
    assert.equal(result.responses.length, 1);
  });
}

test("a proposed bash mutation is recorded but never executes", async t => {
  const canary = join(temporary(t), "must-not-exist");
  const result = await replayDecision(context, goal, async () => response([call("bash", { command: `touch '${canary}'` })]));
  assert.equal(result.kind, "action_requested");
  assert.equal(existsSync(canary), false);
});

test("frozen get_goal queries use the real SDK provider path and then stop before ordinary tools", async () => {
  const runtime = await sdk.ModelRuntime.create({ allowModelNetwork: false, refreshOnCreate: false, modelsPath: null, credentials: new InMemoryCredentialStore(), modelsStore: new InMemoryModelsStore() });
  let requests = 0;
  const model = { provider: "decision-fixture", id: "fixture", name: "Fixture", api: "openai-completions" as const, baseUrl: "http://localhost", reasoning: false, input: ["text" as const], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 10000, maxTokens: 1000 };
  runtime.registerProvider("decision-fixture", { api: "openai-completions", apiKey: "fixture", models: [model], streamSimple: (_model, input) => {
    requests++;
    if (requests === 2) {
      const last = input.messages.at(-1);
      assert.equal(last?.role, "toolResult");
      if (last?.role !== "toolResult") throw new Error("Missing goal result");
      const text = last.content.find(part => part.type === "text");
      assert.ok(text?.type === "text");
      assert.equal(JSON.parse(text.text).goal.objective, goal.objective);
      assert.equal(JSON.parse(text.text).goal.tokensUsed, goal.usage.tokensUsed);
    }
    const stream = createAssistantMessageEventStream();
    const message = response([requests === 1 ? call("get_goal") : call("read", { path: "/ignored/absent" })]);
    queueMicrotask(() => { stream.push({ type: "done", reason: "toolUse", message }); stream.end(); });
    return stream;
  } });
  const result = await replayDecision(context, goal, input => runtime.completeSimple(model, input));
  assert.equal(result.kind, "action_requested");
  assert.equal(requests, 2);
});

test("repeated goal queries and provider failures are bounded and inconclusive", async () => {
  let requests = 0;
  const result = await replayDecision(context, goal, async () => { requests++; return response([call("get_goal")]); }, 1);
  assert.equal(result.kind, "inconclusive");
  assert.equal(requests, 2);
  assert.equal((await replayDecision(context, goal, async () => { throw new Error("offline"); })).kind, "inconclusive");
});

test("comparison requires baseline reproduction and an actual alternative tool request", async () => {
  const block = await replayDecision(context, goal, async () => response([call("update_goal", { status: "blocked", reason: "Input" })]));
  const action = await replayDecision(context, goal, async () => response([call("read", { path: "x" })]));
  const complete = await replayDecision(context, goal, async () => response([call("update_goal", { status: "complete" })]));
  assert.equal(compareDecisions(block, action).outcome, "avoided_at_decision_point");
  assert.equal(compareDecisions(action, action).outcome, "inconclusive");
  assert.equal(compareDecisions(block, block).outcome, "block_reproduced");
  assert.equal(compareDecisions(block, complete).outcome, "inconclusive");
});

test("documented npm replay command reaches the CLI without a model or private configuration", t => {
  const home = temporary(t);
  const help = spawnSync("npm", ["run", "replay:block", "--", "--help"], { encoding: "utf8", env: { ...process.env, HOME: home, npm_config_cache: join(home, "cache") } });
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /No agent loop or external tool execution/);
  const invalid = spawnSync(process.execPath, ["tools/replay-block.ts"], { encoding: "utf8", env: { ...process.env, HOME: home } });
  assert.equal(invalid.status, 2);
  assert.match(invalid.stderr, /Missing --session/);
});
