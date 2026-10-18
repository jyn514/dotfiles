import { realpathSync } from "node:fs";
import type {
  ExtensionAPI, ExtensionCommandContext, SessionHandoff, SessionInput,
} from "@earendil-works/pi-coding-agent";

export const CONTROL_COMMAND = "subagents-control";
export const CONTROL_ENTRY = "pi-codex-subagents-control";
export const CONTROL_VERSION = 1;
export const CONTINUATION_MESSAGE = "[Subagent harness continuation — not a new human instruction.] Continue the unfinished task using the recorded conversation and results. Do not mechanically repeat completed tools.";
const REPLAY_TYPE = "pi-codex-subagents-replay";
const REPLAY_DETAIL = "piCodexSubagentsReplay";

type Disposition = "started" | "queued" | "handled" | "rejected" | "unknown";
export interface ReplayItem {
  id: string;
  lane: "initial" | "steering" | "followUp" | "nextTurn" | "deferred";
  index: number;
  status: "pending" | Disposition;
}
export interface SavedSession {
  handoff: SessionHandoff;
  items: ReplayItem[];
  marker: "pending" | "started" | "handled" | "rejected" | "unknown" | "none";
  error?: string;
}
export interface ControlRequest {
  action: "inspect" | "capture" | "arm" | "finish" | "disarm" | "discard";
  generation: string;
  snapshot?: SavedSession;
  disposition?: Disposition;
}
export interface ControlRecord {
  version: 1;
  generation: string;
  action: ControlRequest["action"];
  ok: boolean;
  sessionId: string;
  snapshot?: SavedSession;
  error?: string;
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
export function isSavedSession(value: unknown): value is SavedSession {
  if (!object(value) || !object(value.handoff) || !Array.isArray(value.items)) return false;
  const h = value.handoff;
  if (typeof h.requestId !== "string" || typeof h.sessionId !== "string" || typeof h.sessionFile !== "string"
    || !(h.leafId === null || typeof h.leafId === "string") || typeof h.wasActive !== "boolean"
    || !object(h.pending) || !object(h.queueModes)) return false;
  const pending = h.pending;
  if (!["initial", "steering", "followUp", "nextTurn", "deferred"].every(lane => Array.isArray(pending[lane]))) return false;
  if (!["all", "one-at-a-time"].includes(String(h.queueModes.steering))
    || !["all", "one-at-a-time"].includes(String(h.queueModes.followUp))
    || (value.error !== undefined && typeof value.error !== "string")
    || !["pending", "started", "handled", "rejected", "unknown", "none"].includes(String(value.marker))) return false;
  const lanes = ["initial", "steering", "followUp", "nextTurn", "deferred"];
  if (value.items.length !== lanes.reduce((count, lane) => count + (pending[lane] as unknown[]).length, 0)) return false;
  const ids = new Set<string>();
  const slots = new Set<string>();
  return value.items.every(item => {
    if (!object(item) || typeof item.id !== "string" || !item.id || ids.has(item.id)
      || typeof item.lane !== "string" || !Array.isArray(pending[item.lane])
      || !Number.isInteger(item.index) || Number(item.index) < 0
      || Number(item.index) >= (pending[item.lane] as unknown[]).length
      || !["pending", "started", "queued", "handled", "rejected", "unknown"].includes(String(item.status))) return false;
    const slot = `${item.lane}:${item.index}`;
    if (slots.has(slot)) return false;
    slots.add(slot);
    ids.add(item.id);
    return true;
  });
}

/** get_entries returns custom entries, not the command's RPC response. */
export function controlRecord(entries: readonly unknown[], generation: string, action: ControlRequest["action"]): ControlRecord | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (!object(entry) || entry.type !== "custom" || entry.customType !== CONTROL_ENTRY || !object(entry.data)) continue;
    const data = entry.data;
    if (data.generation !== generation || data.action !== action) continue;
    // A malformed newer matching record must not revive an older success.
    if (data.version !== CONTROL_VERSION || typeof data.ok !== "boolean" || typeof data.sessionId !== "string"
      || !data.sessionId || (data.error !== undefined && typeof data.error !== "string")
      || (data.snapshot !== undefined && !isSavedSession(data.snapshot))) return undefined;
    return data as unknown as ControlRecord;
  }
  return undefined;
}

