import { SessionManager, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { writeFileSync, unlinkSync } from "node:fs";
import { createConnection } from "node:net";
import { isAbsolute } from "node:path";

// A whole assistant/tool batch is indivisible. Streaming assistants are not normally
// persisted, but terminal failures/deferred responses also cannot be resumed here.
function completedPath(entries: SessionEntry[]): SessionEntry[] {
  const excluded = new Set<number>();
  const pending = new Set<string>();
  let batch: number[] = [];
  const discardBatch = () => {
    for (const index of batch) excluded.add(index);
    batch = [];
    pending.clear();
  };
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    if (entry.type !== "message") continue;
    const message = entry.message;
    if (message.role === "assistant") {
      // A resumed response starts a new batch, even without another user prompt.
      discardBatch();
      if (!["stop", "length", "toolUse"].includes(message.stopReason)) {
        excluded.add(i);
        continue;
      }
      for (const block of message.content) if (block.type === "toolCall") pending.add(block.id);
      if (pending.size) batch = [i];
    } else if (message.role === "toolResult") {
      if (!pending.delete(message.toolCallId)) {
        excluded.add(i); // Late, duplicate, or failed-assistant result has no call.
        continue;
      }
      batch.push(i);
      if (!pending.size) batch = []; // All results present: retain the whole batch.
    } else if (message.role === "user") {
      discardBatch();
    }
  }
  discardBatch(); // Only the unresolved batch is removed, not its later history.
  return entries.filter((_entry, index) => !excluded.has(index));
}

export function snapshotSession(source: ExtensionContext["sessionManager"]): string {
  const path = structuredClone(source.getBranch());
  const positions = new Map(path.map((entry, index) => [entry.id, index]));
  const entries = completedPath(path);
  const fresh = SessionManager.create(source.getCwd(), source.getSessionDir() || undefined, {
    parentSession: source.getSessionFile(),
  });
  const file = fresh.getSessionFile()!;
  // Pi delays persistence until an assistant exists. Publish the API-generated
  // header exclusively so even an empty snapshot is a real --session FILE.
  writeFileSync(file, `${JSON.stringify(fresh.getHeader())}\n`, { flag: "wx", mode: 0o600 });
  try {
    const target = SessionManager.open(file);
    const ids = new Map<string, string>();
    for (const entry of entries) {
      let id: string | undefined;
      switch (entry.type) {
        case "message":
          if (entry.message.role === "branchSummary" || entry.message.role === "compactionSummary") {
            throw new Error("Cannot copy a summary stored as a message instead of a session entry");
          }
          if (entry.message.role === "custom") {
            const { details, ...message } = entry.message;
            id = target.appendMessage(message);
          } else {
            id = target.appendMessage(entry.message);
          }
          break;
        case "model_change": id = target.appendModelChange(entry.provider, entry.modelId); break;
        case "thinking_level_change": id = target.appendThinkingLevelChange(entry.thinkingLevel); break;
        case "compaction": {
          const start = positions.get(entry.firstKeptEntryId);
          const end = positions.get(entry.id)!;
          if (start === undefined || start > end) {
            throw new Error("Cannot preserve compaction: retained entry is outside its source range");
          }
          // The cut point can be extension state or a failed/incomplete response.
          // Advance only within this compaction's retained range, never backwards
          // into summarized history or forwards into post-compaction turns.
          let firstKept: string | undefined;
          for (let i = start; i < end && !firstKept; i++) firstKept = ids.get(path[i].id);
          // With no surviving retained entries, an inert marker keeps the cut
          // point valid without transferring live state or resurrecting history.
          firstKept ??= target.appendCustomEntry("split-compaction-boundary", {});
          id = target.appendCompaction(entry.summary, firstKept, entry.tokensBefore, entry.details, entry.fromHook, entry.usage);
          break;
        }
        case "branch_summary":
          id = target.branchWithSummary(target.getLeafId(), entry.summary, entry.details, entry.fromHook, entry.usage);
          break;
        case "custom_message":
          id = target.appendCustomMessageEntry(entry.customType, entry.content, entry.display);
          break;
        case "label": {
          const labeled = ids.get(entry.targetId);
          if (labeled) id = target.appendLabelChange(labeled, entry.label);
          break;
        }
        // Non-context extension state can contain live workers/child sessions.
        case "custom": case "session_info": break;
      }
      if (id) ids.set(entry.id, id);
    }
    return file;
  } catch (error) {
    unlinkSync(file);
    throw error;
  }
}

type Request =
  | { op: "side"; attachment: string; session: string; prompt?: string }
  | { op: "ready"; attachment: string; session: string }
  | { op: "ready"; attachment: string; session: null; sessionDir: string };

