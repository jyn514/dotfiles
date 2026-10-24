/** Versioned structural contract shared with independently loaded pi-link.
 * Manager owns worker selection, stable IDs, and lifecycle. Only native transcript
 * admission confers reply authority; a queued steering receipt does not.
 */
export const LINK_VERSION = 1;
export const LINK_DISCOVER = "pi-link:workers:v1";
export const LINK_REPLY = "pi-link:worker-reply:v1";
/** Same-process dispatch from pi-link to an admitted manager-delivery reference. */
export const LINK_CHILD_REPLY = "pi-link:child-reply:v1";
export const LINK_COMMAND = "subagent-link";
export const LINK_CONTROL_ENTRY = "subagent-link-control";
export const LINK_MESSAGE_TYPE = "subagent-link-message";
/** RPC's public, fire-and-forget notify event avoids waiting on a tool's own result. */
export const LINK_REPLY_NOTIFY = "subagent-link-reply:";
export const LINK_TIMEOUT_MS = 2_000;
export type LinkStatus = "submitted" | "failed" | "skipped" | "unsupported" | "unknown";
export interface LinkWorkerAddress { workerId: string; taskName: string }
export interface LinkDelivery {
  from: string;
  fromSessionId: string;
  content: string;
  id: string;
  replyTo?: string;
  broadcast?: boolean;
  fromWorker?: LinkWorkerAddress & { ownerSessionId: string };
}
export interface LinkResult {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, unknown>;
  isError?: boolean;
}
export interface LinkWorkerIntegration {
  broadcast(message: LinkDelivery): Promise<Array<LinkWorkerAddress & { status: LinkStatus; reason?: string }>>;
  reply(worker: LinkWorkerAddress, message: LinkDelivery): Promise<{ status: LinkStatus; reason?: string }>;
}
export interface LinkDiscovery {
  version: 1;
  ownerSessionId: string;
  provide(integration: LinkWorkerIntegration): void;
}
/** In-process manager callback, never accepted as worker-supplied routing authority. */
export interface LinkWorkerReply {
  version: 1;
  ownerSessionId: string;
  worker: LinkWorkerAddress;
  reference: LinkDelivery;
  message: string;
  respond(result: Promise<LinkResult>): void;
}
export interface LinkChildReply {
  version: 1;
  replyTo: string;
  message: string;
  signal?: AbortSignal;
  respond(result: Promise<LinkResult>): void;
}
export interface LinkMessageDetails {
  version: 1;
  ownerSessionId: string;
  workerId: string;
  recipientSessionId: string;
  delivery: LinkDelivery;
}
export type LinkCommand =
  | { version: 1; requestId: string; action: "deliver"; ownerSessionId: string; workerId: string; message: LinkDelivery }
  | { version: 1; requestId: string; action: "result"; result: LinkResult };
export interface LinkControlRecord {
  version: 1;
  requestId: string;
  status: LinkStatus;
  reason?: string;
}
/** Child supplies only a delivered reference and text, never an author or destination. */
export interface LinkReplyNotification { version: 1; requestId: string; replyTo: string; message: string }
export function linkFailure(status: LinkStatus, reason: string): LinkResult {
  return { content: [{ type: "text", text: `Worker reply: ${status} (${reason}). No retry was attempted.` }],
    details: { status, reason }, isError: true };
}
export function isLinkDelivery(value: unknown): value is LinkDelivery {
  if (!value || typeof value !== "object") return false;
  const v = value as LinkDelivery;
  const text = (s: unknown) => typeof s === "string" && s.length > 0;
  return text(v.from) && text(v.fromSessionId) && text(v.id) && typeof v.content === "string"
    && (v.replyTo === undefined || text(v.replyTo)) && (v.broadcast === undefined || typeof v.broadcast === "boolean")
    && (v.fromWorker === undefined || (text(v.fromWorker?.workerId) && text(v.fromWorker?.taskName)
      && v.fromWorker.ownerSessionId === v.fromSessionId));
}
export function admittedLink(entry: any, ownerSessionId: string, workerId: string, recipientSessionId?: string): LinkDelivery | undefined {
  const message = entry?.type === "custom_message" ? entry : entry?.type === "message" ? entry.message : undefined;
  const details = message?.details as LinkMessageDetails | undefined;
  if (message?.customType !== LINK_MESSAGE_TYPE || details?.version !== LINK_VERSION
    || details.ownerSessionId !== ownerSessionId || details.workerId !== workerId
    || typeof details.recipientSessionId !== "string"
    || (recipientSessionId !== undefined && details.recipientSessionId !== recipientSessionId)
    || !isLinkDelivery(details.delivery)) return;
  return details.delivery;
}
