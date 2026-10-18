/** Packaged template extension: a real tool with an externally controlled boundary. */
import { appendFileSync, existsSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export function heldToolFiles(path: string) {
  return { started: `${path}.started`, pauseRequested: `${path}.pause-requested`, release: `${path}.release`, effects: `${path}.effects.jsonl`, ended: `${path}.ended` };
}
export function providerCallsFile(sessionFile: string) { return `${sessionFile}.provider-calls.jsonl`; }
export function templateStartsFile(sessionFile: string) { return `${sessionFile}.template-starts.jsonl`; }

function assertOwned(path: string): void {
  const root = process.env.PI_TEST_OWNED_ROOT;
  if (!root) throw new Error("Held-tool extension requires the source-test bootstrap");
  const rel = relative(realpathSync(root), realpathSync(dirname(resolve(path))));
  if (rel === ".." || rel.startsWith("../") || rel.startsWith("/")) throw new Error("Held-tool markers must be disposable");
}
export default function heldToolExtension(pi: ExtensionAPI): void {
  let lastHeldPath: string | undefined;
  pi.on("agent_settled", (event) => {
    if (!event.aborted || !lastHeldPath || !existsSync(`${lastHeldPath}.defer`)) return;
    unlinkSync(`${lastHeldPath}.defer`);
    // Native settlement admission owns these raw occurrences before handoff.
    pi.sendUserMessage(`saved-deferred-one:${lastHeldPath}.seen`);
    pi.sendUserMessage(`saved-deferred-two:${lastHeldPath}.seen`);
  });
  pi.on("input", (event) => {
    const deferred = event.text.match(/^saved-deferred-(?:one|two):(.+)$/);
    if (deferred) {
      assertOwned(deferred[1]);
      appendFileSync(deferred[1], `${event.text}\n`);
    }
  });
  pi.on("session_start", (_event, ctx) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    if (sessionFile) {
      assertOwned(sessionFile);
      appendFileSync(templateStartsFile(sessionFile), `${JSON.stringify({ pid: process.pid, pause: pi.getPauseState() })}\n`);
    }
  });
  pi.registerTool({
    name: "faux_nested_send", label: "Nested integration send", description: "Exercise the public nested tool path into production send_message.",
    parameters: Type.Object({ target: Type.String(), message: Type.String() }),
    async execute(_toolCallId, args, signal, _onUpdate, ctx) {
      const outcome = await ctx.executeTool("send_message", args, { signal });
      if (outcome.isError) throw new Error(JSON.stringify(outcome.result.content));
      return outcome.result;
    },
  });
  pi.registerTool({
    name: "faux_hold", label: "Held integration tool", description: "Wait for an owned test release marker, then record one effect.",
    parameters: Type.Object({ path: Type.String() }),
    async execute(toolCallId, { path }, signal) {
      assertOwned(path);
      lastHeldPath = path;
      const files = heldToolFiles(path);
      writeFileSync(files.started, JSON.stringify({ pid: process.pid, toolCallId }));
      while (!existsSync(files.release)) {
        if (pi.getPauseState() !== "unpaused" && !existsSync(files.pauseRequested)) {
          writeFileSync(files.pauseRequested, pi.getPauseState());
        }
        await delay(5, undefined, { signal });
      }
      signal?.throwIfAborted();
      appendFileSync(files.effects, `${JSON.stringify({ pid: process.pid, toolCallId })}\n`);
      writeFileSync(files.ended, toolCallId);
      return { content: [{ type: "text", text: "held-tool-effect-recorded" }], details: { toolCallId, path } };
    },
  });
}
