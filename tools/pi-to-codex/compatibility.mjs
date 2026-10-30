import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { once } from "node:events";
import { mkdir, mkdtemp, open, readFile, rename, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { isDeepStrictEqual, promisify } from "node:util";
import { CodexClient, importSession, loadPiPackage } from "./importer.mjs";

const execute = promisify(execFile);
const sample = {
  user: "PI_COMPATIBILITY_USER", assistant: "PI_COMPATIBILITY_ASSISTANT",
  callId: "pi_compatibility_call", tool: "read", arguments: { path: "PI_COMPATIBILITY_ARGUMENT" },
  output: "PI_COMPATIBILITY_RESULT", continuation: "PI_COMPATIBILITY_CONTINUE",
};

export async function piBuildIdentity({ sdk, manifest, installedDirectory, directory }) {
  // These are the installer's recorded successful build, not the live checkout's
  // HEAD. Preserve lexical node_modules placement before following its symlink.
  const candidates = [...new Set([installedDirectory, directory].flatMap(path => [
    resolve(path, "../../../.source-revision"),
    resolve(path, "../../../node/.source-revision"),
    resolve(path, "../../../REVISION"),
  ]))];
  for (const path of candidates) {
    let revision;
    try { revision = (await readFile(path, "utf8")).trim(); }
    catch (error) {
      if (error.code === "ENOENT") continue;
      return null;
    }
    if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(revision)) return null;
    return { version: manifest.version, sdkVersion: sdk.VERSION ?? manifest.version, revision };
  }
  return null;
}

async function isolatedEnvironment(env, root) {
  // Do not forward auth, provider selectors, hooks, proxies, or personal Codex
  // paths. PATH selects the same installed command; every writable home is private.
  const isolated = {};
  for (const key of ["PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "PATHEXT", "MISE_DATA_DIR"]) {
    if (env[key] !== undefined) isolated[key] = env[key];
  }
  for (const [key, relative] of Object.entries({ HOME: "home", CODEX_HOME: "codex", CODEX_SQLITE_HOME: "sqlite",
    XDG_CONFIG_HOME: "config", XDG_CACHE_HOME: "cache", XDG_DATA_HOME: "data", XDG_STATE_HOME: "state",
    XDG_RUNTIME_DIR: "run", TMPDIR: "tmp", PI_CODING_AGENT_DIR: "pi" })) {
    isolated[key] = join(root, relative);
    await mkdir(isolated[key], { recursive: true, mode: 0o700 });
  }
  return isolated;
}

function retainedContext(request) {
  assert.equal(request.model, "gpt-5.4", "compatibility request must use the local provider's model");
  const text = request.input.filter(item => item.type === "message")
    .flatMap(item => item.content.map(block => block.text).filter(value => value !== undefined));
  for (const expected of [sample.user, sample.assistant, sample.continuation]) {
    assert.equal(text.filter(value => value === expected).length, 1, `retained context occurrence: ${expected}`);
  }
  const calls = request.input.filter(item => item.type === "function_call");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].call_id, sample.callId);
  assert.equal(calls[0].name, sample.tool);
  assert.deepEqual(JSON.parse(calls[0].arguments), sample.arguments);
  const outputs = request.input.filter(item => item.type === "function_call_output");
  assert.equal(outputs.length, 1);
  assert.equal(outputs[0].call_id, sample.callId);
  assert.equal(outputs[0].output, sample.output);
}

function displayedContext(thread) {
  assert.ok(thread.turns.every(turn => turn.status === "completed"));
  const items = thread.turns.flatMap(turn => turn.items);
  assert.deepEqual(items.map(item => item.type), ["userMessage", "dynamicToolCall", "agentMessage"]);
  assert.deepEqual(items[0].content.map(block => block.text), [sample.user]);
  assert.equal(items[1].tool, sample.tool);
  assert.deepEqual(items[1].arguments, sample.arguments);
  assert.equal(items[1].success, true);
  assert.deepEqual(items[1].contentItems, [{ type: "inputText", text: sample.output }]);
  assert.equal(items[2].text, sample.assistant);
}

