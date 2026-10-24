import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  CONTROL_COMMAND, CONTROL_ENTRY, CONTROL_VERSION, SessionReplay, assertSessionAuthority,
  type ControlRecord, type ControlRequest, type SavedSession,
} from "./handoff.js";

import { registerChildLink } from "./child-link.js";
/** Explicitly loaded before template extensions; this helper owns no AgentInfo. */
export default function childHelper(pi: ExtensionAPI): void {
  registerChildLink(pi);
  const replay = new SessionReplay(pi);
  let generation: string | undefined;
  let snapshot: SavedSession | undefined;
  const captures = new Map<string, SavedSession>();

  const publish = (action: ControlRequest["action"], ok: boolean, sessionId: string, error?: string): void => {
    if (!generation) return;
    const record: ControlRecord = {
      version: CONTROL_VERSION, generation, action, ok, sessionId,
      ...(snapshot ? { snapshot: structuredClone(snapshot) } : {}), ...(error ? { error } : {}),
    };
    pi.appendEntry(CONTROL_ENTRY, record);
  };

  pi.on("session_start", () => {
    // Core actions are not bound during extension loading. The first startup
    // listener is the earliest public hook, and must not yield before pausing.
    if (process.env.PI_SUBAGENT_HOLD === "1") pi.requestPause();
  });
  pi.on("agent_start", (_event, ctx) => {
    // A run started, but public agent_start does not identify the admitted
    // input. Publish progress as unknown, never as a successful marker receipt.
    if (generation && snapshot?.marker === "unknown") {
      try { publish("finish", false, ctx.sessionManager.getSessionId(), "Run start does not identify marker admission."); }
      catch (error) { console.error(`[${CONTROL_COMMAND}] marker progress: ${String(error)}`); }
    }
  });

  pi.registerCommand(CONTROL_COMMAND, {
    description: "Internal native subagent handoff control",
    allowedWhilePaused: true,
    handler: async (args, ctx) => {
      let request: ControlRequest;
      try {
        request = JSON.parse(args);
        if (!request || typeof request.generation !== "string" || !request.generation
          || !["inspect", "capture", "arm", "finish", "disarm", "discard"].includes(request.action)) {
          throw new Error("Malformed subagent control request.");
        }
      } catch (error) {
        console.error(`[${CONTROL_COMMAND}] ${String(error)}`);
        throw error;
      }
      const sessionId = ctx.sessionManager.getSessionId();
      let retainedArm = false;
      if (request.action === "arm" && request.snapshot && snapshot
        && request.snapshot.handoff?.requestId === snapshot.handoff.requestId) {
        // Recapture changes the native request ID. A retained live child may
        // transition control generation only for this same authoritative capture.
        try {
          assertSessionAuthority(request.snapshot, ctx.sessionManager);
          assertSessionAuthority(snapshot, ctx.sessionManager);
          retainedArm = true;
        } catch { /* rejected below, or by arm when generation already matches */ }
      }
      if ((!generation && request.action === "discard")
        || (generation && generation !== request.generation && request.action !== "inspect" && request.action !== "capture" && !retainedArm)) {
        const record: ControlRecord = {
          version: CONTROL_VERSION, generation: request.generation, action: request.action,
          ok: false, sessionId, error: "Stale subagent control generation.",
        };
        pi.appendEntry(CONTROL_ENTRY, record);
        return;
      }
      // inspect must not switch the generation of an already armed replay.
      if (request.action === "inspect") {
        const record: ControlRecord = {
          version: CONTROL_VERSION, generation: request.generation, action: "inspect",
          ok: typeof ctx.handoff === "function" && typeof ctx.submitInput === "function"
            && typeof pi.requestPause === "function" && typeof pi.resume === "function" && typeof pi.getPauseState === "function",
          sessionId,
        };
        pi.appendEntry(CONTROL_ENTRY, record);
        return;
      }
      generation = request.generation;
      const update = (value: SavedSession): void => {
        snapshot = value; // retain ownership even if appendEntry fails
        publish(request.action, request.action !== "finish", sessionId);
      };
      try {
        switch (request.action) {
          case "capture": {
            snapshot = captures.get(generation) ?? await replay.capture(ctx, generation);
            captures.set(generation, snapshot);
            publish("capture", true, sessionId);
            break;
          }
          case "arm": {
            if (!request.snapshot) throw new Error("arm requires a saved session.");
            assertSessionAuthority(request.snapshot, ctx.sessionManager);
            snapshot = request.snapshot;
            await replay.arm(ctx, snapshot, update);
            publish("arm", true, sessionId);
            break;
          }
          case "finish": {
            if (!request.disposition || !["started", "queued", "handled", "rejected", "unknown"].includes(request.disposition)) {
              throw new Error("finish requires the actual marker admission disposition.");
            }
            const result = await replay.finish(ctx, request.disposition, update);
            publish("finish", result.complete, sessionId, result.error);
            break;
          }
          case "discard": {
            replay.discardSavedInputs();
            captures.clear();
            snapshot = undefined;
            publish("discard", true, sessionId);
            break;
          }
          case "disarm": {
            snapshot = await replay.disarm(ctx, update) ?? snapshot;
            publish("disarm", true, sessionId);
            break;
          }
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error(`[${CONTROL_COMMAND}] ${request.action}: ${message}`);
        try { publish(request.action, false, sessionId, message); }
        catch (writeError) { console.error(`[${CONTROL_COMMAND}] record write failed: ${String(writeError)}`); }
      }
    },
  });
}
