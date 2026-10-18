import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionCommandContext, SessionHandoff } from "@earendil-works/pi-coding-agent";
import {
  CONTROL_ENTRY, controlRecord, snapshotHandoff, assertSessionAuthority, isSavedSession, reconcileRecorded, hasUnresolvedInputs, pendingCount, SessionReplay, CONTINUATION_MESSAGE,
} from "./handoff.js";
import childHelper from "./child-helper.js";

function handoff(file = "/unused"): SessionHandoff {
  return {
    requestId: "request", sessionId: "session", sessionFile: file, leafId: "anchor", wasActive: true,
    queueModes: { steering: "all", followUp: "one-at-a-time" },
    pending: {
      initial: [{ role: "user", content: [{ type: "text", text: "equal" }], timestamp: 1 }],
      steering: [{ role: "user", content: [{ type: "text", text: "equal" }, { type: "image", data: "AA==", mimeType: "image/png" }], timestamp: 2 }],
      followUp: [], nextTurn: [], deferred: [{ kind: "raw", text: "equal" }, { kind: "raw", text: "equal" }],
    },
  };
}

test("canonical lane references retain equal occurrences and image bodies without second payload copies", () => {
  const source = handoff();
  const saved = snapshotHandoff(source);
  expect(saved.items.map(item => [item.lane, item.index])).toEqual([["initial", 0], ["steering", 0], ["deferred", 0], ["deferred", 1]]);
  expect(new Set(saved.items.map(item => item.id)).size).toBe(4);
  expect(saved.handoff.pending).toEqual(source.pending);
  source.pending.initial.length = 0;
  expect(saved.handoff.pending.initial).toHaveLength(1);
  expect(JSON.parse(JSON.stringify(saved))).toEqual(saved);
  expect(isSavedSession(JSON.parse(JSON.stringify(saved)))).toBe(true);
  const missing = structuredClone(saved);
  missing.items.pop();
  expect(isSavedSession(missing)).toBe(false);
  const duplicate = structuredClone(saved);
  duplicate.items[3].index = duplicate.items[2].index;
  expect(isSavedSession(duplicate)).toBe(false);
});

test("release projection distinguishes unresolved inputs from confirmed queued display counts", () => {
  const saved = snapshotHandoff(handoff());
  for (const status of ["queued", "started", "handled"] as const) {
    for (const item of saved.items) item.status = status;
    expect(hasUnresolvedInputs(saved)).toBe(false);
    if (status === "queued") expect(pendingCount(saved)).toBe(saved.items.length);
  }
  for (const status of ["pending", "rejected", "unknown"] as const) {
    for (const item of saved.items) item.status = "queued";
    saved.items[0].status = status;
    expect(hasUnresolvedInputs(saved)).toBe(true);
  }
});

test("control lookup selects latest matching custom record; malformed newer success does not revive old success", () => {
  const base = { version: 1, generation: "g", action: "capture", ok: true, sessionId: "s", snapshot: snapshotHandoff(handoff()) };
  const entry = (data: unknown) => ({ type: "custom", customType: CONTROL_ENTRY, data });
  expect(controlRecord([entry(base), entry({ ...base, generation: "other" })], "g", "capture")).toEqual(base);
  expect(controlRecord([entry(base), entry({ ...base, version: 2 })], "g", "capture")).toBeUndefined();
  expect(controlRecord([entry(base), entry({ ...base, ok: "true" })], "g", "capture")).toBeUndefined();
  expect(controlRecord([entry(base), entry({ ...base, snapshot: {} })], "g", "capture")).toBeUndefined();
  expect(controlRecord([{ type: "custom_message", customType: CONTROL_ENTRY, data: base }], "g", "capture")).toBeUndefined();
});

test("authority accepts canonical aliases and appended descendants, rejects copies/id changes/off-anchor branches", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-replay-authority-"));
  try {
    const file = join(root, "session.jsonl"), alias = join(root, "alias.jsonl"), copy = join(root, "copy.jsonl");
    writeFileSync(file, ""); writeFileSync(copy, ""); symlinkSync(file, alias);
    const saved = snapshotHandoff(handoff(alias));
    const manager = {
      getSessionId: () => "session", getSessionFile: () => file,
      getBranch: () => [{ id: "anchor" }, { id: "shutdown" }],
    } as unknown as ExtensionCommandContext["sessionManager"];
    expect(() => assertSessionAuthority(saved, manager)).not.toThrow();
    expect(() => assertSessionAuthority(saved, { ...manager, getSessionFile: () => copy })).toThrow("canonical");
    expect(() => assertSessionAuthority(saved, { ...manager, getSessionId: () => "fork" })).toThrow("identity");
    expect(() => assertSessionAuthority(saved, { ...manager, getBranch: () => [] })).toThrow("anchor");
  } finally { rmSync(root, { recursive: true, force: true }); }
});