function replayId(payload: unknown): string | undefined {
  if (!object(payload)) return;
  if (payload.kind === "prepared") return replayId(payload.message);
  const details = payload.details;
  if (!object(details) || !object(details[REPLAY_DETAIL])) return;
  const id = details[REPLAY_DETAIL].id;
  return typeof id === "string" && id ? id : undefined;
}

export function snapshotHandoff(handoff: SessionHandoff): SavedSession {
  // This is the canonical payload copy. Replay items only reference its lane/index.
  const copy: SessionHandoff = structuredClone(handoff);
  const items: ReplayItem[] = [];
  const ids = new Set<string>();
  for (const lane of ["initial", "steering", "followUp", "nextTurn", "deferred"] as const) {
    copy.pending[lane].forEach((payload, index) => {
      const id = replayId(payload) ?? `${copy.sessionId}:${copy.requestId}:${lane}:${index}`;
      if (ids.has(id)) throw new Error(`Duplicate replay identity: ${id}`);
      ids.add(id);
      items.push({ id, lane, index, status: "pending" });
    });
  }
  return { handoff: copy, items, marker: "pending" };
}

export function assertSessionAuthority(snapshot: SavedSession, manager: ExtensionCommandContext["sessionManager"]): void {
  if (!isSavedSession(snapshot)) throw new Error("Malformed saved session.");
  const h = snapshot.handoff;
  const file = manager.getSessionFile();
  if (h.sessionId !== manager.getSessionId() || !file || realpathSync(file) !== realpathSync(h.sessionFile)) {
    throw new Error("Saved session identity or canonical file does not match.");
  }
  // A null anchor denotes the root. Any descendant (including shutdown entries) is valid.
  if (h.leafId !== null && !manager.getBranch().some(entry => entry.id === h.leafId)) {
    throw new Error("Saved anchor is not an ancestor of the active session leaf.");
  }
}

/** Pending-or-queued saved occurrences; started/handled admissions are excluded.
 * Not a release-completion predicate: finish.complete permits confirmed queued
 * ownership. ControlRecord.ok is the child release result. */
export function pendingCount(snapshot: SavedSession): number {
  return snapshot.items.filter(item => item.status !== "handled" && item.status !== "started").length;
}

/** Inputs not yet confirmed admitted or consumed; confirmed queues are resolved. */
export function hasUnresolvedInputs(snapshot: SavedSession): boolean {
  return snapshot.items.some(item => item.status === "pending" || item.status === "rejected" || item.status === "unknown");
}

function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function outstanding(item: ReplayItem): boolean { return item.status === "pending" || item.status === "rejected"; }
function provenIds(manager: ExtensionCommandContext["sessionManager"]): Set<string> {
  const result = new Set<string>();
  for (const entry of manager.getBranch()) {
    if (entry.type !== "custom_message") continue;
    const id = replayId(entry);
    if (id) result.add(id);
  }
  return result;
}
/** Reconcile only occurrence IDs proven buffered on the current authoritative branch. */
export function reconcileRecorded(snapshot: SavedSession, manager: ExtensionCommandContext["sessionManager"]): void {
  assertSessionAuthority(snapshot, manager);
  const recorded = provenIds(manager);
  for (const item of snapshot.items) if (recorded.has(item.id)) item.status = "handled";
}

function payload(snapshot: SavedSession, item: ReplayItem): unknown {
  return snapshot.handoff.pending[item.lane][item.index];
}
function prepared(snapshot: SavedSession, item: ReplayItem): Extract<SessionInput, { kind: "prepared" }>["message"] {
  const original = payload(snapshot, item);
  if (!object(original)) throw new Error(`Invalid prepared payload ${item.id}`);
  const message = original.kind === "prepared" ? original.message : original;
  if (!object(message)) throw new Error(`Invalid prepared payload ${item.id}`);
  const details = object(message.details) ? message.details : {};
  const prior = object(details[REPLAY_DETAIL]) ? details[REPLAY_DETAIL] : {};
  return {
    customType: typeof message.customType === "string" ? message.customType : REPLAY_TYPE,
    content: message.content as Extract<SessionInput, { kind: "prepared" }>["message"]["content"],
    display: typeof message.display === "boolean" ? message.display : true,
    details: { ...details, [REPLAY_DETAIL]: {
      ...prior, id: item.id, lane: prior.lane ?? item.lane,
      originalRole: prior.originalRole ?? message.role, originalTimestamp: prior.originalTimestamp ?? message.timestamp,
    } },
  };
}

