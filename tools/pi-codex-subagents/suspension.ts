import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { getRunsDir, parentScopeKey, type AgentCompletionEvent, type AgentManager, type CompletionState } from "./core.js";
import { assertSessionAuthority, isSavedSession, pendingCount, SessionReplay, type SavedSession } from "./handoff.js";

type Phase = "preparing" | "saved" | "restoring" | "incomplete" | "consumed" | "discarded";
export interface SuspensionGroup {
  version: 1;
  generation: string;
  captureGeneration?: string;
  needsFreshCapture?: boolean;
  discardCleanupPending?: boolean;
  parentId: string;
  parentFile: string;
  phase: Phase;
  parent?: SavedSession;
  children: Record<string, SavedSession>;
  requiredChildren: string[];
  inventoryComplete: boolean;
  resumed: string[];
  parentResumed: boolean;
  completions: CompletionState;
  error?: string;
}

type GroupFileIO = Pick<typeof fs, "mkdirSync" | "openSync" | "writeFileSync" | "fsyncSync" | "closeSync" | "renameSync" | "unlinkSync">;

/** Publication and durability are distinct: never describe an uncertain rename as a clean rollback. */
export class GroupPublicationUncertainError extends Error {
  constructor(readonly file: string, readonly publishedSnapshot: string, cause: unknown) {
    super(`Group replacement is visible at ${file} with recoverable captured payloads, but directory durability is unconfirmed: ${message(cause)}. Saved publication is not confirmed; keep the parent open.`);
    this.name = "GroupPublicationUncertainError";
  }
}