// These integration cases use the changed public SDK, not a fake admission implementation.
const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
async function nativeFixture(options: { handleMarker?: boolean; hold?: boolean; rejectDeferred?: boolean; failCaptureRecord?: boolean; childControl?: boolean; handleMarkerPrepared?: boolean; abortDeferredOnce?: boolean; beforeInstaller?: (pi: ExtensionAPI) => void; onMarkerInput?: () => void } = {}) {
  const { fauxProvider, fauxAssistantMessage } = await import("@earendil-works/pi-ai/providers/faux");
  const { ModelRuntime, SessionManager, SettingsManager, createAgentSessionServices, createAgentSessionFromServices } = await import("@earendil-works/pi-coding-agent");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "replay-"));
  const agentDir = join(root, "agent"); mkdirSync(agentDir);
  const faux = fauxProvider();
  const contexts: unknown[] = [];
  const respond = (context: unknown) => { contexts.push(context); faux.appendResponses([respond]); return fauxAssistantMessage("done"); };
  faux.setResponses([respond]);
  const modelRuntime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  modelRuntime.registerNativeProvider(faux.provider);
  let commandCtx: ExtensionCommandContext | undefined;
  let replay!: SessionReplay;
  let api!: ExtensionAPI;
  let rawPreflight = 0;
  const rawInputs: string[] = [];
  let abortedDeferred = false;
  const extension = (pi: ExtensionAPI) => {
    api = pi;
    options.beforeInstaller?.(pi);
    replay = new SessionReplay(pi);
    pi.on("input", (event, ctx) => {
      rawPreflight++;
      rawInputs.push(event.text);
      if (event.text === CONTINUATION_MESSAGE) options.onMarkerInput?.();
      if (options.abortDeferredOnce && !abortedDeferred && event.text === "abort-once") {
        abortedDeferred = true;
        ctx.abort();
      }
      if (options.handleMarkerPrepared && event.text === CONTINUATION_MESSAGE) {
        pi.sendMessage({ customType: "alternate-turn", content: "not the marker", display: true }, { triggerTurn: true });
        return { action: "handled" };
      }
      if (options.rejectDeferred && event.text === "bad-deferred") throw new Error("Handler failure is not a retry instruction");
      if (options.handleMarker && event.text === CONTINUATION_MESSAGE) return { action: "handled" };
      return { action: "continue" };
    });
    pi.registerCommand("fixture-context", { allowedWhilePaused: true, handler: async (_args, ctx) => { commandCtx = ctx; } });
    if (options.hold) pi.on("session_start", () => pi.requestPause());
    if (options.failCaptureRecord || options.childControl) {
      let failed = false;
      childHelper({ ...pi, appendEntry(customType, data: any) {
        if (options.failCaptureRecord && !failed && customType === CONTROL_ENTRY && data?.action === "capture") {
          failed = true;
          throw new Error("injected extension record write failure");
        }
        pi.appendEntry(customType, data);
      } });
    }
  };
  const services = await createAgentSessionServices({
    cwd: root, agentDir, modelRuntime,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
    resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension], systemPrompt: "Faux replay fixture." },
  });
  const manager = SessionManager.open(join(root, "session.jsonl"));
  const { session } = await createAgentSessionFromServices({ services, sessionManager: manager, model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" });
  await session.bindExtensions({ mode: "rpc" });
  await session.prompt("/fixture-context");
  if (!commandCtx) throw new Error("Native control context not dispatched.");
  return {
    root, session, manager, ctx: commandCtx, replay, api, contexts, rawInputs,
    get rawPreflight() { return rawPreflight; },
    close() { session.dispose(); rmSync(root, { recursive: true, force: true }); },
  };
}

sourceTest("native fresh replay stages asides once, preserves equal prepared occurrences and only raw inputs run preflight", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "saved");
    const next = handoff(captured.handoff.sessionFile);
    Object.assign(next, { requestId: "all-lanes", sessionId: captured.handoff.sessionId, leafId: captured.handoff.leafId });
    next.pending.followUp.push({ role: "user", content: [{ type: "text", text: "follow" }], timestamp: 3 });
    next.pending.nextTurn.push({ role: "custom", customType: "aside", content: "aside", display: true, timestamp: 4 });
    next.pending.deferred.push({ kind: "prepared", message: { customType: "deferred", content: "prepared-deferred", display: true } });
    const saved = snapshotHandoff(next);
    const before = f.rawPreflight;
    const updates: string[] = [];
    let queueObserverFailures = 0;
    const unsubscribe = f.session.subscribe(event => {
      if (event.type === "queue_update") { queueObserverFailures++; throw new Error("queue observer diagnostic"); }
    });
    const result = await f.replay.resume(f.ctx, saved, value => { updates.push(JSON.stringify(value)); });
    unsubscribe();
    expect(queueObserverFailures).toBeGreaterThan(0);
    expect(result).toEqual({ complete: true });
    expect(hasUnresolvedInputs(saved)).toBe(false);
    expect(saved.marker).toBe("started");
    await f.session.waitForIdle();
    expect(f.rawPreflight - before).toBe(3); // marker and two equal raw deferred occurrences
    const tagged = f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay);
    const ids = tagged.map((entry: any) => entry.details.piCodexSubagentsReplay.id);
    expect(new Set(ids).size).toBe(5);
    expect(ids).toHaveLength(5);
    expect(JSON.stringify(f.manager.getBranch())).toContain("AA==");
    expect(updates.length).toBeGreaterThan(5);
    const canonical = saved.handoff.pending;
    for (const item of saved.items) item.status = "queued";
    reconcileRecorded(saved, f.manager);
    expect(saved.handoff.pending).toBe(canonical);
    expect(saved.items.filter(item => item.status === "handled").map(item => item.id).sort()).toEqual(ids.sort());
    expect(saved.items.filter(item => item.lane === "deferred" && saved.handoff.pending.deferred[item.index].kind === "raw").every(item => item.status === "queued")).toBe(true);
  } finally { f.close(); }
}, 15000);

