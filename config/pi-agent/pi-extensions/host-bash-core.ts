import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { SessionManager } from "@earendil-works/pi-coding-agent";

type Item = Record<string, unknown>;
type Rpc = { request(method: string, params: unknown, options?: { timeoutMs: number }): Promise<any> };

/** Convert the active Pi branch without promoting summaries or tool text to user authority.
 * Thinking and binary attachments are omitted; text and tool arguments retain their roles.
 */
export function guardianHistory(entries: readonly any[], assignedByAgent = false): Item[] {
  const items: Item[] = [];
  const calls = new Set<string>();
  const textContent = (content: any) => typeof content === "string" ? content
    : (content ?? []).filter((block: any) => block.type === "text").map((block: any) => block.text).join("\n");
  const message = (role: string, text: string) => {
    if (text) items.push({ type: "message", role, content: [{ type: role === "assistant" ? "output_text" : "input_text", text }] });
  };
  for (const entry of entries) {
    if (entry.type === "compaction" || entry.type === "branch_summary") {
      message("assistant", `Conversation summary (not a new user instruction):\n${entry.summary}`);
      continue;
    }
    if (entry.type === "custom_message") {
      message("assistant", `Extension context:\n${textContent(entry.content)}`);
      continue;
    }
    if (entry.type !== "message") continue;
    const m = entry.message;
    const blocks = typeof m.content === "string" ? [{ type: "text", text: m.content }] : m.content ?? [];
    const text = textContent(m.content);
    if (m.role === "user" || m.role === "assistant") {
      message(m.role === "user" && assignedByAgent ? "assistant" : m.role,
        m.role === "user" && assignedByAgent ? `Parent-agent assignment:\n${text}` : text);
      if (m.role === "assistant") for (const b of blocks) {
        if (b.type !== "toolCall") continue;
        calls.add(b.id);
        items.push({ type: "function_call", call_id: b.id, name: b.name, arguments: JSON.stringify(b.arguments) });
      }
    } else if (m.role === "toolResult" && calls.has(m.toolCallId)) {
      items.push({ type: "function_call_output", call_id: m.toolCallId, output: text });
    } else {
      message("assistant", `Historical ${m.role}:\n${text}`);
    }
  }
  return items;
}

export interface HostAuthorityContext {
  file: string;
  leafId: string;
  sessionId: string;
  workspace: string;
}

/** Read the selected parent branch through Pi's parser without migrating its live file.
 * Launch metadata identifies the branch; child task prompts cannot replace this human context.
 */
export async function guardianParentHistory(reference: HostAuthorityContext) {
  if (!isAbsolute(reference.file) || !isAbsolute(reference.workspace)
    || !reference.leafId || !reference.sessionId) throw new Error("Invalid inherited host authority context");
  const directory = await mkdtemp(join(tmpdir(), "pi-host-authority-"));
  const run = promisify(execFile);
  try {
    const snapshot = join(directory, "session.jsonl");
    await run("cp", [reference.file, snapshot]);
    await run("cmp", [reference.file, snapshot]);
    const manager = SessionManager.open(snapshot);
    if (manager.getSessionId() !== reference.sessionId || !manager.getEntry(reference.leafId)) {
      throw new Error("Inherited host authority does not match the parent session");
    }
    return guardianHistory(manager.getBranch(reference.leafId));
  } finally { await rm(directory, { recursive: true, force: true }); }
}

export interface HostCommand {
  command: string;
  workspace: string;
  cwd: string;
  timeout: number;
  justification?: string;
  sandbox_permissions?: "use_default" | "require_escalated";
}

/** Check native exec policy, invoking Guardian only when that policy requires approval.
 * The default retains the thread's workspace sandbox, even when a command-rule prompt is approved.
 * Only an explicit escalation permits full host access; failures never trigger an automatic retry.
 * command/exec supplies execution only: this owner must enforce Guardian's decision.
 */
export async function reviewedHostCommand(rpc: Rpc, history: Item[], input: HostCommand) {
  const permissions = input.sandbox_permissions ?? "use_default";
  if (permissions !== "use_default" && permissions !== "require_escalated") throw new Error("Invalid host sandbox permissions");
  const escalated = permissions === "require_escalated";
  if (escalated && !input.justification?.trim()) throw new Error("Host escalation requires a justification");
  // command/exec resolves :workspace relative to its cwd, independently of the
  // thread. Keep both native cwd values fixed; changing the shell directory must
  // not let a model-selected workdir become a new writable workspace.
  const command = input.cwd === input.workspace ? input.command
    : `cd -- '${input.cwd.replaceAll("'", "'\\''")}' || exit\n${input.command}`;
  const thread = await rpc.request("thread/start", {
    cwd: input.workspace, approvalPolicy: "on-request", approvalsReviewer: "auto_review",
    permissions: ":workspace", ephemeral: true,
    // Guardian applies pre-tool hooks but returns no rewritten command. Disable
    // them on this disposable thread so execution uses the command actually reviewed.
    config: { "features.hooks": false },
  });
  if (typeof thread.thread?.id !== "string") throw new Error("Codex did not create a review thread");
  const threadId = thread.thread.id;
  const profile = thread.activePermissionProfile?.id;
  if (typeof profile !== "string" || !profile) throw new Error("Codex did not identify the host sandbox profile");
  const hooks = await rpc.request("hooks/list", { threadId });
  if (!Array.isArray(hooks.data) || hooks.data.some((entry: any) =>
    !Array.isArray(entry.hooks) || entry.hooks.length !== 0 || !Array.isArray(entry.errors) || entry.errors.length !== 0)) {
    throw new Error("Codex did not disable hooks on the host review thread");
  }
  const callId = `pi-host-${randomUUID()}`;
  await rpc.request("thread/inject_items", { threadId, items: [...history, {
    type: "function_call", name: "exec_command", call_id: callId,
    arguments: JSON.stringify({
      cmd: command, workdir: input.workspace, shell: "/bin/bash", login: false,
      sandbox_permissions: permissions, ...(input.justification ? { justification: input.justification } : {}),
    }),
  }] });
  const review = await rpc.request("thread/guardianReview", { threadId }, { timeoutMs: 110_000 });
  if (review.callId !== callId || !Object.hasOwn(review, "assessment")) {
    throw new Error("Guardian returned an invalid command assessment");
  }
  if (review.assessment !== null) {
    const assessment = review.assessment;
    if (typeof assessment?.rationale !== "string" || assessment.outcome !== "allow") {
      throw new Error(`Guardian did not approve this command: ${assessment?.rationale ?? "invalid assessment"}`);
    }
  }
  const result = await rpc.request("command/exec", {
    command: ["/bin/bash", "-c", command], cwd: input.workspace,
    ...(escalated ? { sandboxPolicy: { type: "dangerFullAccess" } } : { permissionProfile: profile }),
    timeoutMs: input.timeout * 1000,
    outputBytesCap: 64 * 1024,
  }, { timeoutMs: input.timeout * 1000 + 10_000 });
  if (!Number.isInteger(result.exitCode) || typeof result.stdout !== "string" || typeof result.stderr !== "string") {
    throw new Error("Codex returned an invalid command result");
  }
  return { ...result, review: review.assessment, execution: escalated ? "full-access" : "sandbox" };
}