type Update = (snapshot: SavedSession) => void;

/** Persist admission intent. A failed pre-effect write cannot create an unknown
 * admission: this caller has not invoked the native producer yet. */
function beginItemAdmission(snapshot: SavedSession, item: ReplayItem, update?: Update): ReplayItem["status"] {
  const previous = item.status;
  item.status = "unknown";
  try { update?.(snapshot); }
  catch (error) { item.status = previous; throw error; }
  return previous;
}

interface Armed {
  snapshot: SavedSession;
  update?: Update;
  installing: boolean;
  started: boolean;
  finishAttempts?: number;
}

/** Only this controller submits fresh inputs. Lifecycle callbacks install prepared queues synchronously. */
export class SessionReplay {
  private armed?: Armed;
  private readonly captures = new Map<string, SavedSession>();
  private readonly pi: ExtensionAPI;
  private finishInFlight?: Promise<{ complete: boolean; error?: string }>;

  constructor(pi: ExtensionAPI) {
    this.pi = pi;
    pi.on("agent_start", (_event, ctx) => {
      const state = this.armed;
      if (!state || state.installing || state.started || ctx.sessionManager.getSessionId() !== state.snapshot.handoff.sessionId) return;
      state.started = true;
      // agent_start identifies a run, not the input that caused it. A handled
      // marker may have started an unrelated prepared turn in an input handler.
      if (state.snapshot.marker === "pending") state.snapshot.marker = "unknown";
      // This listener is awaited by core. Never call/await submitInput here.
      try {
        state.update?.(state.snapshot);
        for (const lane of ["initial", "steering", "followUp"] as const) {
          for (const item of state.snapshot.items.filter(item => item.lane === lane && outstanding(item))) {
            const message = prepared(state.snapshot, item);
            if (ctx.isIdle() || this.pi.getPauseState() !== "unpaused") continue;
            const previous = beginItemAdmission(state.snapshot, item, state.update);
            if (this.armed !== state) { item.status = previous; return; }
            // Narrow native producer contract: with an active unpaused run,
            // prepared steer/followUp transfers to retained Agent queues before
            // any await (including when a queue observer reports an error).
            // Recheck AFTER progress callbacks, which may themselves pause.
            if (ctx.isIdle() || this.pi.getPauseState() !== "unpaused") {
              item.status = previous;
              state.update?.(state.snapshot);
              continue;
            }
            this.pi.sendMessage(message, { deliverAs: lane === "followUp" ? "followUp" : "steer" });
            item.status = "queued";
            if (this.armed === state) state.update?.(state.snapshot);
          }
        }
      } catch (error) {
        state.snapshot.error = errorText(error);
        // Observer failures cannot undo any ownership already transferred.
        try { if (this.armed === state) state.update?.(state.snapshot); } catch { /* retained in memory */ }
      }
    });
    const observeRecorded = (_event: unknown, ctx: Pick<ExtensionCommandContext, "sessionManager">): void => {
      const state = this.armed;
      if (!state || state.snapshot.handoff.sessionId !== ctx.sessionManager.getSessionId()) return;
      const before = state.snapshot.items.map(item => item.status).join(",");
      this.reconcile(ctx, state.snapshot);
      if (before !== state.snapshot.items.map(item => item.status).join(",")) {
        try { state.update?.(state.snapshot); }
        catch (error) { state.snapshot.error = errorText(error); }
      }
    };
    // message_end precedes native buffering. A subsequent event may inspect the
    // buffered branch, but the callback's message alone is not commit evidence.
    pi.on("message_start", observeRecorded);
    pi.on("agent_end", observeRecorded);
  }