sourceTest("native handled marker recaptures staged aside under the same replay ID; explicit retry installs it once", async () => {
  const f = await nativeFixture({ handleMarker: true });
  try {
    await f.session.prompt("seed");
    const saved = await f.replay.capture(f.ctx, "handled");
    saved.handoff.wasActive = true;
    saved.handoff.pending.nextTurn.push({ role: "custom", customType: "aside", content: "aside-once", display: true, timestamp: 1 });
    const snapshot = snapshotHandoff(saved.handoff);
    const id = snapshot.items[0].id;
    const result = await f.replay.resume(f.ctx, snapshot);
    expect(result.complete).toBe(false);
    expect(snapshot.marker).toBe("handled");
    expect(snapshot.items).toHaveLength(1);
    expect(snapshot.items[0].id).toBe(id);
    expect(snapshot.items[0].status).toBe("pending");
    await f.replay.arm(f.ctx, snapshot);
    const admitted = await f.ctx.submitInput({ kind: "raw", text: "explicit retry marker", options: { expandPromptTemplates: false } });
    expect(admitted.disposition).toBe("started");
    expect(await f.replay.finish(f.ctx, admitted.disposition)).toEqual({ complete: true });
    await f.session.waitForIdle();
    expect(f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay?.id === id)).toHaveLength(1);
  } finally { f.close(); }
}, 15000);

sourceTest("native idle parent without own work only unfences, with no synthetic provider turn", async () => {
  const f = await nativeFixture({ hold: true });
  try {
    const saved = await f.replay.capture(f.ctx, "idle");
    expect(saved.handoff.wasActive).toBe(false);
    expect(await f.replay.resume(f.ctx, saved)).toEqual({ complete: true });
    expect(saved.marker).toBe("none");
    expect(f.contexts).toHaveLength(0);
  } finally { f.close(); }
}, 15000);

test("child helper startup requests hold synchronously before later callbacks", () => {
  // This only checks callback ordering, not native admission.
  const events: string[] = [];
  const listeners = new Map<string, Array<(...args: any[]) => unknown>>();
  const old = process.env.PI_SUBAGENT_HOLD;
  process.env.PI_SUBAGENT_HOLD = "1";
  try {
    childHelper({
      on(event: string, fn: (...args: any[]) => unknown) { listeners.set(event, [...listeners.get(event) ?? [], fn]); },
      requestPause() { events.push("pause"); }, registerCommand() {}, registerTool() {},
      getActiveTools() { return []; }, setActiveTools() {},
    } as unknown as ExtensionAPI);
    listeners.get("session_start")!.push(() => { events.push("later-extension"); });
    for (const listener of listeners.get("session_start")!) listener();
    expect(events).toEqual(["pause", "later-extension"]);
  } finally { if (old === undefined) delete process.env.PI_SUBAGENT_HOLD; else process.env.PI_SUBAGENT_HOLD = old; }
});

sourceTest("real child RPC helper holds startup and requires the actual marker acknowledgment rather than agent_start", async () => {
  const { spawn } = await import("node:child_process");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "helper-rpc-"));
  const child = spawn(process.env.PI_SUBAGENT_PI_BIN!, ["--mode", "rpc", "--session", join(root, "child.jsonl"), "--extension", join(import.meta.dir, "child-helper.ts")], {
    cwd: root, env: { ...process.env, PI_SUBAGENT_HOLD: "1" }, stdio: ["pipe", "pipe", "pipe"],
  });
  let buffer = "", stderr = "", serial = 0;
  const waiting = new Map<string, { resolve(value: any): void; reject(error: Error): void }>();
  const exited = new Promise<number | null>((resolve, reject) => { child.on("exit", resolve); child.on("error", reject); });
  child.stderr.on("data", data => { stderr += data; });
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (data: string) => {
    buffer += data;
    for (let n; (n = buffer.indexOf("\n")) >= 0;) {
      const value = JSON.parse(buffer.slice(0, n)); buffer = buffer.slice(n + 1);
      if (value.type === "response" && waiting.has(value.id)) { waiting.get(value.id)!.resolve(value); waiting.delete(value.id); }
    }
  });
  const request = (value: object): Promise<any> => {
    const id = `request-${++serial}`;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { waiting.delete(id); reject(new Error(`RPC timed out: ${JSON.stringify(value)}; ${stderr}`)); }, 5000);
      waiting.set(id, { resolve: value => { clearTimeout(timeout); resolve(value); }, reject });
      child.stdin.write(`${JSON.stringify({ ...value, id })}\n`);
    });
  };
  const control = async (action: string, extra = {}) => request({ type: "prompt", message: `/subagents-control ${JSON.stringify({ action, generation: "rpc-generation", ...extra })}` });
  const entries = async () => (await request({ type: "get_entries" })).data.entries;
  try {
    expect((await control("inspect")).data.disposition).toBe("handled");
    expect(controlRecord(await entries(), "rpc-generation", "inspect")?.ok).toBe(true);
    const blocked = await request({ type: "prompt", message: "must not start while held" });
    expect(blocked.success).toBe(false);
    await control("capture");
    const record = controlRecord(await entries(), "rpc-generation", "capture");
    expect(record?.ok).toBe(true);
    const saved = record!.snapshot!;
    saved.handoff.wasActive = true;
    saved.handoff.pending.nextTurn.push({ role: "custom", customType: "rpc-aside", content: "rpc-aside-once", display: true, timestamp: 1 });
    const snapshot = snapshotHandoff(saved.handoff);
    await control("arm", { snapshot });
    const armedEntries = await entries();
    expect(controlRecord(armedEntries, "rpc-generation", "arm")?.snapshot?.marker).toBe("pending");
    expect(controlRecord(armedEntries, "rpc-generation", "finish")).toBeUndefined();
    const marker = await request({ type: "prompt", message: CONTINUATION_MESSAGE });
    expect(marker.data.disposition).toBe("started");
    const progress = controlRecord(await entries(), "rpc-generation", "finish");
    expect(progress?.snapshot?.marker).toBe("unknown");
    expect(progress?.ok).toBe(false);
    await control("finish", { disposition: marker.data.disposition });
    expect(controlRecord(await entries(), "rpc-generation", "finish")?.ok).toBe(true);
    child.stdin.end();
    expect(await exited).toBe(0);
  } finally {
    if (child.exitCode === null) { child.kill("SIGKILL"); await exited; }
    rmSync(root, { recursive: true, force: true });
  }
}, 20000);

