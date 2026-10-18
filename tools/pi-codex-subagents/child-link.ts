import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  LINK_COMMAND, LINK_CONTROL_ENTRY, LINK_MESSAGE_TYPE, LINK_REPLY_NOTIFY, LINK_VERSION, ROOT_LINK_TOOLS,
  admittedLink, isLinkDelivery, linkFailure,
  type LinkCommand, type LinkControlRecord, type LinkMessageDetails, type LinkReplyNotification, type LinkResult,
} from "./link.js";

// Bound the whole worker tool wait, including manager/child transport.
// Late receipts cannot restart a settled worker or retry an unknown submission.
const REPLY_TIMEOUT_MS = 5_000;

/** Explicit child-only control and reply surface; never joins the root link network. */
export function registerChildLink(pi: ExtensionAPI): void {
  const pending = new Map<string, { finish(result: LinkResult): void }>();
  const ownerSessionId = process.env.PI_SUBAGENT_PARENT_SESSION_ID;
  const workerId = process.env.PI_SUBAGENT_ID;
  const reset = () => {
    for (const request of [...pending.values()]) request.finish(linkFailure("unknown", "worker_session_closed"));
  };
  pi.on("session_start", () => {
    reset();
    // Templates select task tools, not root link authority. The helper always
    // offers this reply-only tool, even with an explicit inherited allowlist.
    pi.setActiveTools([...pi.getActiveTools().filter(name => !ROOT_LINK_TOOLS.has(name)), "link_reply"]);
  });
  pi.on("session_shutdown", reset);

  pi.registerCommand(LINK_COMMAND, {
    description: "Internal subagent link delivery and routing receipts",
    allowedWhilePaused: true,
    handler: async (args, ctx) => {
      const request = JSON.parse(args) as LinkCommand;
      if (request?.version !== LINK_VERSION || typeof request.requestId !== "string" || !request.requestId) {
        throw new Error("Malformed subagent link command.");
      }
      if (request.action === "result") {
        // Late routing receipts resolve only the original in-process tool call.
        // They cannot append input, wake the child, or create a continuation.
        if (!request.result || !Array.isArray(request.result.content) || !request.result.details) {
          throw new Error("Malformed subagent link result.");
        }
        pending.get(request.requestId)?.finish(request.result);
        return;
      }
      if (request.action !== "deliver" || !isLinkDelivery(request.message)) {
        throw new Error("Malformed subagent link delivery.");
      }
      const receipt = (status: LinkControlRecord["status"], reason?: string) => {
        pi.appendEntry(LINK_CONTROL_ENTRY, { version: LINK_VERSION, requestId: request.requestId,
          status, ...(reason ? { reason } : {}) } satisfies LinkControlRecord);
      };
      if (!ownerSessionId || !workerId || request.ownerSessionId !== ownerSessionId || request.workerId !== workerId) {
        receipt("failed", "worker_owner_mismatch");
        return;
      }
      if (typeof pi.getPauseState !== "function" || typeof ctx.submitInput !== "function") {
        receipt("unsupported", "native_input_admission_unavailable");
        return;
      }
      if (pi.getPauseState() !== "unpaused" || ctx.isIdle()) {
        receipt("skipped", "worker_inactive_or_paused");
        return;
      }
      const message = request.message;
      const details: LinkMessageDetails = { version: LINK_VERSION, ownerSessionId, workerId,
        recipientSessionId: ctx.sessionManager.getSessionId(), delivery: structuredClone(message) };
      const author = message.fromWorker
        ? `Worker "${message.fromWorker.taskName}" (${message.fromWorker.workerId}), owner "${message.from}"`
        : `"${message.from}"`;
      // submitInput queues prepared steering synchronously while the run is active.
      // There is no yield between the lifecycle check and native admission.
      const result = await ctx.submitInput({ kind: "prepared", message: {
        customType: LINK_MESSAGE_TYPE, display: true, details,
        content: `[Link${message.broadcast ? " group broadcast" : " private message"}] From ${author}\n`
          + `Message ID: ${message.id}\nAuthor session: ${message.fromSessionId}\n`
          + (message.replyTo ? `Reply to: ${message.replyTo}\n` : "") + message.content,
      }, options: { deliverAs: "steer", triggerTurn: true } });
      if (result.disposition === "rejected") receipt("skipped", result.error);
      else receipt("submitted");
    },
  });

  pi.registerTool({
    name: "link_reply", label: "Link Reply",
    description: "Privately reply to the author of a message actually delivered to this worker. replyTo must be a full received message ID. Cannot choose another recipient or broadcast. Returns routing acceptance, not a model response.",
    parameters: Type.Object({ replyTo: Type.String({ minLength: 1 }), message: Type.String({ minLength: 1 }) },
      { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ownerSessionId || !workerId) return linkFailure("unsupported", "worker_manager_unavailable");
      if (!params.message.trim()) return linkFailure("failed", "invalid_message");
      if (typeof pi.getPauseState !== "function") return linkFailure("unsupported", "native_pause_state_unavailable");
      if (pi.getPauseState() !== "unpaused") return linkFailure("skipped", "worker_paused");
      const delivered = ctx.sessionManager.getBranch().some(entry =>
        admittedLink(entry, ownerSessionId, workerId, ctx.sessionManager.getSessionId())?.id === params.replyTo);
      if (!delivered) return linkFailure("failed", "unknown_reference");
      if (signal?.aborted) return linkFailure("skipped", "aborted_before_send");
      const requestId = randomUUID();
      return new Promise<LinkResult>(resolve => {
        const finish = (result: LinkResult) => {
          if (!pending.delete(requestId)) return;
          clearTimeout(timer);
          signal?.removeEventListener("abort", abort);
          resolve(result);
        };
        const timer = setTimeout(() => finish(linkFailure("unknown", "worker_routing_deadline")), REPLY_TIMEOUT_MS);
        const abort = () => finish(linkFailure("unknown", "aborted_after_send"));
        pending.set(requestId, { finish });
        signal?.addEventListener("abort", abort, { once: true });
        const request: LinkReplyNotification = { version: LINK_VERSION, requestId, replyTo: params.replyTo, message: params.message };
        // RPC notify is immediate, unlike sendMessage: a transcript message can
        // wait for this very tool to finish and would deadlock the reply path.
        try { ctx.ui.notify(LINK_REPLY_NOTIFY + JSON.stringify(request), "info"); }
        catch { finish(linkFailure("unknown", "worker_transport_failed")); }
      });
    },
  });
}