export function requestOwner(socketPath: string, request: Request, timeoutMs = 10_000): Promise<void> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let buffer = "";
    let settled = false;
    let sent = false;
    const finish = (error?: Error, refused = false) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      if (error) {
        // A lost acknowledgement is not evidence that the host did not launch.
        reject(Object.assign(error, { snapshotMayBePublished: sent && !refused }));
      } else resolve();
    };
    const timer = setTimeout(() => finish(new Error("Host Pi controller timed out; request was not retried")), timeoutMs);
    socket.setEncoding("utf8");
    socket.on("connect", () => {
      sent = true;
      socket.write(`${JSON.stringify(request)}\n`);
    });
    socket.on("error", (error) => finish(error));
    socket.on("end", () => finish(new Error("Host Pi controller closed without a response")));
    socket.on("close", () => finish(new Error("Host Pi controller connection closed")));
    socket.on("data", (chunk) => {
      buffer += chunk;
      if (buffer.length > 64 * 1024) return finish(new Error("Host Pi controller response is too large"));
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      try {
        const response = JSON.parse(buffer.slice(0, newline));
        if (response?.ok === true) finish();
        else if (response?.ok === false && typeof response.error === "string") finish(new Error(response.error), true);
        else finish(new Error("Invalid Host Pi controller response"));
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error)));
      }
    });
  });
}

// This is host execution: guest-tools replaces builtins/user_bash, not pi.exec.
export async function publishRestartSession(pi: Pick<ExtensionAPI, "exec">,
  source: ExtensionContext["sessionManager"]): Promise<void> {
  const pane = process.env.TMUX_PANE;
  if (!process.env.TMUX || !pane) return;
  const option = "@codex_sandbox_restart";
  const read = async () => {
    const result = await pi.exec("tmux", ["show-option", "-p", "-q", "-v", "-t", pane, option]);
    if (result.code !== 0) throw new Error("Could not read sandbox restart registration");
    return result.stdout.trim();
  };
  const encoded = await read();
  if (!encoded) return; // Side panes are deliberately unmanaged.
  let registration: any;
  try {
    if (!/^[A-Za-z0-9_-]+={0,2}$/.test(encoded)
      || Buffer.from(encoded, "base64url").toString("base64url") !== encoded.replace(/=+$/, "")) throw Error();
    registration = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
    const keys = registration?.version === 1
      ? ["pane", "repository", "session", "token", "version"]
      : ["cwd", "pane", "repository", "session", "token", "version"];
    if (!registration || ![1, 2].includes(registration.version)
      || Object.keys(registration).sort().join() !== keys.join()
      || ["pane", "repository", "token"].some(key => typeof registration[key] !== "string" || !registration[key])
      || registration.pane !== pane || !isAbsolute(registration.repository)
      || (registration.version === 1
        ? typeof registration.session !== "string" || !registration.session
        : (registration.session !== null && (typeof registration.session !== "string" || !isAbsolute(registration.session)))
          || typeof registration.cwd !== "string" || !isAbsolute(registration.cwd))) throw Error();
  } catch {
    throw new Error("Invalid sandbox restart registration");
  }
  const session = source.getSessionFile() ?? null;
  const cwd = source.getCwd();
  if ((session !== null && !isAbsolute(session)) || !isAbsolute(cwd)) {
    throw new Error("SDK sandbox restart session/cwd must be absolute");
  }
  const payload = { version: 2, pane: registration.pane, repository: registration.repository,
    session, cwd, token: registration.token };
  // Expand and assign in one tmux server command so a replacement generation
  // wins even if it appeared after our read. Base64url excludes format delimiters.
  const updated = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const conditional = `#{?#{==:#{${option}},${encoded}},${updated},#{${option}}}`;
  const result = await pi.exec("tmux", ["set-option", "-p", "-F", "-t", pane, option, conditional]);
  if (result.code !== 0) throw new Error("Could not publish sandbox restart registration");
}

export default function sessionSide(pi: ExtensionAPI) {
  const socket = process.env.CODEX_SANDBOX_PI_OWNER;
  const attachment = process.env.CODEX_SANDBOX_PI_ATTACHMENT;
  const prompt = process.env.CODEX_SANDBOX_PI_SPLIT_PROMPT;
  delete process.env.CODEX_SANDBOX_PI_SPLIT_PROMPT;
  let initialPrompt = prompt;
  if (!socket || !isAbsolute(socket) || !attachment) return;
  pi.on("session_start", async (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    try {
      const source = ctx.sessionManager;
      const session = source.getSessionFile();
      await requestOwner(socket, session
        ? { op: "ready", attachment, session }
        : { op: "ready", attachment, session: null,
          sessionDir: source.getSessionDir() || SessionManager.create(source.getCwd()).getSessionDir() });
      await publishRestartSession(pi, source);
      if (initialPrompt) {
        const message = initialPrompt;
        initialPrompt = undefined;
        pi.sendUserMessage(message);
      }
    } catch (error) {
      ctx.ui.notify(`Host Pi readiness: ${String(error)}`, "error");
    }
  });
  pi.registerCommand("split", {
    description: "Open completed context in a new host Pi pane",
    handler: async (args, ctx) => {
      if (ctx.mode !== "tui") return ctx.ui.notify("/split requires an interactive sandbox attachment", "error");
      let snapshot: string | undefined;
      try {
        snapshot = snapshotSession(ctx.sessionManager);
        await requestOwner(socket, { op: "side", attachment, session: snapshot,
          ...(args.trim() ? { prompt: args } : {}) });
      } catch (error) {
        const uncertain = (error as { snapshotMayBePublished?: boolean })?.snapshotMayBePublished;
        if (snapshot && !uncertain) unlinkSync(snapshot);
        ctx.ui.notify(`/split: ${String(error)}${uncertain ? "; launch outcome unknown, snapshot retained (no retry)" : ""}`, "error");
      }
    },
  });
}