sourceTest("native input observer errors use core's accepted outcome and are never retried by duplicate finish", async () => {
  const f = await nativeFixture({ rejectDeferred: true });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "raw-failure");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "bad-deferred" }, { kind: "raw", text: "later-deferred" });
    const snapshot = snapshotHandoff(captured.handoff);
    const result = await f.replay.resume(f.ctx, snapshot);
    // Core logs input-listener errors and continues ordinary preflight. This
    // acceptance is native behavior, not an extension-invented retry outcome.
    expect(result.complete).toBe(true);
    expect(snapshot.items.every(item => ["queued", "started", "handled"].includes(item.status))).toBe(true);
    const again = await f.replay.finish(f.ctx, "started");
    expect(again.complete).toBe(false); // already complete/disarmed
    expect(f.rawInputs.filter(text => text === "bad-deferred")).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === "later-deferred")).toHaveLength(1);
    await f.session.waitForIdle();
  } finally { f.close(); }
}, 15000);

sourceTest("lost marker acknowledgment stays unknown despite agent_start and cannot be speculatively retried", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const snapshot = await f.replay.capture(f.ctx, "unknown");
    snapshot.handoff.wasActive = true;
    await f.replay.arm(f.ctx, snapshot);
    const actual = await f.ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } });
    expect(actual.disposition).toBe("started"); // deliberately lose this acknowledgment below
    expect((await f.replay.finish(f.ctx, "unknown")).complete).toBe(false);
    expect(snapshot.marker).toBe("unknown");
    const before = f.contexts.length;
    expect((await f.replay.resume(f.ctx, snapshot)).complete).toBe(false);
    expect(f.contexts).toHaveLength(before);
  } finally { f.close(); }
}, 15000);

sourceTest("child capture retains stable generation payload when its extension record write fails", async () => {
  const f = await nativeFixture({ failCaptureRecord: true, handleMarker: true });
  try {
    await f.session.prompt("seed");
    await f.ctx.submitInput({ kind: "prepared", message: { customType: "retained", content: "keep-on-write-failure", display: true }, options: { deliverAs: "nextTurn" } });
    const command = `/subagents-control ${JSON.stringify({ action: "capture", generation: "write-failure" })}`;
    await f.session.prompt(command);
    const first = controlRecord(f.manager.getEntries(), "write-failure", "capture");
    expect(first?.ok).toBe(false);
    expect(first?.snapshot?.items).toHaveLength(1);
    await f.session.prompt(command);
    const second = controlRecord(f.manager.getEntries(), "write-failure", "capture");
    expect(second?.ok).toBe(true);
    expect(second?.snapshot).toEqual(first?.snapshot);
    expect(second?.snapshot?.handoff.pending.nextTurn[0].content).toBe("keep-on-write-failure");
    expect(second?.snapshot?.handoff.requestId).toBe("write-failure");
    const control = (action: string, generation: string, extra = {}) => f.session.prompt(`/subagents-control ${JSON.stringify({ action, generation, ...extra })}`);
    await control("arm", second!.snapshot!.handoff.requestId, { snapshot: second!.snapshot });
    expect(controlRecord(f.manager.getEntries(), "write-failure", "arm")?.ok).toBe(true);
    expect((await f.ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } })).disposition).toBe("handled");
    await control("finish", "write-failure", { disposition: "handled" });
    const recaptured = controlRecord(f.manager.getEntries(), "write-failure", "finish")!.snapshot!;
    expect(recaptured.handoff.requestId).not.toBe("write-failure");
    const wrong = structuredClone(recaptured);
    wrong.handoff.requestId = "unrelated-capture";
    await control("arm", "unrelated-generation", { snapshot: wrong });
    expect(controlRecord(f.manager.getEntries(), "unrelated-generation", "arm")?.ok).toBe(false);
    await control("arm", recaptured.handoff.requestId, { snapshot: recaptured });
    expect(controlRecord(f.manager.getEntries(), recaptured.handoff.requestId, "arm")?.ok).toBe(true);
  } finally { f.close(); }
}, 15000);

