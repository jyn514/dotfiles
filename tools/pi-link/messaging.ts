import { randomUUID } from "node:crypto";
import { groupOf } from "./identity";

// v1 hubs ignored worker reply attribution, which could redirect answers to the
// parent. Require v2 end-to-end; ordinary legacy direct chat remains separate.
export const MESSAGING_VERSION = 2;
/** Routing only: never waits for a model response and never retries. */
export const ROUTING_DEADLINE_MS = 5_000;
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
export type LinkStatus = "submitted" | "failed" | "skipped" | "unsupported" | "unknown";
export interface LinkOutcome {
  kind: "root" | "workers" | "worker" | "routing";
  name: string;
  sessionId?: string;
  taskName?: string;
  workerId?: string;
  status: LinkStatus;
  reason?: string;
}
export type LinkPeer = { name: string; sessionId?: string; messagingVersion?: number };
export type LinkSource = { name: string; sessionId: string };
/**
 * The owner manager, not pi-link, selects active workers and owns lifecycle policy.
 * It must not restart, resume, or enqueue work for inactive workers. These callbacks
 * bypass the parent model. They return transport outcomes, never model responses.
 * Outgoing worker replies require an in-process manager-authoritative reference.
 * The hub checks worker ownership against the registered source socket.
 */
export interface LinkWorkerAddress {
  /** Manager-owned stable identity; taskName is display metadata, never a lookup key. */
  workerId: string;
  taskName: string;
}
export interface LinkWorkerIntegration {
  broadcast(message: LinkDelivery): Promise<Array<LinkWorkerAddress & { status: LinkStatus; reason?: string }>>;
  /** Manager validates stable worker ID and ownership; name reuse must never redirect. */
  reply(worker: LinkWorkerAddress, message: LinkDelivery): Promise<{ status: LinkStatus; reason?: string }>;
}
export interface LinkMessagingOptions {
  self: () => LinkSource | undefined;
  role: () => "hub" | "client" | "disconnected";
  peers: () => LinkPeer[];
  hubSupported: () => boolean;
  sendHub: (frame: unknown) => boolean;
  sendPeer: (peer: LinkSource, frame: unknown) => boolean;
  deliverRoot: (message: LinkDelivery) => void;
  workers?: LinkWorkerIntegration | (() => LinkWorkerIntegration | undefined);
  /** Test-only override. Production uses the fixed five-second deadline. */
  testDeadlineMs?: number;
}

type Operation = "broadcast" | "reply";
type Destination = LinkSource & ({ taskName?: never; workerId?: never } | LinkWorkerAddress);
export interface LinkRequest {
  type: "link_request";
  messagingVersion: typeof MESSAGING_VERSION;
  id: string;
  operation: Operation;
  message: string;
  replyTo?: string;
  includeSubagents?: boolean;
  destination?: Destination;
  fromWorker?: LinkWorkerAddress & { ownerSessionId: string };
}
export interface LinkReceipt {
  type: "link_receipt";
  messagingVersion: typeof MESSAGING_VERSION;
  id: string;
  outcomes: LinkOutcome[];
  empty: boolean;
}
export interface LinkDeliveryFrame {
  type: "link_delivery";
  messagingVersion: typeof MESSAGING_VERSION;
  message: LinkDelivery;
}
export interface LinkWorkersFrame {
  type: "link_workers";
  messagingVersion: typeof MESSAGING_VERSION;
  requestId: string;
  message: LinkDelivery;
  taskName?: string;
  workerId?: string;
}
export interface LinkWorkerReceipt {
  type: "link_worker_receipt";
  messagingVersion: typeof MESSAGING_VERSION;
  requestId: string;
  outcomes: LinkOutcome[];
}