async function continueThread(client, id, signal) {
  let receive;
  let abort;
  const completed = new Promise((resolveTurn, rejectTurn) => {
    receive = line => {
      try {
        const message = JSON.parse(line);
        if (message.method === "turn/completed" && message.params?.threadId === id) resolveTurn(message.params.turn);
      } catch (error) { rejectTurn(error); }
    };
    abort = () => rejectTurn(signal.reason);
    client.lines.on("line", receive);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
  try {
    const exited = client.exited.then(() => { throw client.failure || new Error("Codex exited before its compatibility turn completed"); });
    const [, turn] = await Promise.all([
      client.request("turn/start", { threadId: id, input: [{ type: "text", text: sample.continuation }] }),
      Promise.race([completed, exited]),
    ]);
    assert.equal(turn.status, "completed", "local compatibility turn must complete");
  } finally {
    client.lines.off("line", receive);
    signal.removeEventListener("abort", abort);
  }
}

async function runProbe(root, env, sdk, signal) {
  const requests = [];
  const server = createServer(async (request, response) => {
    try {
      assert.equal(request.url, "/v1/responses");
      assert.equal(request.method, "POST");
      assert.ok(!request.headers["content-encoding"], "compatibility requests must not be compressed");
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      requests.push(JSON.parse(Buffer.concat(chunks)));
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      const item = { id: "msg_compatibility", type: "message", role: "assistant", status: "completed",
        content: [{ type: "output_text", text: "Compatibility confirmed.", annotations: [] }] };
      response.write(`event: response.output_item.done\ndata: ${JSON.stringify({ type: "response.output_item.done", output_index: 0, item })}\n\n`);
      response.end(`event: response.completed\ndata: ${JSON.stringify({ type: "response.completed", response: {
        id: "resp_compatibility", status: "completed", output: [item], usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
      } })}\n\n`);
    } catch (error) {
      requests.push({ error: error.message });
      response.writeHead(500);
      response.end("Invalid compatibility request");
    }
  });
  let failure;
  try {
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const profile = `model = "gpt-5.4"
model_provider = "pi_compatibility"
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
[features]
plugins = false
apps = false
enable_request_compression = false
[model_providers.pi_compatibility]
name = "Local Pi import compatibility check"
base_url = "http://127.0.0.1:${server.address().port}/v1"
wire_api = "responses"
requires_openai_auth = false
`;
    await writeFile(join(env.CODEX_HOME, "config.toml"), profile);
    await writeFile(join(env.CODEX_HOME, "dotfiles.config.toml"), profile);
    const manager = sdk.SessionManager.create(root, join(root, "pi-sessions"));
    manager.appendMessage({ role: "user", content: sample.user, timestamp: 1 });
    const assistant = content => ({ role: "assistant", content, api: "openai-responses", provider: "openai",
      model: "source-model", usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: 2 });
    manager.appendMessage(assistant([{ type: "toolCall", id: sample.callId, name: sample.tool, arguments: sample.arguments }]));
    manager.appendMessage({ role: "toolResult", toolCallId: sample.callId, toolName: sample.tool,
      content: [{ type: "text", text: sample.output }], isError: false, timestamp: 3 });
    manager.appendMessage(assistant([{ type: "text", text: sample.assistant }]));
    const source = manager.getSessionFile();
    const original = await readFile(source);
    const imported = await importSession(source, { env, signal, childCwd: root, report: () => {} });
    assert.equal(requests.length, 0, "importing must not make a provider request");
    const client = new CodexClient({ env, signal, cwd: root });
    let clientFailure;
    try {
      await client.initialize();
      displayedContext((await client.request("thread/read", { threadId: imported.id, includeTurns: true })).thread);
      await client.request("thread/resume", { threadId: imported.id, excludeTurns: true });
      await continueThread(client, imported.id, signal);
      assert.equal(requests.length, 1, "only one local continuation request is expected");
      retainedContext(requests[0]);
      assert.deepEqual(await readFile(source), original, "compatibility import must preserve its Pi source");
    } catch (error) { clientFailure = error; throw error; }
    finally {
      try { await client.close(); }
      catch (error) {
        if (clientFailure) clientFailure.message += `; client cleanup: ${error.message}`;
        else throw error;
      }
    }
  } catch (error) { failure = error; throw error; }
  finally {
    if (server.listening) {
      try {
        server.closeAllConnections();
        await new Promise((resolveClose, rejectClose) => server.close(error => error ? rejectClose(error) : resolveClose()));
      } catch (error) {
        if (failure) failure.message += `; provider cleanup: ${error.message}`;
        else throw error;
      }
    }
  }
}

async function writeReceipt(path, identity, signal) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    const file = await open(temporary, "wx", 0o600);
    try { await file.writeFile(JSON.stringify(identity) + "\n"); await file.sync(); }
    finally { await file.close(); }
    signal?.throwIfAborted();
    await rename(temporary, path);
  } finally { await rm(temporary, { force: true }); }
}

// Check installed-build compatibility before CLI publication. A hit starts only
// codex --version; a miss owns its private homes, local provider and clients until
// cleanup completes. No-provenance SDK overrides are checked without caching.
export async function checkCompatibility({ env = process.env, signal, report = console.error } = {}) {
  const installed = await loadPiPackage(env);
  const pi = await piBuildIdentity(installed);
  const cache = join(env.XDG_CACHE_HOME || join(env.HOME || homedir(), ".cache"), "pi-to-codex", "compatibility.json");
  const root = await mkdtemp(join(tmpdir(), "pi-to-codex-check-"));
  let identity;
  let cached = false;
  let failure;
  try {
    const isolated = await isolatedEnvironment(env, root);
    // Even --version may traverse a personal CLI wrapper. Give it private homes
    // too, so a cache miss/failure cannot mutate the destination's Codex state.
    const { stdout } = await execute("codex", ["--version"], { env: isolated, cwd: root, signal, timeout: 10000 });
    const codex = stdout.trim();
    if (!codex) throw new Error("Codex returned an empty version string");
    identity = { format: 1, codex, pi };
    if (pi) {
      try { cached = isDeepStrictEqual(JSON.parse(await readFile(cache, "utf8")), identity); }
      catch (error) { if (error.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error; }
    }
    if (!cached) {
      report(`Checking Pi/Codex compatibility in disposable storage (${codex})...`);
      if (!pi) report("Pi has no usable recorded build revision; this check will not be cached.");
      isolated.PI_PACKAGE_DIR = installed.directory;
      const timeout = new AbortController();
      const timer = setTimeout(() => timeout.abort(new Error("compatibility check timed out after 30 seconds")), 30000);
      const bounded = AbortSignal.any([...(signal ? [signal] : []), timeout.signal]);
      try { await runProbe(root, isolated, installed.sdk, bounded); bounded.throwIfAborted(); }
      finally { clearTimeout(timer); }
    }
  } catch (error) {
    failure = error;
    error.message = `compatibility preflight failed in disposable storage; destination import was not started: ${error.message}`;
    throw error;
  } finally {
    try { await rm(root, { recursive: true, force: true }); }
    catch (error) {
      if (failure) failure.message += `; compatibility storage cleanup: ${error.message}`;
      else throw error;
    }
  }
  signal?.throwIfAborted();
  // A receipt certifies the entire check, including all process/server/storage
  // cleanup. Failed checks leave any older successful receipt untouched.
  if (!cached && pi) await writeReceipt(cache, identity, signal);
}