sourceTest("a handled marker with no pending payloads does not turn an unfinished task into idle success", async () => {
  const f = await nativeFixture({ handleMarker: true });
  try {
    await f.session.prompt("seed");
    const snapshot = await f.replay.capture(f.ctx, "handled-empty");
    snapshot.handoff.wasActive = true;
    expect((await f.replay.resume(f.ctx, snapshot)).complete).toBe(false);
    expect(snapshot.handoff.wasActive).toBe(true);
    expect((await f.replay.resume(f.ctx, snapshot)).complete).toBe(false);
    expect(snapshot.marker).toBe("handled");
  } finally { f.close(); }
}, 15000);

sourceTest("native handled marker that creates a different prepared turn never acknowledges the old task", async () => {
  const f = await nativeFixture({ handleMarkerPrepared: true });
  try {
    await f.session.prompt("seed");
    const snapshot = await f.replay.capture(f.ctx, "alternate");
    snapshot.handoff.wasActive = true;
    snapshot.handoff.pending.initial.push({ role: "user", content: "saved-context", timestamp: 1 });
    const saved = snapshotHandoff(snapshot.handoff);
    const result = await f.replay.resume(f.ctx, saved);
    expect(result.complete).toBe(false);
    expect(saved.marker).toBe("handled");
    expect(saved.handoff.wasActive).toBe(true);
    expect(f.manager.getBranch().some((entry: any) => entry.type === "custom_message" && entry.customType === "alternate-turn")).toBe(true);
    expect(f.manager.getBranch().some((entry: any) => entry.type === "message" && entry.message.role === "user" && JSON.stringify(entry.message.content).includes(CONTINUATION_MESSAGE))).toBe(false);
  } finally { f.close(); }
}, 15000);

sourceTest("parent marker uncertainty is persisted before native preflight, and a failed uncertainty write prevents submission", async () => {
  let persisted = "", observed = "";
  const f = await nativeFixture({ onMarkerInput: () => { observed = persisted; } });
  try {
    await f.session.prompt("seed");
    const saved = await f.replay.capture(f.ctx, "before-marker");
    saved.handoff.wasActive = true;
    await f.replay.resume(f.ctx, saved, snapshot => { persisted = snapshot.marker; });
    expect(observed).toBe("unknown");
    await f.session.waitForIdle();
    const second = await f.replay.capture(f.ctx, "failed-marker-write");
    second.handoff.wasActive = true;
    const count = f.rawInputs.filter(text => text === CONTINUATION_MESSAGE).length;
    let failed = false;
    const result = await f.replay.resume(f.ctx, second, snapshot => {
      if (!failed && snapshot.marker === "unknown") { failed = true; throw new Error("uncertainty write failed"); }
    });
    expect(result.complete).toBe(false);
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(count);
    expect(second.marker).toBe("pending");
    expect((await f.replay.resume(f.ctx, second)).complete).toBe(true);
    await f.session.waitForIdle();
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(count + 1);
  } finally { f.close(); }
}, 15000);

sourceTest("a concurrent native fence before the guarded installer leaves extension-owned input pending", async () => {
  let intercept = false;
  let entered!: () => void, release!: () => void;
  const entering = new Promise<void>(resolve => { entered = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  const f = await nativeFixture({ beforeInstaller: pi => pi.on("agent_start", async () => {
    if (!intercept) return;
    entered();
    await gate;
  }) });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "before-fence");
    captured.handoff.wasActive = true;
    captured.handoff.pending.initial.push({ role: "user", content: "must-survive-void-rejection", timestamp: 1 });
    const saved = snapshotHandoff(captured.handoff);
    const id = saved.items[0].id;
    await f.replay.arm(f.ctx, saved);
    intercept = true;
    const admission = f.ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } });
    await entering;
    const stopping = f.ctx.handoff("external-fence");
    release();
    expect((await admission).disposition).toBe("started");
    const native = await stopping;
    expect(saved.items[0].status).toBe("pending");
    expect(JSON.stringify(native.pending)).not.toContain(id);
    const merged = await f.replay.capture(f.ctx, "external-fence");
    expect(merged.marker).toBe("unknown"); // capture itself cannot identify the prior marker admission
    expect(merged.items.filter(item => item.id === id)).toHaveLength(1);
    expect(merged.items.find(item => item.id === id)?.status).toBe("pending");
    expect(merged.handoff.wasActive).toBe(true);
    expect(JSON.stringify(merged.handoff.pending)).toContain("must-survive-void-rejection");
  } finally { release(); f.close(); }
}, 15000);