  async capture(ctx: ExtensionCommandContext, requestId: string): Promise<SavedSession> {
    const key = `${ctx.sessionManager.getSessionId()}:${requestId}`;
    const retained = this.captures.get(key);
    if (retained) return retained;
    const state = this.armed;
    let snapshot: SavedSession;
    if (state) {
      const update = state.update;
      state.update = undefined; // the new capture caller owns publication
      try { await this.recapture(ctx, state, requestId); }
      catch (error) { state.update = update; throw error; }
      this.armed = undefined;
      snapshot = state.snapshot;
      // A new save cannot resolve a lost marker admission acknowledgment.
      // Known admitted runs may be suspended afresh; unknown markers stay unknown.
      if (snapshot.marker !== "unknown") snapshot.marker = "pending";
    } else snapshot = snapshotHandoff(await ctx.handoff(requestId));
    this.captures.set(key, snapshot);
    return snapshot;
  }

  async arm(ctx: ExtensionCommandContext, snapshot: SavedSession, onUpdate?: Update): Promise<void> {
    if (typeof ctx.handoff !== "function" || typeof ctx.submitInput !== "function"
      || typeof this.pi.resume !== "function" || typeof this.pi.sendMessage !== "function"
      || typeof this.pi.getPauseState !== "function") {
      throw new Error("Native handoff/submitInput replay capabilities are required.");
    }
    assertSessionAuthority(snapshot, ctx.sessionManager);
    if (this.armed) throw new Error("Replay is already armed.");
    // A valid ancestor manifest may lag later admission/progress writes. Retire
    // transcript-proven IDs before staging even one aside or prepared queue.
    reconcileRecorded(snapshot, ctx.sessionManager);
    if (snapshot.marker === "started" || snapshot.marker === "unknown") {
      throw new Error("Prior marker admission requires reconciliation; it cannot be retried.");
    }
    if (snapshot.items.some(item => item.status === "unknown")) throw new Error("Unknown input admission requires reconciliation before retry.");
    this.captures.clear();
    const state: Armed = { snapshot, update: onUpdate, installing: true, started: false };
    this.armed = state;
    snapshot.marker = "pending";
    // A new explicit release may retry known rejected deferred work once.
    for (const item of snapshot.items) if (item.lane === "deferred" && item.status === "rejected") item.status = "pending";
    delete snapshot.error;
    onUpdate?.(snapshot);
    this.pi.resume();
    try {
      for (const item of snapshot.items.filter(item => item.lane === "nextTurn" && outstanding(item))) {
        const message = prepared(snapshot, item);
        beginItemAdmission(snapshot, item, onUpdate);
        if (this.armed !== state) throw new Error("Saved replay was discarded or replaced.");
        const result = await ctx.submitInput({ kind: "prepared", message, options: { deliverAs: "nextTurn" } });
        item.status = result.disposition;
        if (this.armed !== state) throw new Error("Saved replay was discarded or replaced.");
        if (result.disposition === "rejected") snapshot.error = result.error;
        onUpdate?.(snapshot);
        if (result.disposition !== "queued") throw new Error(snapshot.error ?? "Aside was not staged.");
      }
      state.installing = false;
    } catch (error) {
      snapshot.error = errorText(error);
      // Leave armed state for finish/disarm to recapture already staged work.
      state.installing = false;
      throw error;
    }
  }

  private reconcile(ctx: Pick<ExtensionCommandContext, "sessionManager">, snapshot: SavedSession): void {
    reconcileRecorded(snapshot, ctx.sessionManager);
  }

