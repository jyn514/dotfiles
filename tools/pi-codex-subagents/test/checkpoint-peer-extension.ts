/** Native transport peer, not the real boundary policy. Writes only owned fixture evidence. */
import { appendFileSync, existsSync, readFileSync, realpathSync, writeFileSync, writeSync } from "node:fs";
import { join, relative } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  CHECKPOINT_EXPORT_EVENT, CHECKPOINT_RESTORE_EVENT, CHECKPOINT_VERSION, CHECKPOINT_NOTIFY,
  type Checkpoint, type CheckpointRestore,
} from "../checkpoint.ts";

export type PeerControl = { action?: "write" | "retire" | "missing" | "malformed" | "crash" | "hold";
  value?: string; failRestore?: boolean; lateExport?: boolean; startupCrash?: boolean; restoreCrash?: boolean };
export default function checkpointPeer(pi: ExtensionAPI) {
  let checkpoint: Checkpoint | null = null;
  let cwd: string;
  let sessionId: string;
  let control: PeerControl = {};
  const readControl = (): PeerControl => JSON.parse(readFileSync(join(cwd, "checkpoint-control.json"), "utf8"));
  pi.on("session_start", (_event, ctx) => {
    const owned = process.env.PI_TEST_OWNED_ROOT;
    if (!owned) throw new Error("Checkpoint peer requires owned source-test storage.");
    const rel = relative(realpathSync(owned), realpathSync(ctx.cwd));
    if (rel === ".." || rel.startsWith("../") || rel.startsWith("/")) throw new Error("Checkpoint peer cwd is not owned.");
    cwd = ctx.cwd;
    sessionId = ctx.sessionManager.getSessionId();
    if (readControl().startupCrash) process.exit(38);
    // The restoration command must arrive AFTER this reset, regardless of load order.
    checkpoint = null;
  });
  pi.events.on(CHECKPOINT_RESTORE_EVENT, value => {
    const request = value as CheckpointRestore;
    const control = readControl();
    if (control.restoreCrash) process.exit(39);
    if (control.failRestore) return;
    checkpoint = request.checkpoint;
    request.applied = true;
  });
  pi.registerTool({
    name: "checkpoint_peer", label: "Checkpoint peer", description: "Exercise native checkpoint transport",
    parameters: Type.Object({}),
    async execute(_id, _params, signal) {
      control = readControl();
      appendFileSync(join(cwd, "checkpoint-observations.jsonl"), JSON.stringify({ pid: process.pid, sessionId, checkpoint }) + "\n");
      if (control.action === "write") checkpoint = { repository: join(cwd, "repository"), commit: control.value!, parent: "fixture-parent-secret" };
      if (control.action === "retire") checkpoint = null;
      if (control.action === "crash") {
        pi.events.emit(CHECKPOINT_EXPORT_EVENT, { version: CHECKPOINT_VERSION, checkpoint });
        process.exit(37);
      }
      if (control.action === "hold") {
        writeFileSync(join(cwd, "checkpoint-held"), "held");
        while (!signal?.aborted && !existsSync(join(cwd, "checkpoint-release"))) await delay(10);
      }
      return { content: [{ type: "text", text: "checkpoint peer finished" }], details: {} };
    },
  });
  pi.on("agent_settled", async () => {
    // Exercise an awaited controller hook, after the helper's own hooks.
    await delay(5);
    if (control.action === "missing") return;
    if (control.action === "malformed") pi.events.emit(CHECKPOINT_EXPORT_EVENT, { version: CHECKPOINT_VERSION, checkpoint });
    pi.events.emit(CHECKPOINT_EXPORT_EVENT, control.action === "malformed" ? { version: 1, checkpoint: { commit: 123 } }
      : { version: CHECKPOINT_VERSION, checkpoint });
  });
  pi.on("session_shutdown", () => {
    if (control.lateExport) {
      // Deliberately hostile late protocol frames from the closing native child.
      // The helper correctly stops exporting at shutdown, so bypass only that
      // producer suppression to exercise the manager's independent lifetime check.
      writeSync(1, JSON.stringify({ type: "extension_ui_request", method: "notify", message: CHECKPOINT_NOTIFY + JSON.stringify({
        version: CHECKPOINT_VERSION, checkpoint: { repository: cwd, commit: "late-old-process-secret", parent: "late-parent-secret" },
      }) }) + "\n");
      writeSync(1, JSON.stringify({ type: "agent_settled", aborted: false }) + "\n");
    }
  });
}