sourceTest("new capture merges known rejected and never-admitted extension work; explicit finish retries rejected only without another marker", async () => {
  const f = await nativeFixture({ abortDeferredOnce: true });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "partial");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "abort-once" }, { kind: "raw", text: "later-unadmitted" });
    const saved = snapshotHandoff(captured.handoff);
    const ids = saved.items.map(item => item.id);
    const first = await f.replay.resume(f.ctx, saved);
    expect(first.complete).toBe(false);
    expect(saved.marker).toBe("started");
    expect(saved.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    expect(f.rawInputs.filter(text => text === "abort-once")).toHaveLength(1);
    // An explicit second finish retries only rejected/unadmitted inputs.
    const retry = await f.replay.resume(f.ctx, saved);
    expect(retry.complete).toBe(true);
    expect(f.rawInputs.filter(text => text === "abort-once")).toHaveLength(2);
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(1);
    await f.session.waitForIdle();
    // Establish a second partial release, then stop/save instead of retrying.
    const next = await f.replay.capture(f.ctx, "partial-again");
    next.handoff.wasActive = true;
    next.handoff.pending.deferred.push({ kind: "raw", text: "still-unadmitted" });
    const pending = snapshotHandoff(next.handoff);
    await f.replay.arm(f.ctx, pending);
    const merged = await f.replay.capture(f.ctx, "new-save");
    expect(merged.items.map(item => item.id)).toEqual(pending.items.map(item => item.id));
    expect(merged.handoff.requestId).toBe("new-save");
    expect(merged.handoff.wasActive).toBe(true);
    expect(merged.handoff.pending.deferred).toEqual([{ kind: "raw", text: "still-unadmitted" }]);
    expect(ids).toHaveLength(2);
  } finally { f.close(); }
}, 15000);

sourceTest("saving during a rejected partial release retains every extension-owned replay identity", async () => {
  const f = await nativeFixture({ abortDeferredOnce: true });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "before-partial-save");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "abort-once" }, { kind: "raw", text: "not-yet-submitted" });
    const saved = snapshotHandoff(captured.handoff);
    const ids = saved.items.map(item => item.id);
    expect((await f.replay.resume(f.ctx, saved)).complete).toBe(false);
    expect(saved.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    const merged = await f.replay.capture(f.ctx, "save-after-partial");
    expect(merged.items.map(item => item.id)).toEqual(ids);
    expect(merged.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    expect(merged.handoff.pending.deferred).toEqual([{ kind: "raw", text: "abort-once" }, { kind: "raw", text: "not-yet-submitted" }]);
    expect(merged.handoff.wasActive).toBe(true);
    expect(await f.replay.capture(f.ctx, "save-after-partial")).toBe(merged);
  } finally { f.close(); }
}, 15000);

sourceTest("a failed pre-admission raw progress write leaves pending input explicitly retryable without another marker", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "unknown-deferred");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "unknown-input" }, { kind: "raw", text: "later-input" });
    const saved = snapshotHandoff(captured.handoff);
    let failed = false;
    expect((await f.replay.resume(f.ctx, saved, snapshot => {
      if (!failed && snapshot.items[0].status === "unknown") { failed = true; throw new Error("pre-admission progress write failed"); }
    })).complete).toBe(false);
    expect(saved.marker).toBe("started");
    expect(saved.items.map(item => item.status)).toEqual(["pending", "pending"]);
    expect(f.rawInputs).not.toContain("unknown-input");
    expect(f.rawInputs).not.toContain("later-input");
    expect((await f.replay.resume(f.ctx, saved)).complete).toBe(true);
    await f.session.waitForIdle();
    expect(f.rawInputs.filter(text => text === "unknown-input")).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === "later-input")).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(1);
  } finally { f.close(); }
}, 15000);

sourceTest("an ancestor snapshot reconciles a descendant recorded aside before arm can stage it again", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "ancestor-manifest");
    captured.handoff.wasActive = true;
    captured.handoff.pending.nextTurn.push({ role: "custom", customType: "ancestor-aside", content: "recorded-after-manifest", display: true, timestamp: 1 });
    const first = snapshotHandoff(captured.handoff);
    const oldSaved = structuredClone(first);
    const id = oldSaved.items[0].id;
    expect((await f.replay.resume(f.ctx, first)).complete).toBe(true);
    await f.session.waitForIdle();
    const occurrences = () => f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay?.id === id);
    expect(occurrences()).toHaveLength(1);
    expect(oldSaved.items[0].status).toBe("pending"); // unchanged ancestor manifest
    await f.replay.capture(f.ctx, "descendant-fence");
    const replayed = await f.replay.resume(f.ctx, oldSaved);
    expect(replayed.complete).toBe(true);
    await f.session.waitForIdle();
    expect(oldSaved.items[0].status).toBe("handled");
    expect(occurrences()).toHaveLength(1);
    const stopped = await f.replay.capture(f.ctx, "after-old-manifest");
    expect(stopped.items.some(item => item.id === id)).toBe(false);
    expect(occurrences()).toHaveLength(1);
  } finally { f.close(); }
}, 15000);

sourceTest("an earlier native agent_start pause skips synchronous replay queues and preserves every occurrence", async () => {
  let pauseNext = false;
  const f = await nativeFixture({ beforeInstaller: pi => pi.on("agent_start", () => {
    if (pauseNext) pi.requestPause();
  }) });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "before-listener-pause");
    captured.handoff.wasActive = true;
    for (const lane of ["initial", "steering", "followUp"] as const) {
      captured.handoff.pending[lane].push({ role: "user", content: "equal-pending", timestamp: 1 });
    }
    const saved = snapshotHandoff(captured.handoff);
    const ids = saved.items.map(item => item.id);
    pauseNext = true;
    expect((await f.replay.resume(f.ctx, saved)).complete).toBe(false);
    expect(saved.marker).toBe("started");
    expect(saved.items.map(item => item.status)).toEqual(["pending", "pending", "pending"]);
    expect(f.api.getPauseState()).not.toBe("unpaused");
    const stopped = await f.replay.capture(f.ctx, "after-listener-pause");
    expect(stopped.items.map(item => item.id)).toEqual(ids);
    expect(stopped.items.map(item => item.status)).toEqual(["pending", "pending", "pending"]);
    expect(f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay)).toHaveLength(0);
    pauseNext = false;
    expect((await f.replay.resume(f.ctx, stopped)).complete).toBe(true);
    await f.session.waitForIdle();
    const recorded = f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay);
    expect(recorded.map((entry: any) => entry.details.piCodexSubagentsReplay.id).sort()).toEqual(ids.sort());
  } finally { f.close(); }
}, 15000);

