import { expect, test } from "bun:test";
import * as fs from "node:fs";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionCommandContext, SessionHandoff } from "@earendil-works/pi-coding-agent";
import { parentScopeKey, type AgentManager } from "./core.js";
import { snapshotHandoff } from "./handoff.js";
import { GroupPublicationUncertainError, ParentScopeClaim, SuspensionCoordinator, writeGroup, type SuspensionGroup } from "./suspension.js";

function snapshot(file: string, id = "parent", active = false) {
  return snapshotHandoff({ requestId: "capture", sessionId: id, sessionFile: file, leafId: "anchor", wasActive: active,
    queueModes: { steering: "all", followUp: "all" },
    pending: { initial: [], steering: [], followUp: [], nextTurn: [], deferred: [] },
  } as SessionHandoff);
}

function fixture(writer?: typeof writeGroup) {
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT ?? tmpdir(), "suspension-"));
  const sessionFile = join(root, "parent.jsonl"); writeFileSync(sessionFile, "fixture");
  const groupFile = join(root, parentScopeKey("parent"), "group.json");
  const events: string[] = [];
  let branch: any[] = [{ id: "anchor" }];
  let shutdowns = 0;
  let starts = 0;
  const mailbox: any[] = [];
  const delivered = new Set<string>();
  const pi = { on() {}, requestPause() { events.push("pause"); }, resume() { events.push("resume"); }, getPauseState: () => "paused", sendMessage() {} } as unknown as ExtensionAPI;
  const ctx = {
    sessionManager: { getSessionId: () => "parent", getSessionFile: () => sessionFile, getBranch: () => branch },
    handoff: async () => { events.push("parent-capture"); return snapshot(sessionFile).handoff; },
    submitInput: async () => { starts++; return { disposition: "started" }; },
    shutdown() { shutdowns++; }, ui: { notify() {} }, isIdle: () => true,
  } as unknown as ExtensionCommandContext;
  const manager = {
    listAgents: (_prefix?: string, _parent?: string): any[] => [],
    getAgentInfo: (_name: string, _parent: string): any => { throw new Error("No child fixture info"); },
    beginPause() { events.push("begin"); }, endPause() { events.push("end"); },
    async pauseChildren() { events.push("children-pause"); },
    async drainSubmissions() { events.push("drain"); },
    async discardSuspension() { events.push("discard"); },
    async releaseUncapturedChildren() { events.push("release-uncaptured"); },
    async captureChildren() { events.push("children-capture"); return {}; },
    async prepareChildren(_parent: string, children: any) { events.push(`prepare:${Object.keys(children).join(",")}`); },
    async resumeChild(_parent: string, id: string) { events.push(`release:${id}`); return { complete: true }; },
    getCompletionState() { return { mailbox: [...mailbox], delivered: [...delivered], targets: [] }; },
    restoreCompletionState(_parent: string, state: any) { mailbox.splice(0, mailbox.length, ...state.mailbox); for (const id of state.delivered) delivered.add(id); },
    markCompletionDelivered(id: string) { delivered.add(id); },
  };
  const coordinator = new SuspensionCoordinator(pi, manager as unknown as AgentManager, e => ({ customType: "completion", content: e.id, details: { completionId: e.id } }), () => root, writer);
  coordinator.discover(ctx);
  return { root, sessionFile, groupFile, coordinator, ctx, manager, pi, events, mailbox, delivered,
    get shutdowns() { return shutdowns; }, get starts() { return starts; },
    branch(entries: any[]) { branch = entries; },
    read: () => JSON.parse(readFileSync(groupFile, "utf8")),
    close() { coordinator.shutdown(); rmSync(root, { recursive: true, force: true }); },
  };
}

