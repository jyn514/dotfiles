// Exercise the registered tool through Pi's runtime and the real worker transport.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { access, copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { createGuestAttachment } from "../../libexec/pi-tool-execution.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageDir = process.env.PI_PACKAGE_DIR ?? "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const sdkUrl = pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href;
const sdk = await import(sdkUrl);

test("registered read_session reads a guest session through the actual worker", async t => {
  const dir = await mkdtemp(join(tmpdir(), "routed-reader-"));
  const guest = join(dir, "guest");
  const agentDir = join(dir, "agent");
  const sessions = join(dir, "sessions");
  await Promise.all([guest, agentDir, sessions].map(path => mkdir(path)));
  const sessionDirectory = join(sessions, "--guest--");
  await mkdir(sessionDirectory);
  const manager = sdk.SessionManager.create(guest, sessionDirectory);
  manager.appendMessage({ role: "user", content: "guest-only example text", timestamp: Date.now() });
  manager.appendMessage({ role: "user", content: "second page text", timestamp: Date.now() });
  manager.appendSessionInfo("Guest example title");
  manager.ensurePersisted();
  const sessionFile = manager.getSessionFile();
  const guestOnly = sdk.SessionManager.create(guest, sessionDirectory);
  guestOnly.appendMessage({ role: "user", content: "unavailable on host transcript", timestamp: Date.now() });
  guestOnly.appendSessionInfo("Guest-only title");
  guestOnly.ensurePersisted();
  const guestOnlyFile = guestOnly.getSessionFile();
  const hostRoot = join(dir, "host-sessions");
  const hostSessionDirectory = join(hostRoot, "--guest--");
  await mkdir(hostSessionDirectory, { recursive: true });
  await copyFile(sessionFile, join(hostSessionDirectory, sessionFile.slice(sessionDirectory.length + 1)));
  const hostManager = sdk.SessionManager.create(guest, hostSessionDirectory);
  hostManager.appendMessage({ role: "user", content: "host only search example", timestamp: Date.now() });
  hostManager.ensurePersisted();
  const hostOnly = hostManager.getSessionFile();
  const codexFile = join(guest, "codex.jsonl");
  await writeFile(codexFile, [
    { type: "session_meta", timestamp: "2026-10-17T10:00:00Z", payload: { id: "00000001-0000-4000-8000-000000000000", cwd: guest, timestamp: "2026-10-17T10:00:00Z" } },
    { type: "response_item", timestamp: "2026-10-17T10:00:01Z", payload: { type: "message", role: "user", content: [{ type: "input_text", text: "Codex example" }] } },
  ].map(row => JSON.stringify(row)).join("\n") + "\n");
  const socket = join(dir, "worker.sock");
  const ready = join(dir, "worker-ready");
  const worker = spawn(process.execPath, [join(root, "tools/codex-sandbox/image/tool-worker.mjs")], {
    cwd: guest,
    env: { ...process.env, CODEX_SANDBOX_TOOL_SOCKET: socket, CODEX_SANDBOX_TOOL_READY: ready,
      CODEX_SANDBOX_PI_TOOL_MODULE: sdkUrl, PI_SESSION_SEARCH_ROOT: sessions },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  worker.stderr.on("data", chunk => { stderr += chunk; });
  const keys = ["CODEX_SANDBOX_TOOL_CONTAINER", "CODEX_SANDBOX_TOOL_CONNECT", "CODEX_SANDBOX_TOOL_COMMAND", "CODEX_SANDBOX_GUEST_CWD", "CODEX_SANDBOX_GUEST_REPO", "CODEX_SANDBOX_PI_RESOURCE_PATHS", "PI_SESSION_SEARCH_ROOT"];
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  t.after(async () => {
    for (const key of keys) saved[key] === undefined ? delete process.env[key] : process.env[key] = saved[key];
    if (worker.exitCode === null && worker.signalCode === null) {
      const exited = once(worker, "exit"); worker.kill(); await exited;
    }
    await rm(dir, { recursive: true, force: true });
  });
  for (let n = 0; ; n++) {
    try { await access(ready); break; } catch {
      assert.ok(n < 100 && worker.exitCode === null, `worker failed: ${stderr}`);
      await new Promise(resolveDelay => setTimeout(resolveDelay, 20));
    }
  }
  Object.assign(process.env, {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_TOOL_CONNECT: join(root, "tools/codex-sandbox/sandbox-tool-connect"),
    CODEX_SANDBOX_GUEST_CWD: guest,
    CODEX_SANDBOX_GUEST_REPO: guest,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({ [hostRoot]: sessions }),
    PI_SESSION_SEARCH_ROOT: hostRoot,
    CODEX_SANDBOX_TOOL_COMMAND: JSON.stringify(["/usr/bin/env", `CODEX_SANDBOX_TOOL_SOCKET=${socket}`,
      process.execPath, join(root, "tools/codex-sandbox/image/tool-connect.mjs")]),
  });
  // Pi merges the authoritative user and trusted project files; project wins
  // for the reader while preserving the unrelated host-only assertion.
  await mkdir(join(guest, ".pi"));
  await writeFile(join(agentDir, "settings.json"), JSON.stringify({ sandbox: { toolExecution: {
    read_session: "host", search_sessions: "host",
  } } }));
  await writeFile(join(guest, ".pi", "settings.json"), JSON.stringify({ sandbox: { toolExecution: {
    read_session: "guest", fixture_delay: "guest",
  } } }));
  const settingsManager = sdk.SettingsManager.create(guest, agentDir, { projectTrusted: true });
  assert.deepEqual(settingsManager.getSettings().sandbox.toolExecution, { read_session: "guest", search_sessions: "host", fixture_delay: "guest" });
  // Install before Pi loads extensions: the loader may capture builtin imports.
  const denied = new Set([sessionFile, codexFile, guestOnlyFile,
    join(hostRoot, guestOnlyFile.slice(sessions.length + 1))]);
  const originals = {
    realpath: fs.promises.realpath, stat: fs.promises.stat, open: fs.promises.open,
    createReadStream: fs.createReadStream, readFileSync: fs.readFileSync,
    statSync: fs.statSync, openSync: fs.openSync,
  };
  let hostReads = 0;
  function deny(path) {
    if (typeof path === "string" && denied.has(path)) {
      hostReads++;
      throw Error("host cannot read guest session");
    }
  }
  for (const name of ["realpath", "stat", "open"]) {
    fs.promises[name] = async (...args) => { deny(args[0]); return originals[name](...args); };
  }
  for (const name of ["createReadStream", "readFileSync", "statSync", "openSync"]) {
    fs[name] = (...args) => { deny(args[0]); return originals[name](...args); };
  }
  syncBuiltinESMExports();
  t.after(() => {
    for (const name of ["realpath", "stat", "open"]) fs.promises[name] = originals[name];
    for (const name of ["createReadStream", "readFileSync", "statSync", "openSync"]) fs[name] = originals[name];
    syncBuiltinESMExports();
  });
  const loader = new sdk.DefaultResourceLoader({ cwd: guest, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
    additionalExtensionPaths: [join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
      join(root, "config/pi-agent/pi-extensions/session-tools.ts"),
      join(root, "config/pi-agent/pi-extensions/session-title.ts"),
      join(root, "tests/pi/tool_execution_fixture.ts")] });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const modelRuntime = await sdk.ModelRuntime.create({ modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
  const { session } = await sdk.createAgentSession({ cwd: guest, agentDir, resourceLoader: loader,
    settingsManager, modelRuntime, sessionManager: sdk.SessionManager.inMemory(guest) });
  t.after(() => session.dispose());
  const errors = [];
  await session.bindExtensions({ onError: error => errors.push(error) });
  assert.deepEqual(errors, []);
  const initialActive = session.getActiveToolNames();
  assert.ok(initialActive.includes("fixture_delay"));
  const originalExposure = session.getAllTools().find(item => item.name === "fixture_delay").exposure;
  session.setActiveToolsByName(initialActive.filter(name => name !== "fixture_delay"));
  const inactive = session.getActiveToolNames();
  assert.ok(!inactive.includes("fixture_delay"));
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "host" } } });
  await session.extensionRunner.emit({ type: "session_start", reason: "reload" });
  assert.deepEqual(errors, []);
  assert.deepEqual(session.getActiveToolNames(), inactive, "placement refresh must not activate a disabled tool");
  const inspected = session.getAllTools().find(item => item.name === "fixture_delay");
  assert.ok(inspected, "inactive tool remains registered and inspectable");
  assert.match(inspected.description, /host \(settings\)/);
  assert.equal(inspected.exposure, originalExposure);
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "guest" } } });
  await session.extensionRunner.emit({ type: "session_start", reason: "reload" });
  assert.deepEqual(session.getActiveToolNames(), inactive);
  assert.match(session.getAllTools().find(item => item.name === "fixture_delay").description, /guest \(settings\)/);
  session.setActiveToolsByName(initialActive);
  const guestExtension = loader.getExtensions().extensions.find(item => item.tools.has("bash"));
  for (const name of ["read", "bash", "edit", "write", "grep", "find", "ls"]) {
    assert.match(session.getAllTools().find(item => item.name === name).description, /guest \(default\)/);
  }
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "guest", bash: "host" } } });
  await assert.rejects(guestExtension.tools.get("bash").definition.execute("bash-test", { command: "echo forbidden" },
    undefined, undefined, session.extensionRunner.createToolContext("bash-test", undefined)), /bash execution: host \(settings\).*policy/i);
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "guest" } } });
  const delayedExtension = loader.getExtensions().extensions.find(item => item.tools.has("fixture_delay"));
  const delay = delayedExtension.tools.get("fixture_delay").definition;
  let admitted;
  const started = new Promise(resolveStarted => { admitted = resolveStarted; });
  const pending = delay.execute("delayed", {}, undefined, update => {
    assert.match(JSON.stringify(update), /guest admitted/); admitted();
  }, session.extensionRunner.createToolContext("delayed", undefined));
  await started;
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "host" } } });
  const hostAfterReload = await delay.execute("after", {}, undefined, undefined,
    session.extensionRunner.createToolContext("after", undefined));
  assert.match(JSON.stringify(hostAfterReload), /host completed/);
  const guestInFlight = await pending;
  assert.match(JSON.stringify(guestInFlight), /guest completed/);
  assert.equal(guestInFlight.details.toolExecution.target, "guest");
  assert.equal(hostAfterReload.details.toolExecution.target, "host");
  settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "guest" } } });
  const controller = new AbortController();
  let cancelStarted;
  const cancelReady = new Promise(resolveStarted => { cancelStarted = resolveStarted; });
  const cancelled = delay.execute("cancelled", {}, controller.signal, () => cancelStarted(),
    session.extensionRunner.createToolContext("cancelled", undefined));
  await cancelReady;
  controller.abort();
  await assert.rejects(cancelled, /cancelled/i);
  const attachment = createGuestAttachment(process.env);
  const context = { model: null, session: null };
  const descriptor = { module: pathToFileURL(join(root, "tests/pi/tool_execution_fixture.ts")).href, export: "missingExport" };
  await assert.rejects(attachment.call("fixture_delay", {}, context, undefined, undefined, undefined, undefined, descriptor), /export/i);
  await assert.rejects(attachment.call("fixture_delay", {}, context, undefined, undefined, undefined, undefined,
    { ...descriptor, module: pathToFileURL(join(dir, "missing.mjs")).href }), /import|module/i);
  const extension = loader.getExtensions().extensions.find(item => item.tools.has("read_session"));
  assert.ok(extension, "read_session must be registered by the adapter");
  const read = extension.tools.get("read_session").definition;
  const call = params => read.execute("reader-test", params, undefined, undefined,
    session.extensionRunner.createToolContext("reader-test", undefined));
  const params = { sessionFile, maxMessages: 1 };
  const raw = await call(params);
  assert.notEqual(raw.isError, true, JSON.stringify(raw));
  assert.match(JSON.stringify(raw), /guest-only example text/);
  assert.equal(raw.details.toolExecution.target, "guest");
  assert.equal(raw.details.hasMore, true);
  const continuation = await call({ sessionFile, after: raw.details.nextCursor, maxMessages: 1 });
  assert.match(JSON.stringify(continuation), /second page text/);
  const byId = await call({ sessionId: manager.getSessionId(), maxMessages: 1 });
  assert.match(JSON.stringify(byId), /guest-only example text/);
  const relative = await call({ sessionFile: sessionFile.slice(sessions.length + 1), maxMessages: 1 });
  assert.match(JSON.stringify(relative), /guest-only example text/);
  const edits = await call({ sessionFile, view: "edit_candidates" });
  assert.equal(edits.details.view, "edit_candidates");
  const search = extension.tools.get("search_sessions").definition;
  const searchPath = async query => {
    const result = await search.execute("search-test", { query }, undefined, undefined,
      session.extensionRunner.createToolContext("search-test", undefined));
    assert.notEqual(result.isError, true, JSON.stringify(result));
    const hits = JSON.parse(result.content[0].text).hits;
    assert.equal(hits.length, 1);
    return hits[0].sessionFile;
  };
  const mappedPath = await searchPath("guest-only example text");
  assert.equal(mappedPath, sessionFile.slice(sessions.length + 1));
  const mapped = await call({ sessionFile: mappedPath });
  assert.match(JSON.stringify(mapped), /guest-only example text/);
  const absoluteMapped = await call({ sessionFile: join(hostRoot, mappedPath) });
  assert.match(JSON.stringify(absoluteMapped), /guest-only example text/);
  // Pass the real host-only search result unchanged; its mapped guest file is absent.
  const hostOnlyPath = await searchPath("host only search example");
  assert.equal(hostOnlyPath, hostOnly.slice(hostRoot.length + 1));
  const missing = await call({ sessionFile: hostOnlyPath });
  assert.equal(missing.isError, true);
  assert.match(JSON.stringify(missing), /guest/i);

  const warningRaw = await call({ sessionFile: codexFile });
  assert.notEqual(warningRaw.isError, true, JSON.stringify(warningRaw));
  assert.match(warningRaw.details.sessionTitleWarning, /Codex title database/);
  // The host-routed control proves the denial reaches the reader; the worker
  // has a separate process and can still access the same guest-only fixture.
  try {
    settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "host", search_sessions: "host", fixture_delay: "guest" } } });
    const blocked = await call({ sessionFile: guestOnlyFile });
    assert.equal(blocked.isError, true);
    assert.match(JSON.stringify(blocked), /host cannot read guest session/);
    assert.ok(hostReads > 0, "host-routed control must exercise the denial fixture");
    hostReads = 0;
    settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "guest", search_sessions: "host", fixture_delay: "guest" } } });
    const guestParams = { sessionFile: guestOnlyFile, maxMessages: 1 };
    const guestResult = await call(guestParams);
    assert.notEqual(guestResult.isError, true, JSON.stringify(guestResult));
    assert.match(JSON.stringify(guestResult), /unavailable on host transcript/);
    assert.equal(guestResult.details.sessionFile, guestOnlyFile);
    assert.equal(guestResult.details.toolExecution.target, "guest");
    assert.equal(hostReads, 0, "guest read must not touch the host transcript");
    // Historical results retain their original route even after settings change.
    settingsManager.applyOverrides({ sandbox: { toolExecution: { read_session: "host", search_sessions: "host", fixture_delay: "guest" } } });
    const guestTitle = await session.extensionRunner.emitToolResult({ ...guestResult, type: "tool_result", toolCallId: "guest-only-test",
      toolName: "read_session", input: guestParams, isError: false });
    assert.equal(guestTitle?.details.sessionTitle, "Guest-only title");
    assert.deepEqual(guestTitle.content.slice(1), guestResult.content);
    const result = await session.extensionRunner.emitToolResult({ ...raw, type: "tool_result", toolCallId: "reader-test",
      toolName: "read_session", input: params, isError: false });
    assert.deepEqual(errors, []);
    assert.equal(result?.details.sessionTitle, "Guest example title");
    const warning = await session.extensionRunner.emitToolResult({ ...warningRaw, type: "tool_result", toolCallId: "warning-test",
      toolName: "read_session", input: { sessionFile: codexFile }, isError: false });
    assert.match(warning?.details.sessionTitleWarning, /Codex title database/);
    assert.match(warning.content[0].text, /Warning:/);
    assert.equal(hostReads, 0);
  } finally {
    for (const name of ["realpath", "stat", "open"]) fs.promises[name] = originals[name];
    for (const name of ["createReadStream", "readFileSync", "statSync", "openSync"]) fs[name] = originals[name];
    syncBuiltinESMExports();
  }
});