sourceTest("discarding a partial parent replay prevents resurrection on fresh capture but preserves equal-text core-owned asides", async () => {
  const f = await nativeFixture({ abortDeferredOnce: true });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "before-parent-discard");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "abort-once" }, { kind: "raw", text: "explicitly-discard-this" });
    const saved = snapshotHandoff(captured.handoff);
    expect((await f.replay.resume(f.ctx, saved)).complete).toBe(false);
    expect(saved.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    await f.session.waitForIdle();
    expect((await f.ctx.submitInput({ kind: "prepared", message: { customType: "owned-core", content: "explicitly-discard-this", display: true }, options: { deliverAs: "nextTurn" } })).disposition).toBe("queued");
    const pause = f.api.getPauseState();
    f.replay.discardSavedInputs(); // the coordinator calls this after durable revocation
    f.replay.discardSavedInputs(); // idempotent
    expect(f.api.getPauseState()).toBe(pause);
    const fresh = await f.replay.capture(f.ctx, "after-parent-discard");
    expect(fresh.handoff.pending.deferred).toEqual([]);
    expect(fresh.handoff.pending.nextTurn).toHaveLength(1);
    expect(fresh.handoff.pending.nextTurn[0].content).toBe("explicitly-discard-this");
    expect(fresh.items.some(item => saved.items.some(old => old.id === item.id))).toBe(false);
    expect((await f.replay.resume(f.ctx, fresh)).complete).toBe(true);
    await f.session.waitForIdle();
    expect(f.rawInputs).not.toContain("explicitly-discard-this");
    expect(f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.customType === "owned-core")).toHaveLength(1);
  } finally { f.close(); }
}, 15000);

sourceTest("discard leaves an already admitted native parent run active and does not release unadmitted replay inputs", async () => {
  let intercept = false;
  let entered!: () => void, release!: () => void;
  const entering = new Promise<void>(resolve => { entered = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  const f = await nativeFixture({ beforeInstaller: pi => pi.on("agent_start", async () => {
    if (intercept) { entered(); await gate; }
  }) });
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "active-discard");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "not-yet-admitted" });
    const saved = snapshotHandoff(captured.handoff);
    await f.replay.arm(f.ctx, saved);
    intercept = true;
    const admission = f.ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } });
    await entering;
    expect((await admission).disposition).toBe("started");
    expect(f.ctx.isIdle()).toBe(false);
    f.replay.discardSavedInputs();
    expect(f.ctx.isIdle()).toBe(false);
    expect(f.api.getPauseState()).toBe("unpaused");
    release();
    await f.session.waitForIdle();
    expect(f.contexts).toHaveLength(2); // seed and the already admitted continuation
    const fresh = await f.replay.capture(f.ctx, "after-active-discard");
    expect(fresh.items).toEqual([]);
    expect(f.rawInputs).not.toContain("not-yet-admitted");
  } finally { release(); f.close(); }
}, 15000);

sourceTest("child discard validates generation, acknowledges idempotently, and forgets partial replay without clearing core queues", async () => {
  const f = await nativeFixture({ childControl: true, abortDeferredOnce: true });
  const generation = "child-discard";
  const control = (action: string, gen = generation, extra = {}) => f.session.prompt(`/subagents-control ${JSON.stringify({ action, generation: gen, ...extra })}`);
  try {
    await f.session.prompt("seed");
    await control("capture");
    const captured = controlRecord(f.manager.getEntries(), generation, "capture")!.snapshot!;
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "abort-once" }, { kind: "raw", text: "discard-child-input" });
    const saved = snapshotHandoff(captured.handoff);
    await control("arm", generation, { snapshot: saved });
    const marker = await f.ctx.submitInput({ kind: "raw", text: CONTINUATION_MESSAGE, options: { expandPromptTemplates: false } });
    expect(marker.disposition).toBe("started");
    await control("finish", generation, { disposition: marker.disposition });
    const partial = controlRecord(f.manager.getEntries(), generation, "finish")!;
    expect(partial.ok).toBe(false);
    expect(partial.snapshot!.items.map(item => item.status)).toEqual(["rejected", "pending"]);
    await f.session.waitForIdle();
    expect((await f.ctx.submitInput({ kind: "prepared", message: { customType: "child-core-owned", content: "discard-child-input", display: true }, options: { deliverAs: "nextTurn" } })).disposition).toBe("queued");
    await control("discard", "stale-generation");
    expect(controlRecord(f.manager.getEntries(), "stale-generation", "discard")?.ok).toBe(false);
    const pause = f.api.getPauseState();
    await control("discard");
    const first = f.manager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === CONTROL_ENTRY && entry.data.action === "discard" && entry.data.generation === generation);
    expect(controlRecord(first, generation, "discard")).toEqual({ version: 1, generation, action: "discard", ok: true, sessionId: f.manager.getSessionId() });
    await control("discard");
    const acks = f.manager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === CONTROL_ENTRY && entry.data.action === "discard" && entry.data.generation === generation);
    expect(acks).toHaveLength(2);
    expect(acks[0].id).not.toBe(acks[1].id);
    expect(f.api.getPauseState()).toBe(pause);
    await control("capture", "fresh-after-child-discard");
    const fresh = controlRecord(f.manager.getEntries(), "fresh-after-child-discard", "capture")!.snapshot!;
    expect(fresh.handoff.pending.deferred).toEqual([]);
    expect(fresh.handoff.pending.nextTurn).toHaveLength(1);
    expect(fresh.handoff.pending.nextTurn[0].content).toBe("discard-child-input");
    expect(fresh.items.some(item => saved.items.some(old => old.id === item.id))).toBe(false);
    expect(f.rawInputs).not.toContain("discard-child-input");
  } finally { f.close(); }
}, 15000);