test("exclusive claims fail closed even for implausible PIDs; ordinary release permits a new owner", () => {
  const root = mkdtempSync(join(tmpdir(), "scope-claim-"));
  const file = join(root, "claim");
  const a = new ParentScopeClaim(file), b = new ParentScopeClaim(file);
  try {
    a.acquire();
    const record = JSON.parse(readFileSync(file, "utf8")); record.pid = 999999999;
    writeFileSync(file, JSON.stringify(record));
    expect(() => b.acquire()).toThrow("manually remove");
    a.release(); b.acquire(); b.release();
    expect(existsSync(file)).toBe(false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("capture callback persists equal child inputs before close; a later failure stays not saved and retry keeps captures", async () => {
  const f = fixture();
  const child = snapshot(f.sessionFile, "A", true);
  child.handoff.pending.deferred.push({ kind: "raw", text: "equal" }, { kind: "raw", text: "equal" });
  const saved = snapshotHandoff(child.handoff);
  let fail = true;
  f.manager.captureChildren = async (_id?: any, _generation?: any, callback?: any) => {
    f.events.push("children-capture");
    callback("A", saved);
    expect(f.read().children.A.handoff.pending.deferred).toHaveLength(2);
    f.events.push("close:A");
    if (fail) throw new Error("B close not verified");
    return { A: saved };
  };
  try {
    await expect(f.coordinator.pause(f.ctx, true)).rejects.toThrow("B close");
    expect(f.events.indexOf("drain")).toBeLessThan(f.events.indexOf("children-capture"));
    expect(f.read().phase).toBe("incomplete");
    expect(f.coordinator.status()).toContain("pending 2");
    expect(f.shutdowns).toBe(0);
    fail = false;
    await f.coordinator.pause(f.ctx, true);
    expect(f.read().phase).toBe("saved");
    expect(f.events.filter(event => event === "parent-capture")).toHaveLength(1);
    expect(f.shutdowns).toBe(1);
  } finally { f.close(); }
});

test("live status identifies blocked submission drain and drops that activity after failure", async () => {
  const f = fixture();
  const entered = Promise.withResolvers<void>();
  const release = Promise.withResolvers<void>();
  f.manager.drainSubmissions = async () => {
    entered.resolve();
    await release.promise;
    throw new Error("submission failed");
  };
  const pause = f.coordinator.pause(f.ctx);
  try {
    await entered.promise;
    expect(f.coordinator.status()).toContain("draining parent subagent submissions");
    release.resolve();
    await expect(pause).rejects.toThrow("submission failed");
    expect(f.coordinator.status()).toContain("incomplete");
    expect(f.coordinator.status()).not.toContain("draining parent");
  } finally { release.resolve(); await pause.catch(() => {}); f.close(); }
});

test("early child pause failure stays incomplete without capturing or closing the parent and can be retried", async () => {
  const f = fixture();
  f.manager.pauseChildren = async () => { throw new Error("child pause refused"); };
  try {
    await expect(f.coordinator.pause(f.ctx, true)).rejects.toThrow("child pause refused");
    expect(f.read().phase).toBe("incomplete");
    expect(f.events).not.toContain("parent-capture");
    expect(f.events).not.toContain("children-capture");
    expect(f.shutdowns).toBe(0);
    f.manager.pauseChildren = async () => { f.events.push("children-pause"); };
    await f.coordinator.pause(f.ctx);
    expect(f.read().phase).toBe("saved");
  } finally { f.close(); }
});

test("partial child release persists A; retry only prepares/releases B; idle parent gets no synthetic input", async () => {
  const f = fixture();
  f.manager.captureChildren = async (_id?: any, _generation?: any, callback?: any) => {
    const children = { A: snapshot(f.sessionFile, "A", true), B: snapshot(f.sessionFile, "B", true) };
    for (const [id, saved] of Object.entries(children)) callback(id, saved);
    return children;
  };
  let fail = true;
  f.manager.resumeChild = async (_parent: string, id: string, saved?: any, update?: any) => {
    f.events.push(`release:${id}`);
    if (id === "B" && fail) return { complete: false, error: "B refused" };
    saved.marker = "started"; update(saved);
    expect(f.read().children[id].marker).toBe("started");
    return { complete: true };
  };
  try {
    await f.coordinator.pause(f.ctx);
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("B refused");
    expect(f.read().resumed).toEqual(["A"]);
    fail = false;
    await f.coordinator.unpause(f.ctx);
    expect(f.events.filter(event => event === "release:A")).toHaveLength(1);
    expect(f.events).toContain("prepare:B");
    expect(f.starts).toBe(0);
    expect(f.read().phase).toBe("consumed");
    expect(existsSync(join(f.root, parentScopeKey("parent"), ".group.claim"))).toBe(false);
  } finally { f.close(); }
});

test("startup fences synchronously; anchor descendants are valid; explicit discard survives branch navigation", async () => {
  const f = fixture();
  let reopened: SuspensionCoordinator | undefined;
  try {
    await f.coordinator.pause(f.ctx);
    f.coordinator.shutdown();
    f.branch([{ id: "anchor" }, { id: "shutdown-record" }]);
    reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    const before = f.events.length;
    reopened.discover(f.ctx);
    expect(f.events[before]).toBe("pause");
    expect(reopened.status()).toContain("saved");
    reopened.shutdown();
    f.branch([{ id: "other-branch" }]);
    reopened.discover(f.ctx);
    expect(reopened.status()).toContain("anchor");
    await reopened.discard(f.ctx);
    expect(f.read().phase).toBe("discarded");
    f.branch([{ id: "anchor" }]);
    reopened.discover(f.ctx);
    expect(reopened.isPaused("parent")).toBe(false);
  } finally { reopened?.shutdown(); f.close(); }
});

test("completion ID is acknowledged only from branch/exported prepared ownership, not a void callback", async () => {
  const f = fixture();
  const event = { id: "completion-1", parentSessionId: "parent", agentName: "A", status: "completed", createdAt: 1 };
  f.mailbox.push(event);
  f.ctx.handoff = async () => {
    const saved = snapshot(f.sessionFile);
    saved.handoff.pending.steering.push({ role: "custom", customType: "completion", content: "A done", display: true, details: { completionId: event.id }, timestamp: 1 });
    return saved.handoff;
  };
  try {
    expect(f.coordinator.completion(event as any)).toBe(false);
    expect(f.delivered.size).toBe(0);
    await f.coordinator.pause(f.ctx);
    expect(f.delivered.has(event.id)).toBe(true);
    expect(f.read().completions.delivered).toEqual([event.id]);
  } finally { f.close(); }
});

test("failed serialization cannot erase a previously published manifest", async () => {
  const f = fixture();
  try {
    await f.coordinator.pause(f.ctx);
    const before = readFileSync(f.groupFile, "utf8");
    const broken = f.read(); broken.children.bad = { payload: 1n };
    expect(() => writeGroup(f.groupFile, broken)).toThrow();
    expect(readFileSync(f.groupFile, "utf8")).toBe(before);
  } finally { f.close(); }
});

for (const marker of ["started", "unknown"] as const) {
  test(`reopened ${marker} admission blocks every release, including an otherwise pending child`, async () => {
    const f = fixture();
    let reopened: SuspensionCoordinator | undefined;
    try {
      await f.coordinator.pause(f.ctx);
      f.coordinator.shutdown();
      const group = f.read();
      group.children.A = snapshot(f.sessionFile, "A", true);
      group.children.B = snapshot(f.sessionFile, "B", true);
      group.children.B.marker = marker;
      writeGroup(f.groupFile, group);
      reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
      reopened.discover(f.ctx);
      const before = f.events.length;
      await expect(reopened.unpause(f.ctx)).rejects.toThrow("unresolved prior admission");
      expect(f.events.slice(before).filter(event => event.startsWith("prepare:") || event.startsWith("release:"))).toEqual([]);
      expect(f.read().phase).toBe("incomplete");
    } finally { reopened?.shutdown(); f.close(); }
  });
}

test("missing parent capture after process death cannot masquerade as an idle completed parent", async () => {
  const f = fixture();
  let reopened: SuspensionCoordinator | undefined;
  try {
    await f.coordinator.pause(f.ctx);
    f.coordinator.shutdown();
    const group = f.read(); delete group.parent; group.phase = "incomplete";
    writeGroup(f.groupFile, group);
    reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    reopened.discover(f.ctx);
    await expect(reopened.unpause(f.ctx)).rejects.toThrow("missing after restart");
    await expect(reopened.pause(f.ctx)).rejects.toThrow("missing after restart");
    expect(f.starts).toBe(0);
    expect(f.read().phase).toBe("incomplete");
  } finally { reopened?.shutdown(); f.close(); }
});

test("a copied transcript cannot acquire the original parent's restart or discard authority", async () => {
  const f = fixture();
  let copy: SuspensionCoordinator | undefined;
  try {
    await f.coordinator.pause(f.ctx); f.coordinator.shutdown();
    const copiedFile = join(f.root, "copied.jsonl"); writeFileSync(copiedFile, readFileSync(f.sessionFile));
    const ctx = { ...f.ctx, sessionManager: { ...f.ctx.sessionManager, getSessionFile: () => copiedFile } } as ExtensionCommandContext;
    copy = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    copy.discover(ctx);
    expect(copy.status()).toContain("canonical path mismatch");
    await expect(copy.discard(ctx)).rejects.toThrow("canonical path mismatch");
    expect(f.read().phase).toBe("saved");
    expect(existsSync(join(f.root, parentScopeKey("parent"), ".group.claim"))).toBe(false);
  } finally { copy?.shutdown(); f.close(); }
});

test("buffered completion is admitted with its ID before consumption and remains pending on rejected admission", async () => {
  const f = fixture();
  f.mailbox.push({ id: "mail", parentSessionId: "parent", agentName: "A", status: "completed", createdAt: 1 });
  let reject = true;
  const submitted: any[] = [];
  f.ctx.submitInput = async input => {
    submitted.push(input);
    return reject ? { disposition: "rejected", error: "not admitted" } : { disposition: "queued" };
  };
  try {
    await f.coordinator.pause(f.ctx);
    expect(f.read().completions.delivered).toEqual([]);
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("not acknowledged");
    expect(f.read().phase).toBe("incomplete");
    expect(f.read().completions.delivered).toEqual([]);
    reject = false;
    await f.coordinator.unpause(f.ctx);
    expect(submitted[0].message.details.completionId).toBe("mail");
    expect(f.read().phase).toBe("consumed");
    expect(f.read().completions.delivered).toEqual(["mail"]);
  } finally { f.close(); }
});

test("read-only peek labels suspended work instead of a completed/done child", async () => {
  const { SubagentPeekOverlay } = await import("./peek.js");
  const f = fixture();
  const overlay = new SubagentPeekOverlay({ terminal: { rows: 30 }, requestRender() {} } as any,
    { fg: (_color: string, text: string) => text } as any,
    { id: "00000000-0000-4000-8000-000000000001", taskName: "held", sessionFile: f.sessionFile, cwd: f.root,
      modelId: "faux", provider: "faux", status: "suspended" } as any, () => {});
  try {
    const header = overlay.render(80)[0];
    expect(header).toContain("suspended");
    expect(header).not.toContain("done");
  } finally { overlay.dispose(); f.close(); }
});

test("a new pause after partial release recaptures running A but retains the fenced parent and unadmitted B", async () => {
  const f = fixture();
  const captures = new Map<string, ReturnType<typeof snapshot>>();
  const generations: string[] = [];
  const b = snapshot(f.sessionFile, "B", true);
  f.manager.captureChildren = async (_id?: any, generation?: any, callback?: any) => {
    generations.push(generation);
    if (!captures.has(generation)) {
      const a = snapshot(f.sessionFile, "A", true);
      a.handoff.pending.deferred.push({ kind: "raw", text: `A-work-${captures.size + 1}` });
      captures.set(generation, snapshotHandoff(a.handoff));
    }
    const children = { A: captures.get(generation)!, B: b };
    for (const [id, saved] of Object.entries(children)) callback(id, saved);
    return children;
  };
  f.manager.resumeChild = async (_parent: string, id: string, saved?: any, update?: any) => {
    if (id === "B") return { complete: false, error: "B not admitted" };
    saved.marker = "started"; saved.items.forEach((item: any) => { item.status = "queued"; }); update(saved);
    return { complete: true };
  };
  try {
    await f.coordinator.pause(f.ctx);
    const parent = f.read().parent;
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("B not admitted");
    await f.coordinator.pause(f.ctx);
    const group = f.read();
    expect(group.phase).toBe("saved");
    expect(group.parent).toEqual(parent);
    expect(f.events.filter(event => event === "parent-capture")).toHaveLength(1);
    expect(group.children.A.handoff.pending.deferred[0].text).toBe("A-work-2");
    expect(group.children.B).toEqual(b);
    expect(group.resumed).toEqual([]);
    expect(generations[1]).not.toBe(generations[0]);
    expect(group.generation).toBe(generations[0]);
    expect(group.captureGeneration).toBe(generations[1]);
  } finally { f.close(); }
});

test("explicit discard publishes revocation before Manager cleanup and preserves it when cleanup fails", async () => {
  const f = fixture();
  let fail = true;
  f.manager.discardSuspension = async () => {
    expect(f.read().phase).toBe("discarded");
    expect(f.read().discardCleanupPending).toBe(true);
    if (fail) throw new Error("held child did not close");
  };
  try {
    await f.coordinator.pause(f.ctx);
    await expect(f.coordinator.discard(f.ctx)).rejects.toThrow("held child");
    expect(f.read().phase).toBe("discarded");
    expect(f.read().parent).toBeDefined();
    const failedGeneration = f.read().generation, before = readFileSync(f.groupFile, "utf8"), events = [...f.events];
    await expect(f.coordinator.pause(f.ctx)).rejects.toThrow("retry /pause --discard");
    expect(f.events).toEqual(events);
    expect(readFileSync(f.groupFile, "utf8")).toBe(before);
    f.coordinator.discover(f.ctx);
    expect(f.coordinator.status()).toContain("Discard cleanup incomplete");
    expect(f.coordinator.isPaused("parent")).toBe(false);
    await expect(f.coordinator.pause(f.ctx)).rejects.toThrow("retry /pause --discard");
    // A crash after revocation but before cleanup/error publication has the same durable guard.
    const interrupted = f.read(); delete interrupted.error; writeGroup(f.groupFile, interrupted);
    f.coordinator.discover(f.ctx);
    expect(f.coordinator.status()).toContain("discard cleanup pending");
    await expect(f.coordinator.pause(f.ctx)).rejects.toThrow("retry /pause --discard");
    fail = false;
    await f.coordinator.discard(f.ctx);
    expect(f.read().phase).toBe("discarded");
    expect(f.read().error).toBeUndefined();
    expect(f.read().discardCleanupPending).toBe(false);
    await f.coordinator.pause(f.ctx);
    expect(f.read().phase).toBe("saved");
    expect(f.read().generation).not.toBe(failedGeneration);
  } finally { f.close(); }
});

for (const status of ["interrupted", "completed"] as const) {
  test(`reopened partial inventory treats missing ${status} child as ${status === "completed" ? "genuinely terminal" : "unresolved"}`, async () => {
    const f = fixture();
    let reopened: SuspensionCoordinator | undefined;
    try {
      await f.coordinator.pause(f.ctx); f.coordinator.shutdown();
      const group = f.read(); group.phase = "incomplete"; group.requiredChildren = ["missing"];
      group.children.A = snapshot(f.sessionFile, "A", true);
      writeGroup(f.groupFile, group);
      f.manager.listAgents = () => [{ agent_name: "lost", agent_status: status }];
      f.manager.getAgentInfo = () => ({ id: "missing", status });
      reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
      reopened.discover(f.ctx);
      if (status === "completed") {
        await reopened.unpause(f.ctx);
        expect(f.read().phase).toBe("consumed");
      } else {
        const before = f.events.length;
        await expect(reopened.unpause(f.ctx)).rejects.toThrow("no captured ownership");
        expect(f.events.slice(before).filter(event => event.startsWith("release:"))).toEqual([]);
        expect(f.read().children.A).toBeDefined();
      }
    } finally { reopened?.shutdown(); f.close(); }
  });
}

test("off-anchor history before exit prevents shutdown; shutdown-time validation downgrades saved status", async () => {
  const f = fixture();
  try {
    await f.coordinator.pause(f.ctx);
    f.branch([{ id: "not-the-anchor" }]);
    f.coordinator.shutdown(f.ctx);
    expect(f.read().phase).toBe("incomplete");
    expect(f.coordinator.status()).toContain("anchor");
    await expect(f.coordinator.pause(f.ctx, true)).rejects.toThrow("anchor");
    expect(f.shutdowns).toBe(0);
  } finally { f.close(); }
});

test("captured legacy command contexts without submitInput retain automatic void delivery", () => {
  const f = fixture();
  try {
    f.coordinator.setCommandContext({ ...f.ctx, submitInput: undefined } as any);
    expect(f.coordinator.completion({ id: "legacy", parentSessionId: "parent", agentName: "A", status: "completed", createdAt: 1 })).toBe(false);
    expect(f.delivered.size).toBe(0);
  } finally { f.close(); }
});

test("known same-process started replay retries unresolved raw input without requiring another marker", async () => {
  const f = fixture();
  const a = snapshot(f.sessionFile, "A", true);
  a.handoff.pending.deferred.push({ kind: "raw", text: "retry raw" });
  const saved = snapshotHandoff(a.handoff);
  f.manager.captureChildren = async (_id?: any, _generation?: any, callback?: any) => { callback("A", saved); return { A: saved }; };
  let restored: SuspensionCoordinator | undefined;
  let releases = 0;
  f.manager.resumeChild = async (_parent: string, _id: string, progress?: any, update?: any) => {
    releases++;
    if (releases === 1) {
      progress.marker = "started"; progress.items[0].status = "rejected"; update(progress);
      return { complete: false, error: "raw input rejected" };
    }
    expect(progress.marker).toBe("started");
    expect(progress.items[0].status).toBe("rejected");
    progress.items[0].status = "handled"; update(progress);
    return { complete: true };
  };
  try {
    await f.coordinator.pause(f.ctx);
    f.coordinator.shutdown();
    restored = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    restored.discover(f.ctx);
    await expect(restored.unpause(f.ctx)).rejects.toThrow("raw input rejected");
    await restored.unpause(f.ctx);
    expect(releases).toBe(2);
    expect(f.starts).toBe(0);
    expect(f.read().phase).toBe("consumed");
  } finally { restored?.shutdown(); f.close(); }
});

test("ordinary uncaptured children release before consumption; unknown stopped ownership prevents it live and after restart", async () => {
  const f = fixture();
  let reopened: SuspensionCoordinator | undefined;
  f.manager.listAgents = () => ["A", "B"].map(id => ({ agent_name: id, agent_status: "suspended" }));
  f.manager.getAgentInfo = id => ({ id, status: "suspended" });
  f.manager.captureChildren = async (_id?: any, _generation?: any, callback?: any) => {
    callback("A", snapshot(f.sessionFile, "A", true));
    throw new Error("B stopped during handoff before its acknowledgment");
  };
  f.manager.releaseUncapturedChildren = async () => {
    expect(f.read().phase).toBe("restoring");
    throw new Error("B may already be handed off");
  };
  try {
    await expect(f.coordinator.pause(f.ctx)).rejects.toThrow("B stopped");
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("already be handed off");
    expect(f.read().phase).toBe("incomplete");
    expect(f.read().requiredChildren).toEqual(["A", "B"]);
    expect(f.read().children.A).toBeDefined();
    f.coordinator.shutdown();
    reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    reopened.discover(f.ctx);
    const before = f.events.length;
    await expect(reopened.unpause(f.ctx)).rejects.toThrow("B has no captured ownership");
    expect(f.events.slice(before).filter(event => event.startsWith("release:"))).toEqual([]);
    expect(f.read().children.A).toBeDefined();
  } finally { reopened?.shutdown(); f.close(); }
});

test("final Saved rename with failed directory fsync and failed compensation retains the complete recoverable publication and reports uncertainty", async () => {
  let afterSavedRename = false, rejectFurtherWrites = false;
  let durableStage: any;
  const writer: typeof writeGroup = (file, group) => {
    const result = writeGroup(file, group, { ...fs,
      renameSync(from, to) { fs.renameSync(from, to); if (group.phase === "saved") afterSavedRename = true; },
      fsyncSync(fd) {
        if (rejectFurtherWrites) throw new Error("injected subsequent persistence failure");
        if (afterSavedRename && fs.fstatSync(fd).isDirectory()) {
          rejectFurtherWrites = true; throw new Error("injected post-rename directory fsync failure");
        }
        fs.fsyncSync(fd);
      },
    });
    durableStage = structuredClone(group);
    return result;
  };
  const f = fixture(writer);
  const child = snapshot(f.sessionFile, "A", true);
  child.handoff.pending.deferred.push({ kind: "raw", text: "equal" }, { kind: "raw", text: "equal" });
  child.handoff.pending.steering.push({ role: "user", content: [{ type: "image", data: "AA==", mimeType: "image/png" }], timestamp: 1 });
  const captured = snapshotHandoff(child.handoff);
  f.manager.captureChildren = async (_parent?: any, _generation?: any, callback?: any) => { callback("A", captured); return { A: captured }; };
  let reopened: SuspensionCoordinator | undefined;
  try {
    await expect(f.coordinator.pause(f.ctx, true)).rejects.toBeInstanceOf(GroupPublicationUncertainError);
    expect(f.shutdowns).toBe(0);
    expect(f.coordinator.status()).toContain("incomplete");
    expect(f.coordinator.status()).toContain("Saved publication is not confirmed");
    const visible = f.read();
    expect(visible.phase).toBe("saved"); // Visibility is not claimed to have rolled back.
    expect(visible.parent).toEqual(durableStage.parent);
    expect(visible.children).toEqual(durableStage.children);
    expect(visible.children.A.handoff.pending.deferred).toHaveLength(2);
    expect(visible.children.A.handoff.pending.steering[0].content[0].data).toBe("AA==");
    expect(visible.completions).toEqual(durableStage.completions);
    expect(durableStage.phase).toBe("preparing");
    f.coordinator.shutdown();
    // Either surviving name owns the same durable payload; a real reopening can use the visible snapshot.
    reopened = new SuspensionCoordinator(f.pi, f.manager as unknown as AgentManager, () => ({}), () => f.root);
    reopened.discover(f.ctx);
    await reopened.unpause(f.ctx);
    expect(f.read().phase).toBe("consumed");
  } finally { reopened?.shutdown(); f.close(); }
});

test("unsupported directory fsync from the first write cannot reach Saved or request exit", async () => {
  const f = fixture((file, group) => writeGroup(file, group, { ...fs,
    fsyncSync(fd) { if (fs.fstatSync(fd).isDirectory()) throw new Error("directory fsync unsupported"); fs.fsyncSync(fd); },
  }));
  try {
    await expect(f.coordinator.pause(f.ctx, true)).rejects.toThrow("directory fsync unsupported");
    expect(f.read().phase).toBe("incomplete");
    expect(f.shutdowns).toBe(0);
    expect(f.events).not.toContain("parent-capture");
  } finally { f.close(); }
});

test("a failed recapture after A closes keeps its fresh attempt ID while B's admitted progress remains", async () => {
  const f = fixture();
  const generations: string[] = [];
  let attempt = 0, stoppedGeneration: string | undefined;
  f.manager.captureChildren = async (_parent?: any, generation?: any, callback?: any) => {
    generations.push(generation); attempt++;
    callback("A", snapshot(f.sessionFile, "A", true));
    if (attempt === 2) { stoppedGeneration = generation; throw new Error("B capture persistence failed"); }
    if (attempt === 3 && generation !== stoppedGeneration) throw new Error("fenced B received a different capture ID");
    const b = snapshot(f.sessionFile, "B", true); callback("B", b);
    return { A: snapshot(f.sessionFile, "A", true), B: b };
  };
  f.manager.resumeChild = async (_parent: string, _id: string, saved?: any, update?: any) => {
    saved.marker = "started"; update(saved); return { complete: true };
  };
  f.mailbox.push({ id: "mail", parentSessionId: "parent", agentName: "A", status: "completed", createdAt: 1 });
  f.ctx.submitInput = async () => ({ disposition: "rejected", error: "completion held" });
  try {
    await f.coordinator.pause(f.ctx);
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("not acknowledged");
    await expect(f.coordinator.pause(f.ctx)).rejects.toThrow("B capture persistence failed");
    expect(f.read().resumed).toEqual(["B"]);
    await f.coordinator.pause(f.ctx);
    expect(generations[1]).not.toBe(generations[0]);
    expect(generations[2]).toBe(generations[1]);
    expect(f.events.filter(event => event === "parent-capture")).toHaveLength(2);
    expect(f.read().phase).toBe("saved");
  } finally { f.close(); }
});

for (const [owner, method] of [["ctx", "handoff"], ["ctx", "submitInput"], ["pi", "requestPause"], ["pi", "resume"], ["pi", "getPauseState"]] as const) {
  test(`missing native ${owner}.${method} rejects pause and unpause before claims or admission changes`, async () => {
    const f = fixture();
    const target = owner === "ctx" ? f.ctx as any : f.pi as any;
    const original = target[method];
    const claim = join(f.root, parentScopeKey("parent"), ".group.claim");
    try {
      target[method] = undefined;
      await expect(f.coordinator.pause(f.ctx)).rejects.toThrow(`Unsupported Pi`);
      expect(f.events).toEqual([]);
      expect(existsSync(f.groupFile)).toBe(false);
      expect(existsSync(claim)).toBe(false);
      target[method] = original;
      await f.coordinator.pause(f.ctx);
      f.coordinator.shutdown();
      const before = readFileSync(f.groupFile, "utf8"), events = [...f.events];
      target[method] = undefined;
      await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow(`${owner}.${method}`);
      expect(f.events).toEqual(events);
      expect(readFileSync(f.groupFile, "utf8")).toBe(before);
      expect(existsSync(claim)).toBe(false);
    } finally { target[method] = original; f.close(); }
  });
}

test("preparation recapture mutations are persisted before any child release; a failed write prevents release", async () => {
  let rejectPreparedWrite = false;
  const f = fixture((file, group) => {
    if (rejectPreparedWrite && group.phase === "restoring") {
      rejectPreparedWrite = false;
      throw new Error("prepared capture persistence failed");
    }
    writeGroup(file, group);
  });
  const saved = snapshot(f.sessionFile, "A", true);
  f.manager.captureChildren = async (_parent?: any, _generation?: any, callback?: any) => { callback("A", saved); return { A: saved }; };
  let prepares = 0, releases = 0;
  f.manager.prepareChildren = async (_parent: string, children: any) => {
    prepares++;
    const changed = snapshot(f.sessionFile, "A", true);
    changed.handoff.requestId = "recaptured-preparation";
    changed.handoff.pending.deferred.push({ kind: "raw", text: "retained after disarm" });
    Object.assign(children.A, snapshotHandoff(changed.handoff));
    if (prepares === 1) rejectPreparedWrite = true;
  };
  f.manager.resumeChild = async (_parent: string, id: string, progress?: any) => {
    releases++;
    expect(f.read().children[id]).toEqual(progress);
    expect(f.read().children[id].handoff.pending.deferred[0].text).toBe("retained after disarm");
    return { complete: true };
  };
  try {
    await f.coordinator.pause(f.ctx);
    await expect(f.coordinator.unpause(f.ctx)).rejects.toThrow("prepared capture persistence failed");
    expect(releases).toBe(0);
    expect(f.read().phase).toBe("incomplete");
    expect(f.read().children.A.handoff.requestId).toBe("recaptured-preparation");
    await f.coordinator.unpause(f.ctx);
    expect(releases).toBe(1);
    expect(f.read().phase).toBe("consumed");
  } finally { f.close(); }
});

test("paused configured direct skill leaves input unhandled and never spawns before native rejection", async () => {
  // Isolate module doubles: Bun mock.module cannot safely be restored for the native suites below.
  // This subprocess deliberately has no changed-core aliases and uses only installed public SDK imports.
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT ?? tmpdir(), "paused-route-"));
  const script = `
    import { mock } from "bun:test";
    import assert from "node:assert/strict";
    import { EventEmitter } from "node:events";
    import { readFileSync, writeFileSync } from "node:fs";
    import { join } from "node:path";
    const root = ${JSON.stringify(root)};
    const sessionFile = join(root, "session.jsonl");
    const skillFile = join(root, "eligible.md");
    writeFileSync(sessionFile, "owned input-handler fixture");
    writeFileSync(skillFile, "eligible configured skill");
    let spawns = 0, paused = false;
    const state = () => ({ mailbox: [], delivered: [], targets: [] });
    const corePath = ${JSON.stringify(join(import.meta.dir, "core.ts"))};
    const originalCore = await import(corePath);
    mock.module(corePath, () => ({
      ...originalCore,
      AgentManager: class {
        beginPause() {} endPause() {} async ready() {} async shutdown() {}
        async pauseChildren() {} async drainSubmissions() {} async captureChildren() { return {}; }
        listAgents() { return []; } getCompletionState() { return state(); }
        async spawnAgent(request) { spawns++; return { task_name: request.task_name }; }
      },
      getRunsDir: () => join(root, "runs"), parentScopeKey: () => "parent-scope",
      loadSubagentConfig: () => ({ directSkillRoutes: { eligible: { agentType: "reviewer" } } }),
      getAgentDefinition: () => ({ name: "reviewer" }), getAgentDefinitionsDescription: () => "reviewer",
    }));
    mock.module(${JSON.stringify(join(import.meta.dir, "peek.ts"))}, () => ({ SubagentPeekOverlay: class {} }));
    const { default: extension } = await import(${JSON.stringify(join(import.meta.dir, "index.ts"))});
    const handlers = new Map(), commands = new Map();
    const pi = {
      events: new EventEmitter(),
      on(name, handler) { const list = handlers.get(name) ?? []; list.push(handler); handlers.set(name, list); },
      registerTool() {}, registerMessageRenderer() {}, registerShortcut() {},
      registerCommand(name, command) { commands.set(name, command); },
      requestPause() { paused = true; }, resume() { paused = false; }, getPauseState: () => paused ? "paused" : "unpaused",
      getThinkingLevel: () => "off", getActiveTools: () => [], sendMessage() {},
    };
    const ctx = {
      cwd: root, mode: "rpc", model: { provider: "fixture", id: "fixture" }, ui: { notify() {} },
      sessionManager: { getSessionId: () => "parent", getSessionFile: () => sessionFile, getBranch: () => [{ id: "anchor" }] },
      resolveSkillCommand: () => ({ skill: { name: "eligible", filePath: skillFile } }),
      handoff: async requestId => ({ requestId, sessionId: "parent", sessionFile, leafId: "anchor", wasActive: false,
        queueModes: { steering: "all", followUp: "all" }, pending: { initial: [], steering: [], followUp: [], nextTurn: [], deferred: [] } }),
      submitInput: async () => { throw new Error("input callback must not submit anything"); },
    };
    extension(pi);
    await commands.get("pause").handler("", ctx);
    assert.equal(JSON.parse(readFileSync(join(root, "runs/parent-scope/group.json"), "utf8")).phase, "saved");
    assert.equal(paused, true);
    const inputHandlers = handlers.get("input");
    assert.equal(inputHandlers.length, 1);
    const result = await inputHandlers[0]({ source: "interactive", text: "/skill:eligible concrete work" }, ctx);
    assert.equal(result, undefined, "a pre-effect pause guard must not consume the request");
    assert.equal(spawns, 0);
    for (const handler of handlers.get("session_shutdown") ?? []) await handler({}, ctx);
    console.log(JSON.stringify({ unhandled: result === undefined, spawns, pausedGeneration: true }));
  `;
  try {
    const child = Bun.spawn([process.execPath, "--no-install", "-e", script], {
      cwd: root, env: { PATH: process.env.PATH ?? "", HOME: root, PI_CODING_AGENT_DIR: join(root, "agent"), PI_OFFLINE: "1" },
      stdout: "pipe", stderr: "pipe",
    });
    const [exit, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
    expect({ exit, stderr }).toEqual({ exit: 0, stderr: "" });
    expect(JSON.parse(stdout.trim())).toEqual({ unhandled: true, spawns: 0, pausedGeneration: true });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("real core: pending-only parent saves, reopens held, and idle unpause creates no provider input", async () => {
  const { fauxProvider, fauxAssistantMessage } = await import("@earendil-works/pi-ai/providers/faux");
  const { ModelRuntime, SessionManager, SettingsManager, createAgentSessionServices, createAgentSessionFromServices } = await import("@earendil-works/pi-coding-agent");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "parent-native-"));
  const agentDir = join(root, "agent"); mkdirSync(agentDir);
  const faux = fauxProvider(); let calls = 0;
  const respond = () => { calls++; faux.appendResponses([respond]); return fauxAssistantMessage("done"); };
  faux.setResponses([respond]);
  const runtime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  runtime.registerNativeProvider(faux.provider);
  const f = fixture(); // Child lifecycle is a deliberately empty group; parent is the real SDK.
  let coordinator!: SuspensionCoordinator;
  let context!: ExtensionCommandContext;
  const extension = (pi: ExtensionAPI) => {
    coordinator = new SuspensionCoordinator(pi, f.manager as unknown as AgentManager, () => ({}), () => root);
    pi.on("session_start", (_event, ctx) => coordinator.discover(ctx));
    pi.registerCommand("context", { allowedWhilePaused: true, handler: async (_args, ctx) => { context = ctx; } });
  };
  const makeServices = () => createAgentSessionServices({ cwd: root, agentDir, modelRuntime: runtime,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
    resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension], systemPrompt: "Offline parent coordinator fixture." },
  });
  let session: any;
  try {
    const services = await makeServices();
    const manager = SessionManager.open(join(root, "parent.jsonl"));
    ({ session } = await createAgentSessionFromServices({ services, sessionManager: manager, model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" }));
    await session.bindExtensions({ mode: "rpc" });
    await session.prompt("/context");
    expect(existsSync(manager.getSessionFile()!)).toBe(false);
    await coordinator.pause(context);
    expect(existsSync(manager.getSessionFile()!)).toBe(true);
    expect(coordinator.status()).toContain("saved");
    coordinator.shutdown();
    session.dispose();
    // Recreate the complete extension/session runtime over the same durable transcript.
    ({ session } = await createAgentSessionFromServices({ services: await makeServices(), sessionManager: SessionManager.open(manager.getSessionFile()!), model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" }));
    await session.bindExtensions({ mode: "rpc" });
    expect(session.sessionManager.getSessionId()).toBe(manager.getSessionId());
    expect(coordinator.status()).toContain("saved");
    expect(session.pauseState).toBe("paused");
    await session.prompt("/context");
    await coordinator.unpause(context);
    expect(coordinator.status()).toContain("consumed");
    expect(calls).toBe(0);
  } finally { coordinator?.shutdown(); session?.dispose(); f.close(); rmSync(root, { recursive: true, force: true }); }
}, 15000);

sourceTest("production index controls save/reopen/unpause a real parent and release the exclusive claim on ordinary shutdown", async () => {
  const { default: extension } = await import("./index.js");
  const { fauxProvider, fauxAssistantMessage } = await import("@earendil-works/pi-ai/providers/faux");
  const { ModelRuntime, SessionManager, SettingsManager, createAgentSessionServices, createAgentSessionFromServices, createAgentSessionRuntime } = await import("@earendil-works/pi-coding-agent");
  const { getRunsDir } = await import("./core.js");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "index-native-"));
  const agentDir = join(root, "agent"); mkdirSync(agentDir);
  const faux = fauxProvider(); let calls = 0;
  faux.setResponses([() => { calls++; return fauxAssistantMessage("done"); }]);
  const models = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  models.registerNativeProvider(faux.provider);
  const factory = async ({ sessionManager, sessionStartEvent }: any) => {
    const services = await createAgentSessionServices({ cwd: root, agentDir, modelRuntime: models,
      settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
      resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension], systemPrompt: "Offline production-index fixture." },
    });
    const result = await createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" });
    expect(result.extensionsResult.errors).toEqual([]);
    return { ...result, services, diagnostics: services.diagnostics };
  };
  let runtime: any;
  let scope: string | undefined;
  try {
    runtime = await createAgentSessionRuntime(factory, { cwd: root, agentDir, sessionManager: SessionManager.open(join(root, "session.jsonl")) });
    await runtime.session.bindExtensions({ mode: "rpc" });
    scope = join(getRunsDir(), parentScopeKey(runtime.session.sessionId));
    const file = join(scope, "group.json"), claim = join(scope, ".group.claim");
    await runtime.session.prompt("/pause");
    expect(JSON.parse(readFileSync(file, "utf8")).phase).toBe("saved");
    expect(existsSync(claim)).toBe(true);
    const sessionFile = runtime.session.sessionFile;
    await runtime.dispose(); runtime = undefined;
    expect(existsSync(claim)).toBe(false);
    runtime = await createAgentSessionRuntime(factory, { cwd: root, agentDir, sessionManager: SessionManager.open(sessionFile) });
    await runtime.session.bindExtensions({ mode: "rpc" });
    expect(runtime.session.pauseState).toBe("paused");
    await runtime.session.prompt("/pause --status");
    await runtime.session.prompt("/unpause");
    expect(JSON.parse(readFileSync(file, "utf8")).phase).toBe("consumed");
    expect(existsSync(claim)).toBe(false);
    expect(calls).toBe(0);
  } finally { await runtime?.dispose(); if (scope) rmSync(scope, { recursive: true, force: true }); rmSync(root, { recursive: true, force: true }); }
}, 15000);

sourceTest("native discard then fresh pause never resurrects extension-owned deferred input and preserves core-owned asides", async () => {
  const { fauxProvider, fauxAssistantMessage } = await import("@earendil-works/pi-ai/providers/faux");
  const { ModelRuntime, SessionManager, SettingsManager, createAgentSessionServices, createAgentSessionFromServices } = await import("@earendil-works/pi-coding-agent");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "discard-native-"));
  const agentDir = join(root, "agent"); mkdirSync(agentDir);
  const faux = fauxProvider();
  const respond = () => { faux.appendResponses([respond]); return fauxAssistantMessage("done"); };
  faux.setResponses([respond]);
  const runtime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  runtime.registerNativeProvider(faux.provider);
  const f = fixture();
  let coordinator!: SuspensionCoordinator, context!: ExtensionCommandContext, published!: SuspensionGroup;
  let aborted = false;
  const rawInputs: string[] = [];
  const extension = (pi: ExtensionAPI) => {
    coordinator = new SuspensionCoordinator(pi, f.manager as unknown as AgentManager, () => ({}), () => join(root, "groups"), (file, group) => {
      published = group; writeGroup(file, group);
    });
    pi.on("session_start", (_event, ctx) => coordinator.discover(ctx));
    pi.on("input", (event, ctx) => {
      rawInputs.push(event.text);
      if (event.text === "abort-once" && !aborted) { aborted = true; ctx.abort(); }
    });
    pi.registerCommand("context", { allowedWhilePaused: true, handler: async (_args, ctx) => { context = ctx; } });
  };
  const services = await createAgentSessionServices({ cwd: root, agentDir, modelRuntime: runtime,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
    resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension], systemPrompt: "Offline discard ownership regression." },
  });
  let session: any;
  try {
    const manager = SessionManager.open(join(root, "session.jsonl"));
    ({ session } = await createAgentSessionFromServices({ services, sessionManager: manager, model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" }));
    await session.bindExtensions({ mode: "rpc" });
    await session.prompt("/context");
    await session.prompt("seed");
    await coordinator.pause(context);
    const originalGeneration = published.generation;
    // Seed distinct extension-owned occurrences at the real SavedSession replay boundary.
    const handoff = structuredClone(published.parent!.handoff);
    handoff.wasActive = true;
    handoff.pending.deferred.push({ kind: "raw", text: "abort-once" }, { kind: "raw", text: "explicitly-discard-this" });
    published.parent = snapshotHandoff(handoff);
    await expect(coordinator.unpause(context)).rejects.toThrow();
    expect(published.parent.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    await session.waitForIdle();
    const aside = await context.submitInput({ kind: "prepared", message: { customType: "core-survivor", content: "core-owned-survivor", display: true }, options: { deliverAs: "nextTurn" } });
    expect(aside.disposition).toBe("queued");
    await coordinator.discard(context);
    expect(published.phase).toBe("discarded");
    await coordinator.pause(context);
    expect(published.generation).not.toBe(originalGeneration);
    expect(JSON.stringify(published.parent!.handoff.pending)).not.toContain("explicitly-discard-this");
    expect(JSON.stringify(published.parent!.handoff.pending)).toContain("core-owned-survivor");
    await coordinator.unpause(context);
    await session.waitForIdle();
    expect(rawInputs).not.toContain("explicitly-discard-this");
    const survivors = manager.getBranch().filter(entry => entry.type === "custom_message" && entry.content === "core-owned-survivor");
    expect(survivors).toHaveLength(1);
  } finally { coordinator?.shutdown(); session?.dispose(); f.close(); rmSync(root, { recursive: true, force: true }); }
}, 15000);