  /** Stop/export staged work after failed marker admission; replay tags survive subsequent handoffs. */
  private async recapture(ctx: ExtensionCommandContext, state: Armed, requestId?: string): Promise<void> {
    const previous = state.snapshot;
    const captured = snapshotHandoff(await ctx.handoff(requestId ?? `${previous.handoff.requestId}:replay:${crypto.randomUUID()}`));
    if (this.armed !== state) throw new Error("Saved replay was discarded or replaced.");
    this.reconcile(ctx, previous);
    const recorded = provenIds(ctx.sessionManager);
    const byId = new Map(captured.items.filter(item => !recorded.has(item.id)).map(item => [item.id, item]));
    // Keep extension-owned inputs, but do not keep a second copy of admitted core-owned work.
    for (const item of previous.items) {
      if (recorded.has(item.id) || item.status === "handled" || item.status === "started" || byId.has(item.id)) continue;
      if (item.status === "queued") continue;
      const lane = item.lane;
      const lanePayloads = captured.handoff.pending[lane] as unknown[];
      const index = lanePayloads.length;
      lanePayloads.push(structuredClone(payload(previous, item)));
      // A stopped handoff plus transcript absence proves a tagged prepared
      // occurrence was never admitted. Raw unknown outcomes remain unknown.
      const recoverablePrepared = item.lane !== "deferred" || object(payload(previous, item)) && (payload(previous, item) as { kind?: string }).kind === "prepared";
      const retained = { ...item, index, status: item.status === "unknown" && recoverablePrepared ? "pending" as const : item.status };
      captured.items.push(retained);
      byId.set(item.id, retained);
    }
    captured.items = captured.items.filter(item => !recorded.has(item.id));
    for (const lane of ["initial", "steering", "followUp", "nextTurn", "deferred"] as const) {
      const items = captured.items.filter(item => item.lane === lane);
      const bodies = items.map(item => payload(captured, item));
      (captured.handoff.pending as Record<ReplayItem["lane"], unknown[]>)[lane] = bodies;
      items.forEach((item, index) => { item.index = index; });
    }
    captured.handoff.wasActive ||= previous.handoff.wasActive;
    previous.handoff = captured.handoff;
    previous.items = captured.items;
    state.update?.(previous);
  }

  async finish(ctx: ExtensionCommandContext, disposition: Disposition, onUpdate?: Update): Promise<{ complete: boolean; error?: string }> {
    if (this.finishInFlight) return this.finishInFlight;
    const operation = this.finishArmed(ctx, disposition, onUpdate);
    this.finishInFlight = operation;
    try { return await operation; }
    finally { if (this.finishInFlight === operation) this.finishInFlight = undefined; }
  }

  private async finishArmed(ctx: ExtensionCommandContext, disposition: Disposition, onUpdate?: Update): Promise<{ complete: boolean; error?: string }> {
    const state = this.armed;
    if (!state) return { complete: false, error: "No replay is armed in this process." };
    if (onUpdate) state.update = onUpdate;
    const snapshot = state.snapshot;
    // Only the actual input admission may prove started. A bare agent_start
    // cannot resolve a lost acknowledgment, nor override handled/rejected.
    const explicitRetry = (state.finishAttempts ?? 0) > 0;
    state.finishAttempts = (state.finishAttempts ?? 0) + 1;
    snapshot.marker = disposition === "queued" ? "unknown" : disposition;
    state.update?.(snapshot);
    if (disposition !== "started") {
      await this.recapture(ctx, state);
      this.armed = undefined;
      snapshot.error = `Resume incomplete: continuation ${disposition}.`;
      state.update?.(snapshot);
      return { complete: false, error: snapshot.error };
    }
    try {
      this.reconcile(ctx, snapshot);
      if (this.pi.getPauseState() !== "unpaused" && hasUnresolvedInputs(snapshot)) {
        snapshot.error = "Replay installation was held by pause; unadmitted inputs remain pending.";
        state.update?.(snapshot);
        return { complete: false, error: snapshot.error };
      }
      // A later explicit finish/unpause retries known-unadmitted rejections,
      // never the first finish itself and never an unknown handler outcome.
      if (explicitRetry) for (const item of snapshot.items) {
        if (item.lane === "deferred" && item.status === "rejected") item.status = "pending";
      }
      // A progress write may have stopped the synchronous installer. Explicit
      // same-process finish retries only inputs that never reached admission,
      // without submitting a second continuation marker.
      for (const lane of ["initial", "steering", "followUp"] as const) {
        for (const item of snapshot.items.filter(item => item.lane === lane && item.status === "pending")) {
          const message = prepared(snapshot, item);
          beginItemAdmission(snapshot, item, state.update);
          if (this.armed !== state) return { complete: false, error: "Saved replay was discarded or replaced." };
          const result = await ctx.submitInput({ kind: "prepared", message, options: {
            deliverAs: lane === "followUp" ? "followUp" : "steer", ...(ctx.isIdle() ? { triggerTurn: true } : {}),
          } });
          item.status = result.disposition;
          if (this.armed !== state) return { complete: false, error: "Saved replay was discarded or replaced." };
          if (result.disposition === "rejected") snapshot.error = result.error;
          state.update?.(snapshot);
          if (result.disposition === "rejected") return { complete: false, error: snapshot.error };
        }
      }
      for (const item of snapshot.items.filter(item => item.lane === "deferred")) {
        if (item.status === "rejected" || item.status === "unknown") break;
        if (item.status !== "pending") continue;
        const input = structuredClone(payload(snapshot, item)) as SessionInput;
        if (input.kind === "prepared") {
          input.message = prepared(snapshot, item);
          if (!ctx.isIdle() && input.options?.deliverAs === undefined && input.options?.triggerTurn !== false) {
            input.options = { ...input.options, deliverAs: "followUp" };
          }
        } else if (!ctx.isIdle() && input.options?.streamingBehavior === undefined) {
          input.options = { ...input.options, streamingBehavior: "followUp" };
        }
        beginItemAdmission(snapshot, item, state.update);
        if (this.armed !== state) return { complete: false, error: "Saved replay was discarded or replaced." };
        const result = await ctx.submitInput(input);
        item.status = result.disposition;
        if (this.armed !== state) return { complete: false, error: "Saved replay was discarded or replaced." };
        if (result.disposition === "rejected") snapshot.error = result.error;
        state.update?.(snapshot);
        // A failed handler is not retried automatically; later input remains ordered behind it.
        if (result.disposition === "rejected") break;
      }
      this.reconcile(ctx, snapshot);
      const incomplete = hasUnresolvedInputs(snapshot);
      state.update?.(snapshot);
      if (!incomplete) this.armed = undefined;
      return { complete: !incomplete, ...(incomplete ? { error: snapshot.error ?? "Replay has unresolved inputs." } : {}) };
    } catch (error) {
      snapshot.error = errorText(error);
      try { if (this.armed === state) state.update?.(snapshot); } catch { /* retain the original admission uncertainty */ }
      return { complete: false, error: snapshot.error };
    }
  }