type Pending = { finish: (value: LinkOutcome[], empty?: boolean) => void };
const types = new Set(["link_request", "link_receipt", "link_delivery", "link_workers", "link_worker_receipt"]);
const statuses = new Set(["submitted", "failed", "skipped", "unsupported", "unknown"]);
function object(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function text(value: unknown): value is string { return typeof value === "string" && value.length > 0; }
function workerAddress(value: unknown): value is LinkWorkerAddress {
  return object(value) && text(value.workerId) && text(value.taskName);
}
function optionalWorkerAddress(value: Record<string, any>): boolean {
  return (value.workerId === undefined && value.taskName === undefined) || workerAddress(value);
}
function delivery(value: unknown): value is LinkDelivery {
  return object(value) && text(value.from) && text(value.fromSessionId) && text(value.id)
    && typeof value.content === "string" && (value.replyTo === undefined || text(value.replyTo))
    && (value.broadcast === undefined || typeof value.broadcast === "boolean")
    && (value.fromWorker === undefined || (object(value.fromWorker)
      && value.fromWorker.ownerSessionId === value.fromSessionId && workerAddress(value.fromWorker)));
}
function outcomes(value: unknown): value is LinkOutcome[] {
  return Array.isArray(value) && value.every(o => object(o)
    && ["root", "workers", "worker", "routing"].includes(o.kind)
    && typeof o.name === "string" && statuses.has(o.status)
    && (o.sessionId === undefined || text(o.sessionId))
    && optionalWorkerAddress(o)
    && (o.kind !== "worker" || workerAddress(o))
    && (o.reason === undefined || typeof o.reason === "string"));
}

export class LinkMessaging {
  private references = new Map<string, LinkDelivery>();
  private referenceSession: string | undefined;
  private pending = new Map<string, Pending>();
  private workerPending = new Map<string, { source: string; finish: (value: LinkOutcome[]) => void; cancel: () => void }>();
  private epoch = 0;
  private readonly deadline: number;
  constructor(private readonly options: LinkMessagingOptions) {
    this.referenceSession = options.self()?.sessionId;
    this.deadline = options.testDeadlineMs ?? ROUTING_DEADLINE_MS;
    if (!Number.isFinite(this.deadline) || this.deadline <= 0) throw new Error("Invalid routing deadline");
  }

  private syncSession(): void {
    const session = this.options.self()?.sessionId;
    if (session !== this.referenceSession) {
      this.disconnect();
      this.references.clear();
      this.referenceSession = session;
    }
  }
  /** Only successful model-visible admission confers reply permission. */
  recordDelivered(message: unknown): void {
    this.syncSession();
    if (delivery(message)) this.references.set(message.id, structuredClone(message));
  }
  /** Restore only admitted deliveries from the current Pi session's transcript. */
  restoreDelivered(messages: Iterable<unknown>): void {
    this.syncSession();
    for (const message of messages) this.recordDelivered(message);
  }
  /** Parent calls this on session switch, even if the next session has no identity yet. */
  reset(): void {
    this.disconnect();
    this.references.clear();
    this.referenceSession = this.options.self()?.sessionId;
  }
  disconnect(): void {
    this.epoch++;
    for (const pending of [...this.pending.values()]) pending.finish([this.routing("unknown", "disconnected")]);
    for (const pending of [...this.workerPending.values()]) pending.cancel();
  }
  private routing(status: LinkStatus, reason: string): LinkOutcome {
    return { kind: "routing", name: "hub", status, reason };
  }
  private result(id: string, operation: Operation, values: LinkOutcome[], empty = false, destination?: Destination): LinkResult {
    const counts = [...statuses].map(status => `${values.filter(o => o.status === status).length} ${status}`).join(", ");
    const failed = values.length > 0 && values.every(o => o.status !== "submitted");
    const lines = values.map(outcome => {
      const session = outcome.sessionId ?? "unavailable";
      const target = outcome.kind === "root" ? `root ${outcome.name} (session ${session})`
        : outcome.kind === "worker" ? `worker ${outcome.taskName} (worker ID ${outcome.workerId}; owner ${outcome.name}, session ${session})`
        : outcome.kind === "workers" ? `workers of ${outcome.name} (owner session ${session})`
        : `routing via ${outcome.name}`;
      return `- ${target}: ${outcome.status}${outcome.reason ? ` (${outcome.reason})` : ""}`;
    });
    if (destination && !values.some(o => o.kind === "root" || o.kind === "worker")) {
      lines.unshift(`Reply destination: ${destination.workerId
        ? `worker ${destination.taskName} (worker ID ${destination.workerId}; owner ${destination.name}, session ${destination.sessionId})`
        : `root ${destination.name} (session ${destination.sessionId})`}.`);
    }
    if (values.some(o => o.kind === "routing" && o.status === "unknown")) {
      lines.push(`${operation === "broadcast" ? "Recipient selection and submission outcomes are unknown" : "Submission outcome is unknown"} because no routing receipt was obtained. No retry was attempted.`);
    }
    return {
      content: [{ type: "text", text: [
        `${operation} ${id}: ${empty ? "empty selection; " : ""}${counts}.`,
        ...lines,
        "Submission is transport acceptance, not model read.",
      ].join("\n") }],
      details: { messageId: id, operation, outcomes: values, empty,
        ...(failed ? { error: values.map(o => o.reason ?? o.status).join("; ") } : {}),
      },
      ...(failed ? { isError: true } : {}),
    };
  }
  broadcast(args: { message: string; replyTo?: string; includeSubagents?: boolean }, signal?: AbortSignal): Promise<LinkResult> {
    return this.start({ type: "link_request", messagingVersion: MESSAGING_VERSION, id: randomUUID(), operation: "broadcast",
      // Empty broadcast correlation is omitted, matching the hub's delivery
      // construction before requests encounter the stricter wire validator.
      message: args.message, replyTo: args.replyTo || undefined, includeSubagents: args.includeSubagents }, signal);
  }
  reply(args: { message: string; replyTo: string }, signal?: AbortSignal): Promise<LinkResult> {
    this.syncSession();
    const id = randomUUID();
    const ref = this.references.get(args.replyTo);
    if (!ref) return Promise.resolve(this.result(id, "reply", [this.routing("failed", "unknown_reference")]));
    return this.replyToReference(ref, args.message, id, signal);
  }
  /** In-process manager only: reference was admitted in the child's transcript,
   * not necessarily in this root's transcript. Never expose as a model tool. */
  replyFromWorker(worker: LinkWorkerAddress, reference: LinkDelivery, message: string): Promise<LinkResult> {
    this.syncSession();
    const id = randomUUID();
    const self = this.options.self();
    if (!self || !workerAddress(worker) || !delivery(reference)) {
      return Promise.resolve(this.result(id, "reply", [this.routing("failed", "invalid_worker_reference")]));
    }
    return this.replyToReference(reference, message, id, undefined, { ...worker, ownerSessionId: self.sessionId });
  }
  private replyToReference(ref: LinkDelivery, message: string, id: string, signal?: AbortSignal, fromWorker?: LinkRequest["fromWorker"]): Promise<LinkResult> {
    const destination: Destination = ref.fromWorker
      ? { name: ref.from, sessionId: ref.fromSessionId, taskName: ref.fromWorker.taskName, workerId: ref.fromWorker.workerId }
      : { name: ref.from, sessionId: ref.fromSessionId };
    return this.start({ type: "link_request", messagingVersion: MESSAGING_VERSION, id, operation: "reply", message, replyTo: ref.id,
      destination, ...(fromWorker ? { fromWorker } : {}) }, signal);
  }
  private start(request: LinkRequest, signal?: AbortSignal): Promise<LinkResult> {
    this.syncSession();
    const self = this.options.self();
    const fail = (status: LinkStatus, reason: string) => Promise.resolve(this.result(request.id, request.operation, [this.routing(status, reason)], false, request.destination));
    if (typeof request.message !== "string" || !request.message.trim()) return fail("failed", "invalid_message");
    if (signal?.aborted) return fail("skipped", "aborted_before_send");
    if (!self || this.options.role() === "disconnected") return fail("failed", "disconnected");
    if (this.options.role() === "client" && !this.options.hubSupported()) return fail("unsupported", "hub_unsupported");
    return new Promise(resolve => {
      let done = false;
      const finish = (values: LinkOutcome[], empty = false) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        this.pending.delete(request.id);
        resolve(this.result(request.id, request.operation, values, empty, request.destination));
      };
      const timer = setTimeout(() => finish([this.routing("unknown", "routing_deadline")]), this.deadline);
      const abort = () => finish([this.routing("unknown", "aborted_after_send")]);
      this.pending.set(request.id, { finish });
      signal?.addEventListener("abort", abort, { once: true });
      if (this.options.role() === "hub") {
        void this.route(request, self).then(receipt => finish(receipt.outcomes, receipt.empty));
      } else if (!this.safeSend(() => this.options.sendHub(request))) finish([this.routing("failed", "hub_send_failed")]);
    });
  }
  private safeSend(send: () => boolean): boolean {
    try { return send(); } catch { return false; }
  }

  /** Only call for registered client sockets; source is the socket's hub-owned identity. */
  handleHub(frame: unknown, source: LinkSource): boolean {
    if (!object(frame) || !types.has(frame.type)) return false;
    if (this.options.role() !== "hub" || frame.messagingVersion !== MESSAGING_VERSION) return true;
    this.syncSession();
    if (frame.type === "link_worker_receipt") {
      const pending = this.workerPending.get(frame.requestId);
      if (pending?.source === source.sessionId && outcomes(frame.outcomes)) {
        // Owners may report their own workers, never other roots or owners.
        if (frame.outcomes.every((o: LinkOutcome) => (o.kind === "workers" || o.kind === "worker") && o.sessionId === source.sessionId)) pending.finish(frame.outcomes.map((o: LinkOutcome) => ({ ...o, name: source.name })));
      }
    } else if (frame.type === "link_request" && this.isRequest(frame)) {
      const epoch = this.epoch;
      void this.route(frame, source).then(receipt => {
        if (this.epoch === epoch) this.safeSend(() => this.options.sendPeer(source, receipt));
      });
    }
    return true;
  }
  /** Client ingress must be the current hub socket, never an arbitrary peer. */
  handleIncoming(frame: unknown): boolean {
    if (!object(frame) || !types.has(frame.type)) return false;
    if (frame.messagingVersion !== MESSAGING_VERSION || this.options.role() === "disconnected") return true;
    this.syncSession();
    if (frame.type === "link_receipt" && text(frame.id) && outcomes(frame.outcomes) && typeof frame.empty === "boolean") {
      this.pending.get(frame.id)?.finish(frame.outcomes, frame.empty);
    } else if (frame.type === "link_delivery" && delivery(frame.message)) {
      try { this.options.deliverRoot(structuredClone(frame.message)); } catch { /* Transport acceptance is not model admission. */ }
    } else if (frame.type === "link_workers" && text(frame.requestId) && delivery(frame.message)
      && optionalWorkerAddress(frame)) {
      const self = this.options.self();
      if (self) {
        const epoch = this.epoch;
        void this.localWorkers(self, frame.message, workerAddress(frame) ? { taskName: frame.taskName, workerId: frame.workerId } : undefined).then(values => {
          if (this.epoch === epoch) this.safeSend(() => this.options.sendHub({ type: "link_worker_receipt", messagingVersion: MESSAGING_VERSION, requestId: frame.requestId, outcomes: values } satisfies LinkWorkerReceipt));
        });
      }
    }
    return true;
  }
  private isRequest(frame: Record<string, any>): frame is LinkRequest {
    return text(frame.id) && typeof frame.message === "string" && !!frame.message.trim()
      && (frame.replyTo === undefined || text(frame.replyTo))
      && ((frame.operation === "broadcast" && (frame.includeSubagents === undefined || typeof frame.includeSubagents === "boolean"))
        || (frame.operation === "reply" && text(frame.replyTo) && object(frame.destination)
          && text(frame.destination.name) && text(frame.destination.sessionId)
          && optionalWorkerAddress(frame.destination)
          && (frame.fromWorker === undefined || (workerAddress(frame.fromWorker) && text(frame.fromWorker.ownerSessionId)))))
      && (frame.fromWorker === undefined || frame.operation === "reply");
  }
  private async route(request: LinkRequest, source: LinkSource): Promise<LinkReceipt> {
    if (request.fromWorker && (request.operation !== "reply" || request.fromWorker.ownerSessionId !== source.sessionId)) {
      return { type: "link_receipt", messagingVersion: MESSAGING_VERSION, id: request.id,
        outcomes: [this.routing("failed", "invalid_worker_owner")], empty: false };
    }
    // One immutable roster selection. Neither replyTo nor client-supplied author fields affect it.
    const snapshot = this.options.peers().map(p => ({ ...p }));
    const message: LinkDelivery = { from: source.name, fromSessionId: source.sessionId, content: request.message, id: request.id,
      ...(request.fromWorker ? { fromWorker: { ...request.fromWorker } } : {}),
      ...(request.replyTo ? { replyTo: request.replyTo } : {}), ...(request.operation === "broadcast" ? { broadcast: true } : {}) };
    const values: LinkOutcome[] = [];
    const workerJobs: Promise<LinkOutcome[]>[] = [];
    if (request.operation === "reply") {
      const target = snapshot.find(p => p.sessionId === request.destination!.sessionId);
      if (!target || groupOf(target.name) !== groupOf(source.name)) {
        values.push({ kind: request.destination!.taskName ? "worker" : "root", ...request.destination!, status: "failed", reason: target ? "outside_group" : "offline" });
      } else if (request.destination!.taskName) {
        workerJobs.push(this.ownerWorkers(target, message, { taskName: request.destination!.taskName, workerId: request.destination!.workerId! }));
      } else values.push(this.root(target, message));
    } else {
      const selected = snapshot.filter(p => p.sessionId !== source.sessionId && groupOf(p.name) === groupOf(source.name));
      for (const target of selected) values.push(this.root(target, message));
      if (request.includeSubagents) {
        // Sender workers are selected too, even though its root inbox is excluded.
        const owners = [...selected, { ...source, messagingVersion: MESSAGING_VERSION }];
        for (const target of owners) workerJobs.push(this.ownerWorkers(target, message));
      }
    }
    for (const result of await Promise.all(workerJobs)) values.push(...result);
    return { type: "link_receipt", messagingVersion: MESSAGING_VERSION, id: request.id, outcomes: values, empty: values.length === 0 };
  }
  private root(target: LinkPeer, message: LinkDelivery): LinkOutcome {
    const base = { kind: "root" as const, name: target.name, ...(target.sessionId ? { sessionId: target.sessionId } : {}) };
    if (!target.sessionId) return { ...base, status: "unsupported", reason: "missing_session_id" };
    if (target.messagingVersion !== MESSAGING_VERSION) return { ...base, status: "unsupported", reason: "peer_unsupported" };
    let accepted = false;
    if (target.sessionId === this.options.self()?.sessionId) {
      try { this.options.deliverRoot(structuredClone(message)); accepted = true; } catch { /* Known local enqueue failure. */ }
    } else accepted = this.safeSend(() => this.options.sendPeer({ name: target.name, sessionId: target.sessionId! }, { type: "link_delivery", messagingVersion: MESSAGING_VERSION, message } satisfies LinkDeliveryFrame));
    return { ...base, status: accepted ? "submitted" : "failed", ...(accepted ? {} : { reason: "root_send_failed" }) };
  }
  private async localWorkers(owner: LinkSource, message: LinkDelivery, worker?: LinkWorkerAddress): Promise<LinkOutcome[]> {
    const base = { kind: worker ? "worker" as const : "workers" as const, name: owner.name, sessionId: owner.sessionId, ...(worker ?? {}) };
    try {
      const workers = typeof this.options.workers === "function" ? this.options.workers() : this.options.workers;
      if (!workers) return [{ ...base, status: "unsupported", reason: "worker_integration_unavailable" }];
      if (worker) {
        const result = await workers.reply({ ...worker }, structuredClone(message));
        return [{ ...base, ...result }];
      }
      const selected = await workers.broadcast(structuredClone(message));
      return selected.map(w => ({ kind: "worker", name: owner.name, sessionId: owner.sessionId, ...w }));
    } catch {
      return [{ ...base, status: "unknown", reason: "worker_callback_failed" }];
    }
  }
  private ownerWorkers(owner: LinkPeer, message: LinkDelivery, worker?: LinkWorkerAddress): Promise<LinkOutcome[]> {
    const base = { kind: worker ? "worker" as const : "workers" as const, name: owner.name, ...(owner.sessionId ? { sessionId: owner.sessionId } : {}), ...(worker ?? {}) };
    if (!owner.sessionId || owner.messagingVersion !== MESSAGING_VERSION) return Promise.resolve([{ ...base, status: "unsupported", reason: !owner.sessionId ? "missing_session_id" : "peer_unsupported" }]);
    const requestId = randomUUID();
    return new Promise(resolve => {
      let done = false;
      const finish = (values: LinkOutcome[]) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        this.workerPending.delete(requestId);
        resolve(values);
      };
      const timer = setTimeout(() => finish([{ ...base, status: "unknown", reason: "worker_routing_deadline" }]), Math.max(1, this.deadline / 2));
      this.workerPending.set(requestId, { source: owner.sessionId!, finish, cancel: () => finish([{ ...base, status: "unknown", reason: "disconnected" }]) });
      if (owner.sessionId === this.options.self()?.sessionId) {
        void this.localWorkers({ name: owner.name, sessionId: owner.sessionId! }, message, worker).then(finish);
      } else if (!this.safeSend(() => this.options.sendPeer({ name: owner.name, sessionId: owner.sessionId! }, { type: "link_workers", messagingVersion: MESSAGING_VERSION, requestId, message, ...(worker ?? {}) } satisfies LinkWorkersFrame))) {
        finish([{ ...base, status: "failed", reason: "owner_send_failed" }]);
      }
    });
  }
}