test("old-worker protocol rejection identifies unsupported portable requests", async () => {
  const attachment = createGuestAttachment({ CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_TOOL_CONNECT: join(root, "tests/pi/legacy_worker_connector.py") });
  const context = { model: null, session: null };
  await assert.rejects(attachment.call("portable", {}, context, undefined, undefined, undefined, undefined,
    { module: pathToFileURL(join(root, "tests/pi/tool_execution_fixture.ts")).href, export: "delayedGuest" }), error => {
    assert.equal(error.code, "WORKER_PROTOCOL_UNSUPPORTED");
    assert.match(error.message, /portable/);
    assert.match(error.message, /restart|update/i);
    return true;
  });
  await assert.rejects(attachment.call("ordinary", {}, context), error => {
    assert.equal(error.message, "unknown tool");
    assert.notEqual(error.code, "WORKER_PROTOCOL_UNSUPPORTED");
    return true;
  });
});

test("transport retains terminal and boundary failures and response limit", async () => {
  const attachment = createGuestAttachment({ CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_TOOL_CONNECT: join(root, "tests/pi/legacy_worker_connector.py") });
  const context = { model: null, session: null };
  await assert.rejects(attachment.call("read", { mode: "duplicate" }, context), /duplicate guest tool result/);
  await assert.rejects(attachment.call("read", { mode: "oversize" }, context), /response is too large/);
  let boundary;
  await assert.rejects(attachment.call("read", { mode: "boundary" }, context, undefined, undefined, undefined,
    { onBoundary: value => { boundary = value; } }), /worker refused/);
  assert.deepEqual(boundary, { error: "checkpoint failed" });
  await assert.rejects(attachment.call("read", { mode: "invalid-boundary" }, context, undefined, undefined, undefined,
    { onBoundary() {} }), /invalid guest boundary error/);
});