  /** Call only after durable revocation. Forget extension-owned work without
   * resuming, aborting, or clearing anything already admitted to native core. */
  discardSavedInputs(): void {
    this.armed = undefined;
    this.captures.clear();
    this.finishInFlight = undefined;
  }

  /** Disarm is cancellation, never evidence that the marker was admitted. */
  async disarm(ctx: ExtensionCommandContext, onUpdate?: Update): Promise<SavedSession | undefined> {
    const state = this.armed;
    if (!state) return;
    if (onUpdate) state.update = onUpdate;
    await this.recapture(ctx, state);
    this.armed = undefined;
    return state.snapshot;
  }

  async resume(ctx: ExtensionCommandContext, snapshot: SavedSession, onUpdate?: Update): Promise<{ complete: boolean; error?: string }> {
    if (snapshot.marker === "started" && this.armed?.snapshot === snapshot && this.armed.started) {
      return this.finish(ctx, "started", onUpdate);
    }
    if (snapshot.marker === "started" || snapshot.marker === "unknown") {
      return { complete: false, error: "Prior marker admission requires reconciliation; it cannot be retried." };
    }
    if (!snapshot.handoff.wasActive && snapshot.items.length === 0) {
      assertSessionAuthority(snapshot, ctx.sessionManager);
      this.pi.resume();
      snapshot.marker = "none";
      onUpdate?.(snapshot);
      return { complete: true };
    }
    try {
      await this.arm(ctx, snapshot, onUpdate);
      const previousMarker = snapshot.marker;
      snapshot.marker = "unknown";
      try { onUpdate?.(snapshot); } // Persist uncertainty BEFORE transferring marker ownership.
      catch (error) { snapshot.marker = previousMarker; throw error; }
      const result = await ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } });
      return await this.finish(ctx, result.disposition, onUpdate);
    } catch (error) {
      snapshot.error = errorText(error);
      if (this.armed?.snapshot !== snapshot) return { complete: false, error: snapshot.error };
      if (this.armed) {
        try {
          await this.recapture(ctx, this.armed);
          this.armed = undefined;
        } catch (captureError) { snapshot.error += `; recapture failed: ${errorText(captureError)}`; }
      }
      onUpdate?.(snapshot);
      return { complete: false, error: snapshot.error };
    }
  }
}