for (const stage of ["before", "after"] as const) {
  sourceTest(`${stage}-aside-admission progress failure preserves known ownership and explicit repair delivers once`, async () => {
    const f = await nativeFixture();
    try {
      await f.session.prompt("seed");
      const captured = await f.replay.capture(f.ctx, `aside-write-${stage}`);
      captured.handoff.wasActive = true;
      captured.handoff.pending.nextTurn.push({ role: "custom", customType: "write-failure-aside", content: "aside-exactly-once", display: true, timestamp: 1 });
      const saved = snapshotHandoff(captured.handoff);
      const id = saved.items[0].id;
      let failed = false;
      const update = (snapshot: typeof saved) => {
        if (!failed && snapshot.items[0].status === (stage === "before" ? "unknown" : "queued")) {
          failed = true;
          throw new Error(`${stage}-aside progress write failure`);
        }
      };
      await expect(f.replay.arm(f.ctx, saved, update)).rejects.toThrow(`${stage}-aside progress write failure`);
      expect(saved.items[0].status).toBe(stage === "before" ? "pending" : "queued");
      expect(f.rawInputs).not.toContain(CONTINUATION_MESSAGE);
      expect(await f.replay.disarm(f.ctx, update)).toBe(saved);
      expect(saved.items).toHaveLength(1);
      expect(saved.items[0].id).toBe(id);
      expect(saved.items[0].status).toBe("pending");
      expect((await f.replay.resume(f.ctx, saved, update)).complete).toBe(true);
      await f.session.waitForIdle();
      expect(f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay?.id === id)).toHaveLength(1);
      expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(1);
    } finally { f.close(); }
  }, 15000);
}

sourceTest("installer and outside prepared fallback restore pending after pre-effect progress failure", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "prepared-write-failure");
    captured.handoff.wasActive = true;
    captured.handoff.pending.initial.push({ role: "user", content: "prepared-once-after-repair", timestamp: 1 });
    const saved = snapshotHandoff(captured.handoff);
    const id = saved.items[0].id;
    let repaired = false;
    const update = (snapshot: typeof saved) => {
      if (!repaired && snapshot.items[0].status === "unknown") throw new Error("prepared progress storage unavailable");
    };
    expect((await f.replay.resume(f.ctx, saved, update)).complete).toBe(false);
    expect(saved.marker).toBe("started");
    expect(saved.items[0].status).toBe("pending");
    repaired = true;
    expect((await f.replay.resume(f.ctx, saved, update)).complete).toBe(true);
    await f.session.waitForIdle();
    expect(f.manager.getBranch().filter((entry: any) => entry.type === "custom_message" && entry.details?.piCodexSubagentsReplay?.id === id)).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(1);
  } finally { f.close(); }
}, 15000);

sourceTest("failed post-admission raw progress write keeps confirmed ownership and never resubmits it", async () => {
  const f = await nativeFixture();
  try {
    await f.session.prompt("seed");
    const captured = await f.replay.capture(f.ctx, "raw-post-admission-write");
    captured.handoff.wasActive = true;
    captured.handoff.pending.deferred.push({ kind: "raw", text: "already-admitted-once" }, { kind: "raw", text: "later-after-repair" });
    const saved = snapshotHandoff(captured.handoff);
    let failed = false;
    const update = (snapshot: typeof saved) => {
      if (!failed && ["started", "queued"].includes(snapshot.items[0].status)) {
        failed = true;
        throw new Error("post-admission progress write failed");
      }
    };
    expect((await f.replay.resume(f.ctx, saved, update)).complete).toBe(false);
    expect(["started", "queued"]).toContain(saved.items[0].status);
    expect(saved.items[1].status).toBe("pending");
    expect((await f.replay.resume(f.ctx, saved, update)).complete).toBe(true);
    await f.session.waitForIdle();
    expect(f.rawInputs.filter(text => text === "already-admitted-once")).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === "later-after-repair")).toHaveLength(1);
    expect(f.rawInputs.filter(text => text === CONTINUATION_MESSAGE)).toHaveLength(1);
  } finally { f.close(); }
}, 15000);