/** Rename is the visibility point; directory fsync is the durability acknowledgment. */
export function writeGroup(file: string, group: SuspensionGroup, io: GroupFileIO = fs): void {
  io.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${randomUUID()}.tmp`;
  const serialized = JSON.stringify(group, null, 2) + "\n";
  let fd: number | undefined;
  try {
    fd = io.openSync(temporary, "wx", 0o600);
    io.writeFileSync(fd, serialized);
    io.fsyncSync(fd);
    io.closeSync(fd); fd = undefined;
    io.renameSync(temporary, file);
    try {
      const directory = io.openSync(path.dirname(file), "r");
      try { io.fsyncSync(directory); } finally { io.closeSync(directory); }
    } catch (error) { throw new GroupPublicationUncertainError(file, serialized, error); }
  } finally {
    if (fd !== undefined) io.closeSync(fd);
    try { io.unlinkSync(temporary); } catch (error: any) { if (error.code !== "ENOENT") throw error; }
  }
}

/** Conservative lock: neither age nor a PID probe grants authority to steal it. */
export class ParentScopeClaim {
  private token?: string;
  private identity?: { dev: number; ino: number };
  constructor(readonly file: string) {}
  acquire(): void {
    if (this.token) return;
    fs.mkdirSync(path.dirname(this.file), { recursive: true, mode: 0o700 });
    const token = randomUUID();
    let fd: number;
    try { fd = fs.openSync(this.file, "wx", 0o600); }
    catch (error: any) {
      if (error.code !== "EEXIST") throw error;
      throw new Error(`Suspension scope is already claimed: ${this.file}. Close the other parent first. After verifying no parent/restore process owns it, manually remove this claim; PID alone is not proof of abandonment.`);
    }
    // Retain ownership even if writing diagnostics fails, so ordinary shutdown can release it.
    this.token = token;
    const { dev, ino } = fs.fstatSync(fd);
    this.identity = { dev, ino };
    try { fs.writeFileSync(fd, JSON.stringify({ token, pid: process.pid, createdAt: new Date().toISOString() })); fs.fsyncSync(fd); }
    finally { fs.closeSync(fd); }
  }
  release(): void {
    if (!this.token) return;
    const stat = fs.statSync(this.file);
    if (stat.dev !== this.identity?.dev || stat.ino !== this.identity?.ino) throw new Error(`Suspension claim ownership changed: ${this.file}`);
    fs.unlinkSync(this.file);
    this.token = undefined;
    this.identity = undefined;
  }
}

function canonicalFile(file: string): string {
  try { return fs.realpathSync(file); }
  catch (error: any) {
    if (error.code !== "ENOENT") throw error;
    return path.join(fs.realpathSync(path.dirname(file)), path.basename(file));
  }
}

function message(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function revoked(group: SuspensionGroup): boolean { return group.phase === "consumed" || group.phase === "discarded"; }
function parseGroup(value: unknown): SuspensionGroup {
  const g = value as SuspensionGroup;
  if (!g || g.version !== 1 || typeof g.generation !== "string" || !g.generation
    || typeof g.parentId !== "string" || typeof g.parentFile !== "string"
    || !["preparing", "saved", "restoring", "incomplete", "consumed", "discarded"].includes(g.phase)
    || !g.children || typeof g.children !== "object" || Array.isArray(g.children)
    || !Array.isArray(g.requiredChildren) || !g.requiredChildren.every(id => typeof id === "string")
    || typeof g.inventoryComplete !== "boolean"
    || (g.discardCleanupPending !== undefined && typeof g.discardCleanupPending !== "boolean")
    || !Array.isArray(g.resumed) || typeof g.parentResumed !== "boolean"
    || !g.completions || !Array.isArray(g.completions.mailbox) || !Array.isArray(g.completions.delivered) || !Array.isArray(g.completions.targets)) {
    throw new Error("Malformed suspension group; retain the file for manual recovery.");
  }
  if ((g.parent !== undefined && !isSavedSession(g.parent)) || !Object.values(g.children).every(isSavedSession)
    || !g.resumed.every(id => typeof id === "string" && Object.hasOwn(g.children, id))) {
    throw new Error("Malformed suspension snapshots/progress; retain the file for manual recovery.");
  }
  if (g.phase === "saved" && !g.parent) throw new Error("Saved suspension group has no parent capture.");
  return g;
}

/** Extension-owned orchestration only; no lifecycle callback awaits fresh admission. */
export class SuspensionCoordinator {
  private group?: SuspensionGroup;
  private claim?: ParentScopeClaim;
  private file?: string;
  private busy = false;
  private liveGeneration = false;
  private discoveryError?: string;
  private commandContext?: ExtensionCommandContext;
  private delivery = Promise.resolve();
  private readonly legacyDelivery = new Set<string>();
  private readonly replay: SessionReplay;

  constructor(private readonly pi: ExtensionAPI, private readonly manager: AgentManager,
    private readonly completionMessage: (event: AgentCompletionEvent) => any,
    private readonly runsDir: () => string = getRunsDir,
    private readonly groupWriter: typeof writeGroup = writeGroup) {
    this.replay = new SessionReplay(pi);
  }

  setCommandContext(ctx: ExtensionCommandContext): void { this.commandContext = ctx; }

  isPaused(parentId: string): boolean {
    return !!this.discoveryError || !!(this.group && this.group.parentId === parentId && !revoked(this.group));
  }
  isPreparing(parentId: string): boolean { return this.group?.parentId === parentId && this.group.phase === "preparing"; }

  /** Called synchronously, before session_start's first await or automatic work. */
  discover(ctx: any): void {
    this.claim?.release();
    this.commandContext = undefined;
    this.legacyDelivery.clear();
    this.discoveryError = undefined;
    this.group = undefined;
    this.liveGeneration = false;
    this.file = path.join(this.runsDir(), parentScopeKey(ctx.sessionManager.getSessionId()), "group.json");
    this.claim = new ParentScopeClaim(path.join(path.dirname(this.file), ".group.claim"));
    if (!fs.existsSync(this.file)) return;
    try {
      const group = parseGroup(JSON.parse(fs.readFileSync(this.file, "utf8")));
      // Revocation is session-wide, not an entry on the navigable transcript tree.
      this.group = group;
      if (revoked(group)) return;
      this.pi.requestPause();
      this.validate(ctx, false);
      this.claim.acquire();
      this.validate(ctx);
      this.manager.beginPause(group.parentId);
      this.manager.restoreCompletionState(group.parentId, group.completions);
    } catch (error) {
      this.pi.requestPause();
      this.discoveryError = message(error);
      ctx.ui?.notify?.(`Suspension incomplete: ${this.discoveryError}`, "error");
    }
  }

  private assertDiscardCleanupComplete(): void {
    if (this.group?.phase === "discarded" && (this.group.discardCleanupPending
      || this.group.error?.startsWith("Discard cleanup incomplete"))) {
      throw new Error("Discard cleanup is incomplete; retry /pause --discard before starting a new suspension generation.");
    }
  }

  private assertNativeCapabilities(ctx: ExtensionCommandContext): void {
    const missing = [
      ["ctx.handoff", ctx?.handoff], ["ctx.submitInput", ctx?.submitInput],
      ["pi.requestPause", this.pi.requestPause], ["pi.resume", this.pi.resume], ["pi.getPauseState", this.pi.getPauseState],
    ].filter(([, value]) => typeof value !== "function").map(([name]) => name);
    if (missing.length) throw new Error(`Unsupported Pi: subagent suspension requires native handoff/admission and pause controls (missing ${missing.join(", ")}). Upgrade Pi before /pause or /unpause.`);
  }

  private validate(ctx: any, anchor = true): void {
    const group = this.group!;
    const file = ctx.sessionManager.getSessionFile();
    if (group.parentId !== ctx.sessionManager.getSessionId() || !file || canonicalFile(file) !== group.parentFile) {
      throw new Error("Suspension parent identity/canonical path mismatch; copies, forks and imports cannot restore this group.");
    }
    if (anchor && group.parent) assertSessionAuthority(group.parent, ctx.sessionManager);
  }
  private persist(): void { if (!this.file || !this.group) throw new Error("No suspension group is open."); this.groupWriter(this.file, this.group); }
  private updateCompletions(): void { this.group!.completions = this.manager.getCompletionState(this.group!.parentId); }

  /** IDs in history or exported prepared inputs prove ownership; void sendMessage does not. */
  private reconcileCompletions(ctx: any): void {
    const ids = new Set<string>();
    const inspect = (value: any): void => {
      if (!value || typeof value !== "object") return;
      if (typeof value.details?.completionId === "string") ids.add(value.details.completionId);
      if (value.message) inspect(value.message);
    };
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type === "custom_message") inspect(entry);
      if (entry.message) inspect(entry.message);
    }
    const parent = this.group?.parent;
    if (parent) for (const lane of Object.values(parent.handoff.pending)) for (const input of lane) inspect(input);
    for (const id of ids) this.manager.markCompletionDelivered(id);
    if (this.group) this.updateCompletions();
  }

  private assertChildrenAccountedFor(): void {
    const group = this.group!;
    if (!group.inventoryComplete) throw new Error("Incomplete child inventory after restart; no release is authorized.");
    for (const id of group.requiredChildren) {
      if (group.children[id] || group.resumed.includes(id)) continue;
      const terminal = this.manager.listAgents(undefined, group.parentId).some(agent => {
        const info = this.manager.getAgentInfo(agent.agent_name, group.parentId);
        return info.id === id && (info.status === "completed" || info.status === "failed");
      });
      if (!terminal) throw new Error(`Child ${id} has no captured ownership or genuine terminal result; suspension remains incomplete.`);
    }
  }

  status(): string {
    if (this.discoveryError) return `Suspension incomplete (pending unknown): ${this.discoveryError}`;
    const group = this.group;
    if (!group) return "Suspension: live; pending 0.";
    const count = revoked(group) ? 0 : (group.parent ? pendingCount(group.parent) : 0)
      + Object.values(group.children).reduce((sum, saved) => sum + pendingCount(saved), 0);
    const cleanup = group.discardCleanupPending && !group.error ? "; discard cleanup pending; retry /pause --discard" : "";
    return `Suspension: ${group.phase}; pending ${count}${group.error ? `; ${group.error}` : cleanup}.`;
  }

  async pause(ctx: ExtensionCommandContext, exit = false): Promise<void> {
    this.assertNativeCapabilities(ctx);
    if (this.busy) throw new Error("Suspension operation is already in progress; use /pause --status.");
    if (this.discoveryError) throw new Error(this.discoveryError);
    this.assertDiscardCleanupComplete();
    this.busy = true;
    this.commandContext = ctx;
    try {
      const id = ctx.sessionManager.getSessionId();
      if (!this.file) this.discover(ctx);
      this.assertDiscardCleanupComplete();
      this.claim!.acquire();
      if (!this.group || revoked(this.group)) {
        const sessionFile = ctx.sessionManager.getSessionFile();
        if (!sessionFile) throw new Error("Durable suspension requires a persisted parent session.");
        this.group = { version: 1, generation: randomUUID(), parentId: id, parentFile: canonicalFile(sessionFile),
          phase: "preparing", needsFreshCapture: false, children: {}, requiredChildren: [], inventoryComplete: false, resumed: [], parentResumed: false,
          completions: this.manager.getCompletionState(id) };
        this.liveGeneration = true;
      }
      this.validate(ctx);
      if (!this.liveGeneration && !this.group.parent) throw new Error("Parent capture is missing after restart; retain this incomplete generation for recovery or explicitly discard it.");
      if (!this.liveGeneration && !this.group.inventoryComplete) throw new Error("Incomplete child inventory after restart; retain captured payloads for manual recovery or explicitly discard them.");
      if (this.group.phase === "saved") { if (exit) ctx.shutdown(); return; }
      const acceptedSinceCapture = this.group.needsFreshCapture ?? !!(this.group.resumed.length || this.group.parentResumed);
      const captureGeneration = acceptedSinceCapture ? `${this.group.generation}:capture:${randomUUID()}`
        : this.group.captureGeneration ?? this.group.generation;
      this.group.needsFreshCapture = false;
      this.group.captureGeneration = captureGeneration;
      this.group.phase = "preparing";
      this.manager.beginPause(id);
      this.pi.requestPause();
      this.persist();
      // beginPause releases waits. The entire accepted tool batch drains before children stop.
      await this.manager.drainSubmissions(id);
      if (!this.group.parent || this.group.parentResumed || this.group.parent.marker === "started") {
        // Acknowledged parent replay is a new run. A fenced partial replay must retain its current request ID.
        const requestId = this.group.parentResumed ? `${this.group.generation}:parent:${randomUUID()}`
          : this.group.parent?.handoff.requestId ?? this.group.generation;
        this.group.parent = await this.replay.capture(ctx, requestId);
        this.group.parentResumed = false;
        this.persist();
      }
      // Handoff also finishes later tools in the admitted batch. Recheck their nested submissions/failures.
      await this.manager.drainSubmissions(id);
      const activeIds = this.manager.listAgents(undefined, id)
        .filter(agent => ["starting", "running", "suspended"].includes(agent.agent_status))
        .map(agent => this.manager.getAgentInfo(agent.agent_name, id).id);
      this.group.requiredChildren = [...new Set([...this.group.requiredChildren, ...activeIds])];
      this.group.inventoryComplete = true;
      this.persist();
      if (!this.liveGeneration && Object.keys(this.group.children).length) {
        await this.manager.prepareChildren(id, this.group.children);
        this.persist(); // Preparation may recapture/disarm held children and mutate their saved payloads.
      }
      const children = await this.manager.captureChildren(id, captureGeneration, (childId, saved) => {
        this.group!.children[childId] = saved;
        this.group!.resumed = this.group!.resumed.filter(id => id !== childId);
        this.updateCompletions();
        this.persist(); // Manager MUST await this synchronous callback before closing this child.
      });
      Object.assign(this.group.children, children);
      this.assertChildrenAccountedFor();
      // Parent shutdown records may be descendants; this checks ancestry, not exact leaf equality.
      this.validate(ctx);
      this.reconcileCompletions(ctx);
      // The stopped core now proves whether each earlier void delivery retained ownership.
      this.legacyDelivery.clear();
      delete this.group.error;
      // Stage the full reconciled payload durably before changing only the publication status.
      // If the final rename's directory fsync fails, either surviving name still owns every capture.
      this.persist();
      this.group.phase = "saved";
      try { this.persist(); } catch (error) { this.group.phase = "incomplete"; throw error; }
      ctx.ui?.notify?.(this.status(), "info");
      if (exit) ctx.shutdown();
    } catch (error) {
      if (this.group && !revoked(this.group)) {
        this.group.phase = "incomplete"; this.group.error = message(error);
        try { this.updateCompletions(); this.persist(); } catch { /* captures remain owned in memory */ }
      }
      throw error;
    } finally { this.busy = false; }
  }

  async unpause(ctx: ExtensionCommandContext): Promise<void> {
    this.assertNativeCapabilities(ctx);
    if (this.busy) throw new Error("Suspension operation is already in progress.");
    if (this.discoveryError) throw new Error(this.discoveryError);
    if (!this.group || revoked(this.group)) throw new Error("No saved suspension group. /resume remains the session picker.");
    this.busy = true;
    this.commandContext = ctx;
    const group = this.group;
    try {
      this.claim!.acquire();
      this.validate(ctx);
      if (!group.parent && !this.liveGeneration) throw new Error("Parent capture is missing after restart; no continuation admission can be inferred.");
      if (!this.liveGeneration) this.assertChildrenAccountedFor();
      const unresolved = (saved: SavedSession) => saved.marker === "unknown" || (!this.liveGeneration && saved.marker === "started") || saved.items.some(item => item.status === "unknown");
      for (const [id, saved] of Object.entries(group.children)) {
        if (!group.resumed.includes(id) && unresolved(saved)) throw new Error(`Child ${id} has unresolved prior admission; reconcile it before retry, never resend speculatively.`);
      }
      if (group.parent && !group.parentResumed && unresolved(group.parent)) throw new Error("Parent has unresolved prior admission; reconcile it before retry, never resend speculatively.");
      group.phase = "restoring"; delete group.error; this.persist();
      // Never release A until every needed child has been launched held and validated.
      const needed = Object.fromEntries(Object.entries(group.children).filter(([id]) => !group.resumed.includes(id)));
      await this.manager.prepareChildren(group.parentId, needed);
      this.persist(); // Persist all preparation-side ownership changes before the first release.
      // From here, admission progress belongs to this process, even for a reopened generation.
      this.liveGeneration = true;
      for (const [id, saved] of Object.entries(needed)) {
        const result = await this.manager.resumeChild(group.parentId, id, saved, updated => {
          group.children[id] = updated;
          if (updated.marker === "started") group.needsFreshCapture = true;
          this.persist();
        });
        if (!result.complete) throw new Error(result.error ?? `Child ${id}: resume incomplete.`);
        if (saved.marker === "started") group.needsFreshCapture = true;
        group.resumed.push(id); this.persist();
      }
      if (group.parent && !group.parentResumed) {
        const result = await this.replay.resume(ctx, group.parent, saved => {
          group.parent = saved;
          if (saved.marker === "started") group.needsFreshCapture = true;
          this.persist();
        });
        if (!result.complete) throw new Error(result.error ?? "Parent resume incomplete.");
        group.parentResumed = true; group.needsFreshCapture = true; this.persist();
      } else {
        // Either the original live run still owns continuation, or prior replay was already acknowledged.
        // Unfence without submitting another marker in either case.
        this.pi.resume();
      }
      await this.manager.releaseUncapturedChildren(group.parentId);
      this.reconcileCompletions(ctx);
      await this.flushCompletions(ctx, true);
      group.phase = "consumed";
      try { this.persist(); } catch (error) {
        if (error instanceof GroupPublicationUncertainError) {
          // A visible revocation must never be overwritten by an incomplete/replayable manifest.
          group.error = message(error);
          this.manager.endPause(group.parentId);
          this.claim!.release();
        } else group.phase = "incomplete";
        throw error;
      }
      this.manager.endPause(group.parentId);
      this.claim!.release();
      // Catch completions that arrived while an awaited admission was draining the earlier mailbox snapshot.
      this.scheduleCompletions(ctx);
      ctx.ui?.notify?.(this.status(), "info");
    } catch (error) {
      // Consumption is durable revocation; a later cleanup failure cannot resurrect it.
      if (revoked(group)) throw error;
      group.phase = "incomplete"; group.error = message(error);
      try { this.persist(); } catch { /* retain per-session progress */ }
      throw error;
    } finally { this.busy = false; }
  }

  async discard(ctx: ExtensionCommandContext): Promise<void> {
    if (this.busy) throw new Error("Cannot discard during a suspension operation.");
    if (!this.group || this.group.phase === "consumed") {
      if (this.discoveryError) throw new Error(this.discoveryError);
      return;
    }
    // Explicit revocation survives navigation behind/off the saved anchor.
    this.validate(ctx, false);
    this.claim!.acquire();
    const phase = this.group.phase, pending = this.group.discardCleanupPending;
    this.group.phase = "discarded";
    this.group.discardCleanupPending = true;
    try { this.persist(); } catch (error) {
      if (error instanceof GroupPublicationUncertainError) this.group.error = `Discard cleanup incomplete: ${message(error)}`;
      else { this.group.phase = phase; this.group.discardCleanupPending = pending; }
      throw error;
    }
    this.discoveryError = undefined;
    this.busy = true;
    try {
      this.replay.discardSavedInputs(); // Revocation clears only extension ownership, never admitted core work.
      await this.manager.discardSuspension(this.group.parentId);
      this.pi.resume();
      this.group.discardCleanupPending = false;
      delete this.group.error;
      this.persist();
    } catch (error) {
      this.group.discardCleanupPending = true;
      this.group.error = `Discard cleanup incomplete: ${message(error)}`;
      try { this.persist(); } catch { /* revocation is already published; never erase its payload */ }
      throw error;
    } finally { this.busy = false; this.claim!.release(); }
  }

  /** Called from Manager's void callback. Never await admission in a boundary handler. */
  completion(event: AgentCompletionEvent): boolean {
    if (this.isPaused(event.parentSessionId)) {
      if (this.group && !this.discoveryError) {
        this.updateCompletions();
        try { this.persist(); } catch (error) {
          this.group.error = `Completion state not persisted: ${message(error)}`;
          if (this.group.phase === "saved") this.group.phase = "incomplete";
        }
      }
      return true;
    }
    if (!this.commandContext || typeof this.commandContext.submitInput !== "function"
      || this.commandContext.sessionManager.getSessionId() !== event.parentSessionId) {
      this.legacyDelivery.add(event.id);
      return false;
    }
    this.scheduleCompletions(this.commandContext);
    return true;
  }

  private scheduleCompletions(ctx: ExtensionCommandContext): void {
    this.delivery = this.delivery.then(() => this.flushCompletions(ctx)).catch(error => {
      ctx.ui?.notify?.(`Subagent completion remains pending: ${message(error)}`, "error");
    });
  }

  private async flushCompletions(ctx: ExtensionCommandContext, releasing = false): Promise<void> {
    const id = ctx.sessionManager.getSessionId();
    if (this.isPaused(id) && !releasing) return;
    this.reconcileCompletions(ctx);
    const state = this.manager.getCompletionState(id);
    for (const event of state.mailbox) {
      // A prior void delivery may still be queued. Only history/handoff can discharge that uncertainty.
      if (state.delivered.includes(event.id) || this.legacyDelivery.has(event.id)) continue;
      const result = await ctx.submitInput({ kind: "prepared", message: this.completionMessage(event),
        options: { deliverAs: "steer", triggerTurn: true } });
      if (result.disposition === "started" || result.disposition === "queued") this.manager.markCompletionDelivered(event.id);
      else throw new Error(`Completion ${event.id} admission ${result.disposition}; not acknowledged.`);
      if (this.group?.parentId === id && !revoked(this.group)) { this.updateCompletions(); this.persist(); }
    }
  }

  shutdown(ctx?: any): void {
    try {
      if (ctx && this.group && !revoked(this.group) && !this.discoveryError) {
        try { this.validate(ctx); }
        catch (error) {
          this.group.phase = "incomplete"; this.group.error = message(error); this.persist();
        }
      }
    } finally { this.claim?.release(); }
  }
}
