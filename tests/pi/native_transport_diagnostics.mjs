import assert from "node:assert/strict";
import { channel } from "node:diagnostics_channel";
import { createServer } from "node:http";
import { createServer as createTcpServer } from "node:net";
import { createRequire } from "node:module";
import { once } from "node:events";
import { test } from "node:test";
import { mkdtemp, readFile, readdir, realpath, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import transportDiagnostics, { observeTransport, instrumentProvider, probeNetwork, parseTcpSamples } from "../../config/pi-agent/pi-extensions/transport-diagnostics.ts";

async function installedAiModule(subpath = ".") {
  const packageDir = await realpath(process.env.PI_PACKAGE_DIR);
  const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
  const require = createRequire(resolve(packageDir, manifest.exports["."].import));
  for (const modules of require.resolve.paths("@earendil-works/pi-ai")) {
    const directory = join(modules, "@earendil-works/pi-ai");
    let aiManifest;
    try { aiManifest = JSON.parse(await readFile(join(directory, "package.json"), "utf8")); }
    catch (error) { if (error.code === "ENOENT") continue; throw error; }
    const target = subpath === "." ? aiManifest.exports["."].import
      : aiManifest.exports["./providers/*"].import.replace("*", subpath);
    return import(pathToFileURL(resolve(directory, target)).href);
  }
  throw new Error("installed Pi provider not found");
}

async function installedProvider() { return (await installedAiModule("openai-codex")).openaiCodexProvider(); }

test("installed Pi loads the extension and releases its observers on reload", async () => {
  const packageDir = process.env.PI_PACKAGE_DIR;
  assert.ok(packageDir, "run through dev/test-environment to locate installed Pi");
  const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
  const { discoverAndLoadExtensions } = await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
  const extension = fileURLToPath(new URL("../../config/pi-agent/pi-extensions/transport-diagnostics.ts", import.meta.url));
  const directory = await mkdtemp(join(tmpdir(), "pi-transport-loader-"));
  const source = channel("undici:request:error");
  assert.equal(source.hasSubscribers, false);
  try {
    for (let reload = 0; reload < 2; reload++) {
      const loaded = await discoverAndLoadExtensions([extension], directory, join(directory, "agent"));
      assert.deepEqual(loaded.errors, []);
      assert.equal(source.hasSubscribers, true);
      for (const handler of loaded.extensions[0].handlers.get("session_shutdown")) {
        await handler({ type: "session_shutdown", reason: "reload" }, {});
      }
      assert.equal(source.hasSubscribers, false);
    }
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("captures a real fetch stream failure with response timing and peer", async () => {
  const records = [];
  const stop = observeTransport(record => { if (record.type === "http_attempt") records.push(record); }, () => "test-session");
  const server = createServer((_request, response) => {
    response.writeHead(200, { "Content-Type": "text/event-stream", "x-request-id": "fixture-request",
      "Set-Cookie": "private-cookie", "x-private": "private-response" });
    response.write("data: incomplete\n\n");
    setTimeout(() => response.socket.destroy(), 20);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/codex/responses`, {
      method: "POST", headers: { Authorization: "Bearer secret", Cookie: "private-cookie",
        "User-Agent": "diagnostic-fixture", "x-client-request-id": "fixture-client",
        "OpenAI-Beta": "responses=experimental", "x-private": "private-request" }, body: "private prompt",
    });
    await assert.rejects(response.text());
    assert.equal(records.length, 1);
    const record = records[0];
    assert.equal(record.status, 200);
    assert.equal(record.sessionId, "test-session");
    assert.equal(record.requestId, "fixture-request");
    assert.equal(record.requestHeaders["user-agent"], "diagnostic-fixture");
    assert.equal(record.requestHeaders["x-client-request-id"], "fixture-client");
    assert.equal(record.requestHeaders["openai-beta"], "responses=experimental");
    assert.equal(record.responseHeaders["x-request-id"], "fixture-request");
    assert.equal(record.responseHeaders["content-type"], "text/event-stream");
    assert.ok(record.elapsedMs >= record.headersMs);
    assert.equal(typeof record.lastChunkAgoMs, "number");
    assert.ok(record.lastChunkAgoMs >= 0);
    assert.ok(record.lastChunkAgoMs <= record.elapsedMs - record.headersMs);
    assert.equal(record.socket.remoteAddress, "127.0.0.1");
    assert.equal(record.socket.remotePort, server.address().port);
    assert.ok(record.socket.bytesRead > 0);
    assert.ok(record.errors.some(error => error.code === "UND_ERR_SOCKET"));
    assert.doesNotMatch(JSON.stringify(record), /secret|private|incomplete/);
  } finally {
    stop();
    server.close();
    await once(server, "close");
  }
});

function failRequest(path = "/backend-api/codex/responses?private-query", origin = "https://user:password@chatgpt.com") {
  const request = { method: "POST", origin, path, headers: "Bearer private-token" };
  channel("undici:request:create").publish({ request });
  channel("undici:request:error").publish({ request, error: Object.assign(new Error("private-token"), {
    code: "UND_ERR_SOCKET", cause: Object.assign(new Error("private prompt"), { code: "ECONNRESET" }),
  }) });
}

test("omits sensitive fields, ignores unrelated requests, and unsubscribes", () => {
  const records = [];
  const stop = observeTransport(record => { if (record.type === "http_attempt") records.push(record); });
  try {
    failRequest("/unrelated");
    failRequest();
    assert.equal(records.length, 1);
    assert.equal(records[0].origin, "https://chatgpt.com");
    assert.equal(records[0].path, "/backend-api/codex/responses");
    assert.equal(records[0].lastChunkAgoMs, null, "no observed chunk must not imply zero idle time");
    assert.deepEqual(records[0].errors.map(error => error.code), ["UND_ERR_SOCKET", "ECONNRESET"]);
    assert.doesNotMatch(JSON.stringify(records), /password|user:|private/);
  } finally { stop(); }
  failRequest();
  assert.equal(records.length, 1);
});

test("diagnostics subscribers cannot break transport when logging throws", () => {
  const stop = observeTransport(() => { throw new Error("disk failed"); });
  try { assert.doesNotThrow(() => failRequest()); } finally { stop(); }
});

test("extension flushes its private log on shutdown and survives a write failure", async () => {
  // homedir() follows HOME on this Node runtime; use disposable state even outside the wrapper.
  const previousHome = process.env.HOME;
  const home = await mkdtemp(join(tmpdir(), "pi-transport-test-"));
  process.env.HOME = home;
  const hooks = new Map();
  const pi = { on: (name, handler) => hooks.set(name, handler), registerCommand: () => {} };
  try {
    transportDiagnostics(pi);
    hooks.get("session_start")({}, { sessionManager: { getSessionId: () => "fixture-session" },
      modelRegistry: { getProvider: () => undefined } });
    failRequest();
    await hooks.get("session_shutdown")();
    const directory = join(home, ".pi/agent/logs");
    const files = await readdir(directory);
    assert.equal(files.length, 1);
    assert.equal((await stat(directory)).mode & 0o777, 0o700);
    assert.equal((await stat(join(directory, files[0]))).mode & 0o777, 0o600);
    const record = JSON.parse(await readFile(join(directory, files[0]), "utf8"));
    assert.equal(record.sessionId, "fixture-session");
    await rm(directory, { recursive: true });
    await writeFile(directory, "blocks directory creation");
    transportDiagnostics(pi);
    failRequest();
    // A failed writer must not reject shutdown or the next request.
    await hooks.get("session_shutdown")();
  } finally {
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    await rm(home, { recursive: true, force: true });
  }
});

test("native provider distinguishes successful reader cleanup, remote failure, and explicit abort", async () => {
  const original = await installedProvider();
  const records = [];
  const stop = observeTransport(record => { if (record.type === "http_attempt") records.push(record); });
  const provider = instrumentProvider(original, record => records.push(record));
  assert.equal(provider.auth, original.auth);
  assert.equal(provider.getModels, original.getModels);
  let mode = "complete";
  const server = createServer((_request, response) => {
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write('data: {"type":"response.created","response":{"id":"resp_fixture"}}\n\n');
    if (mode === "complete") {
      // Leave HTTP open: the real Pi parser must cancel it after the terminal SSE event.
      response.write('data: {"type":"response.completed","response":{"id":"resp_fixture","status":"completed","output":[],"usage":{"input_tokens":1,"output_tokens":0,"total_tokens":1}}}\n\n');
    } else if (mode === "drop") {
      setTimeout(() => response.socket.destroy(), 20);
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const model = { ...original.getModels()[0], baseUrl: `http://127.0.0.1:${server.address().port}` };
  const token = `fixture.${Buffer.from(JSON.stringify({ "https://api.openai.com/auth": {
    chatgpt_account_id: "fixture-account",
  } })).toString("base64url")}.fixture`;
  try {
    for (const scenario of ["complete", "drop", "abort"]) {
      mode = scenario;
      const controller = new AbortController();
      let seenEvents = 0;
      const stream = provider.streamSimple(model, { messages: [] }, {
        apiKey: token, transport: "sse", signal: controller.signal, maxRetries: 0,
        onProviderStreamEvent: () => {
          seenEvents++;
          if (scenario === "abort") controller.abort();
        },
      });
      const result = await stream.result();
      await new Promise(resolve => setImmediate(resolve));
      const record = records.at(-1);
      assert.ok(seenEvents > 0, "existing callbacks must still run");
      assert.equal(records.length, ["complete", "drop", "abort"].indexOf(scenario) + 1);
      assert.equal(record.responseId, "resp_fixture");
      assert.equal(record.model, model.id);
      assert.equal(record.provider, "openai-codex");
      assert.equal(record.addressFamily, 4);
      assert.ok(record.chunkCount > 0);
      assert.ok(record.receivedBodyBytes > 0);
      assert.equal(record.signalAborted, scenario === "abort");
      assert.equal(record.callStopReason, result.stopReason);
      if (scenario === "complete") {
        assert.equal(result.stopReason, "stop");
        assert.equal(record.transportOutcome, "reader_cleanup");
        assert.equal(record.terminalEventType, "response.completed");
      } else {
        assert.equal(result.stopReason, scenario === "abort" ? "aborted" : "error");
        assert.equal(record.transportOutcome, "error");
        assert.equal(record.terminalEventType, null);
        assert.equal(record.lastEventType, "response.created");
      }
    }
    assert.doesNotMatch(JSON.stringify(records), /fixture-account|apiKey|encrypted_content/);
  } finally {
    stop(); server.closeAllConnections(); server.close();
    await once(server, "close");
  }
});

test("network probe reports stalled TLS separately from DNS/TCP success", async () => {
  const sockets = new Set();
  const server = createTcpServer(socket => { sockets.add(socket); socket.on("close", () => sockets.delete(socket)); });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const results = await probeNetwork("127.0.0.1", server.address().port, 20);
    assert.equal(results[0].outcome, "timeout");
    assert.equal(typeof results[0].tcpMs, "number");
    assert.equal(results[1].outcome, "no_address");
  } finally {
    for (const socket of sockets) socket.destroy();
    server.close(); await once(server, "close");
  }
});

test("concurrent native provider calls retain separate retry, response, and callback metadata", async () => {
  const records = [];
  const stop = observeTransport(record => { if (record.type === "http_attempt") records.push(record); });
  const provider = instrumentProvider(await installedProvider(), record => records.push(record));
  const calls = new Map();
  const server = createServer((request, response) => {
    const call = request.headers["x-test-call"];
    const count = (calls.get(call) ?? 0) + 1;
    calls.set(call, count);
    if (count === 1) {
      response.writeHead(503, { "Content-Type": "application/json", "retry-after-ms": "0" });
      response.end('{"error":{"message":"server overloaded"}}');
      return;
    }
    response.writeHead(200, { "Content-Type": "text/event-stream", "x-request-id": `request_${call}` });
    response.end(`data: {"type":"response.completed","response":{"id":"resp_${call}","status":"completed","output":[],"usage":{"input_tokens":1,"output_tokens":0,"total_tokens":1}}}\n\n`);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const model = { ...provider.getModels()[0], baseUrl: `http://127.0.0.1:${server.address().port}` };
  const token = `fixture.${Buffer.from(JSON.stringify({ "https://api.openai.com/auth": {
    chatgpt_account_id: "fixture-account",
  } })).toString("base64url")}.fixture`;
  let fetchCalls = 0;
  try {
    await Promise.all(["a", "b"].map(async call => {
      const stream = provider.streamSimple(model, { messages: [] }, {
        apiKey: token, transport: "sse", maxRetries: 1, headers: { "x-test-call": call },
        fetch: (...args) => { fetchCalls++; return fetch(...args); },
      });
      assert.equal((await stream.result()).stopReason, "stop");
    }));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(fetchCalls, 4, "the caller's fetch implementation is preserved through retries");
    assert.equal(records.length, 4);
    const reused = records.find(record => record.observedRequestsOnSocket > 1);
    assert.ok(reused, "the keep-alive fixture must exercise observed socket reuse");
    assert.ok(records.some(record => record.socketId === reused.socketId && record.observedRequestsOnSocket === 1));
    const groups = Map.groupBy(records, record => record.operationId);
    assert.equal(groups.size, 2);
    for (const attempts of groups.values()) {
      assert.deepEqual(attempts.map(record => record.attempt), [1, 2]);
      assert.deepEqual(attempts.map(record => record.status), [503, 200]);
      assert.equal(attempts[0].responseId, null, "the failed attempt must not acquire its retry's response ID");
      assert.equal(attempts[0].terminalEventType, null);
      assert.equal(attempts[1].terminalEventType, "response.completed");
      assert.equal(attempts[1].transportOutcome, "http_complete");
      assert.equal(attempts[1].responseId.replace("resp_", "request_"), attempts[1].requestId);
    }
  } finally {
    stop(); server.closeAllConnections(); server.close(); await once(server, "close");
  }
});

test("real Pi session reload restores and re-decorates the resolved provider", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-transport-reload-"));
  const packageDir = await realpath(process.env.PI_PACKAGE_DIR);
  const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
  const { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } =
    await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
  const { InMemoryCredentialStore } = await installedAiModule();
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(directory, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
  const original = modelRuntime.getProvider("openai-codex");
  const extension = fileURLToPath(new URL("../../config/pi-agent/pi-extensions/transport-diagnostics.ts", import.meta.url));
  const entrypoint = join(directory, "extension.ts");
  await writeFile(entrypoint, `export { default } from ${JSON.stringify(extension)};\n`);
  const loader = new DefaultResourceLoader({ cwd: directory, agentDir: directory, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [entrypoint] });
  await loader.reload();
  const { session } = await createAgentSession({ cwd: directory, agentDir: directory,
    resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: SessionManager.inMemory(directory), model: original.getModels()[0], tools: [] });
  const errors = [];
  try {
    await session.bindExtensions({ onError: error => errors.push(error) });
    const first = modelRuntime.getProvider("openai-codex");
    assert.notEqual(first.streamSimple, original.streamSimple);
    await session.reload();
    const second = modelRuntime.getProvider("openai-codex");
    assert.notEqual(second.streamSimple, first.streamSimple);
    assert.equal(second.auth, original.auth);
    // Shutdown restoration also covers removing this extension on the next reload.
    await writeFile(entrypoint, "export default function () {}\n");
    await session.reload();
    assert.equal(modelRuntime.getProvider("openai-codex").streamSimple, original.streamSimple);
    assert.deepEqual(errors, []);
  } finally { session.dispose(); await rm(directory, { recursive: true, force: true }); }
});

test("TCP parser accepts IPv4/IPv6 endpoints and retains only numeric diagnostic fields", () => {
  const samples = parseTcpSamples("ESTAB 0 13 127.0.0.1:1234 127.0.0.1:443 rtt:1.2/0.3 retrans:0/2 bytes_retrans:120 private:secret\n"
    + "CLOSE-WAIT 1 0 [::1]:1235 [::1]:443 rto:200 cwnd:10 unacked:1");
  assert.equal(samples.length, 2);
  assert.deepEqual(samples[0].stats.rtt, [1.2, 0.3]);
  assert.deepEqual(samples[0].stats.retrans, [0, 2]);
  assert.equal(samples[1].remote.address, "::1");
  assert.doesNotMatch(JSON.stringify(samples), /secret|private/);
});

test("live TCP counters and socket closure correlate with an induced event-loop stall", async () => {
  const records = [];
  const stop = observeTransport(record => records.push(record));
  let reset = false;
  const server = createServer((_request, response) => {
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write("data: incomplete\n\n");
    const socket = response.socket;
    if (reset) setTimeout(() => socket.resetAndDestroy(), 20);
    else setTimeout(() => socket.end(), 1300);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/codex/responses`);
    const reader = response.body.getReader();
    await reader.read();
    await new Promise(resolve => setTimeout(resolve, 30));
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 150);
    await assert.rejects(reader.read());
    await new Promise(resolve => setImmediate(resolve));
    const attempt = records.find(record => record.type === "http_attempt");
    assert.ok(attempt.eventLoop.maxDelayMs >= 100);
    assert.ok(attempt.eventLoop.lastChunkGapMaxDelayMs >= 100);
    assert.ok(attempt.eventLoop.stallCount >= 1);
    assert.ok(attempt.eventLoop.utilization.active >= 100);
    const tcp = records.find(record => record.type === "tcp_sample" && record.attemptId === attempt.attemptId);
    if (process.platform === "linux") {
      assert.ok(tcp, "ss must observe the real connection, not a synthetic sample");
      assert.equal(tcp.socketId, attempt.socketId);
      assert.equal(tcp.local.port, attempt.socket.localPort);
      assert.equal(tcp.remote.port, server.address().port);
      assert.ok(tcp.stats.rtt, "kernel TCP_INFO must include RTT");
    }
    assert.ok(records.some(record => record.type === "socket_event" && record.socketId === attempt.socketId && record.event === "end"));

    reset = true;
    const second = await fetch(`http://127.0.0.1:${server.address().port}/codex/responses`);
    await assert.rejects(second.text());
    await new Promise(resolve => setImmediate(resolve));
    const failure = records.filter(record => record.type === "http_attempt").at(-1);
    assert.ok(records.some(record => record.type === "socket_event" && record.socketId === failure.socketId
      && record.event === "error" && record.errors.some(error => error.code === "ECONNRESET")));
    assert.doesNotMatch(JSON.stringify(records), /incomplete/);
  } finally {
    stop(); server.closeAllConnections(); server.close(); await once(server, "close");
  }
});

test("missing ss reports unavailable TCP sampling without failing the HTTP request", async () => {
  if (process.platform !== "linux") return;
  const records = [];
  const stop = observeTransport(record => records.push(record));
  const directory = await mkdtemp(join(tmpdir(), "pi-no-ss-"));
  const previousPath = process.env.PATH;
  const server = createServer((_request, response) => {
    response.write("first chunk");
    setTimeout(() => response.end("last chunk"), 1200);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    process.env.PATH = directory;
    const response = await fetch(`http://127.0.0.1:${server.address().port}/codex/responses`);
    assert.equal(await response.text(), "first chunklast chunk");
    const status = records.filter(record => record.type === "tcp_sampling_status");
    assert.equal(status.length, 1);
    assert.equal(status[0].reason, "ss_missing");
    assert.equal(records.find(record => record.type === "http_attempt").transportOutcome, "http_complete");
    assert.doesNotMatch(JSON.stringify(records), /first chunk|last chunk/);
  } finally {
    if (previousPath === undefined) delete process.env.PATH;
    else process.env.PATH = previousPath;
    stop(); server.closeAllConnections(); server.close(); await once(server, "close");
    await rm(directory, { recursive: true, force: true });
  }
});
