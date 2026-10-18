import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, realpathSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { CodexClient, convertMessages, loadPi, readSession } from "../pi-to-codex.mjs";

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, "../../..");
const command = join(root, "bin/pi-to-codex");
const sdk = await loadPi();
const execute = promisify(execFile);
const usage = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const user = text => ({ role: "user", content: text, timestamp: 1 });
const assistant = content => ({ role: "assistant", content, api: "anthropic-messages", provider: "anthropic",
  model: "source-model", usage, stopReason: "stop", timestamp: 2 });
const call = (id, args = {}) => ({ type: "toolCall", id, name: "read", arguments: args });
const result = (id, text, isError = false) => ({ role: "toolResult", toolCallId: id, toolName: "read",
  content: [{ type: "text", text }], isError, timestamp: 3 });

async function fixture(t, native = false) {
  const dir = await mkdtemp(join(tmpdir(), "pi-to-codex-test-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const home = join(dir, "codex");
  const bin = join(dir, "bin");
  const temp = join(dir, "temporary");
  await Promise.all([mkdir(home), mkdir(bin), mkdir(temp)]);
  if (native) {
    await symlink(native, join(bin, "codex"));
  } else await symlink(join(directory, "fixtures/codex.mjs"), join(bin, "codex"));
  const manager = sdk.SessionManager.create(dir, join(dir, "pi-sessions"));
  manager.appendMessage(user("ORIGINAL_USER"));
  manager.appendMessage(assistant([{ type: "text", text: "ORIGINAL_ASSISTANT" }]));
  const source = manager.getSessionFile();
  return { dir, home, temp, source, manager,
    env: { ...process.env, HOME: dir, CODEX_HOME: home, TMPDIR: temp, PATH: `${bin}:${process.env.PATH}` } };
}

function launch(f, args = [f.source], extra = {}) {
  const child = spawn(process.execPath, [command, ...args], { env: { ...f.env, ...extra }, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", bytes => { stdout += bytes; });
  child.stderr.on("data", bytes => { stderr += bytes; });
  const done = once(child, "close").then(([code, signal]) => ({ code, signal, stdout, stderr }));
  return { child, done };
}

async function readLines(path) {
  return (await readFile(path, "utf8")).trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
}

async function noChildren(f) {
  const pids = await readLines(join(f.home, "fixture-pids.jsonl"));
  for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
  assert.deepEqual(await readdir(f.temp), []);
}

test("conversion preserves occurrences, JSON arguments, parallel result identity, and failures", () => {
  // Seeded bounded cases cover nested JSON and varying result order, without a new dependency.
  let seed = 519;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed; };
  const values = [null, false, 0, -42, 1.25, "quote\" slash\\ newline\n λ", [], {}, { nested: [true, null, "雪"] }];
  const lengths = new Set();
  const orders = new Set();
  for (let sample = 0; sample < 90; sample++) {
    const size = sample % 4 + 1;
    lengths.add(size);
    const calls = Array.from({ length: size }, (_, index) => call(`call_${index}`, { value: values[(sample + index) % values.length] }));
    const order = calls.slice();
    for (let index = order.length - 1; index > 0; index--) {
      const other = random() % (index + 1);
      [order[index], order[other]] = [order[other], order[index]];
    }
    orders.add(order.map(item => item.id).join(","));
    const messages = [user("same"), user("same"), assistant(calls),
      ...order.map(item => result(item.id, `output:${item.id}`, item.id === "call_0"))];
    const converted = convertMessages(messages).history;
    assert.deepEqual(converted.slice(0, 2).map(item => item.content[0].text), ["same", "same"], `sample ${sample}`);
    const importedCalls = converted.filter(item => item.type === "function_call");
    assert.deepEqual(importedCalls.map(item => JSON.parse(item.arguments)), calls.map(item => item.arguments));
    assert.deepEqual(importedCalls.map(item => item.call_id), calls.map(item => item.id));
    const outputs = converted.filter(item => item.type === "function_call_output");
    assert.deepEqual(outputs.map(item => item.call_id), order.map(item => item.id));
    for (const output of outputs) {
      if (output.call_id === "call_0") assert.deepEqual(JSON.parse(output.output), { isError: true, content: "output:call_0" });
      else assert.equal(output.output, `output:${output.call_id}`);
    }
  }
  assert.deepEqual([...lengths], [1, 2, 3, 4]);
  assert.ok(orders.size > 4, "result-order permutations executed");
});

test("unsupported content and broken call/result relationships are rejected", () => {
  const cases = [
    [user([{ type: "image", data: "abc", mimeType: "image/png" }])],
    [user("x"), assistant([call("a")])],
    [user("x"), result("orphan", "x")],
    [user("x"), assistant([call("a"), call("a")]), result("a", "x")],
    [user("x"), assistant([call("a")]), result("a", "x"), result("a", "again")],
    [user("x"), assistant([call("a")]), { ...result("a", "x"), toolName: "bash" }],
    [user("x"), { role: "unknown", content: "unsupported" }],
    [assistant([{ type: "text", text: "no user" }])],
  ];
  for (const messages of cases) assert.throws(() => convertMessages(messages));
  const converted = convertMessages([user("u"), assistant([{ type: "thinking", thinking: "private", signature: "opaque" },
    { type: "text", text: "before" }, call("a"), { type: "text", text: "after" }]), result("a", "done")]);
  assert.equal(converted.omittedReasoning, 1);
  assert.deepEqual(converted.history.map(item => item.type), ["message", "message", "function_call", "message", "function_call_output"]);
  assert.ok(!JSON.stringify(converted.history).includes("private"));
  const system = convertMessages([{ role: "system", content: "PI_SYSTEM" }, user("kept"),
    { role: "system", content: null, sections: { instructions: "PI_SECTIONS" } }]);
  assert.equal(system.omittedSystem, 2);
  assert.deepEqual(system.history, convertMessages([user("kept")]).history);
});

test("provider-length call IDs retain identity without colliding with later source IDs", () => {
  const ids = ["x".repeat(64), "x".repeat(65), "x".repeat(83), "pi_import_1", "pi_import_2"];
  const converted = convertMessages([user("u"), assistant(ids.map(id => call(id))),
    ...ids.slice().reverse().map(id => result(id, `output:${id}`))]).history;
  const calls = converted.filter(item => item.type === "function_call");
  const outputs = converted.filter(item => item.type === "function_call_output");
  assert.ok(calls.every(item => item.call_id.length <= 64));
  assert.equal(new Set(calls.map(item => item.call_id)).size, ids.length);
  assert.equal(calls[0].call_id, ids[0]);
  assert.equal(calls[3].call_id, ids[3]);
  assert.equal(calls[4].call_id, ids[4]);
  assert.deepEqual(outputs.map(item => item.call_id), calls.map(item => item.call_id).reverse());
  assert.deepEqual(outputs.map(item => item.output), ids.slice().reverse().map(id => `output:${id}`));
});

test("public command imports before publication, adds one visibility event, and verifies paginated index", async t => {
  const f = await fixture(t);
  const original = await readFile(f.source);
  const outcome = await launch(f).done;
  assert.equal(outcome.code, 0, JSON.stringify(outcome));
  assert.match(outcome.stdout, /Imported \d+ history items into Codex thread [0-9a-f-]+/);
  assert.match(outcome.stdout, /Resume with: codex resume '/);
  const requests = await readLines(join(f.home, "fixture-requests.jsonl"));
  assert.equal(requests.filter(item => item.method === "thread/resume" && item.params.history).length, 1);
  assert.equal(requests.filter(item => item.method === "thread/resume" && !item.params.history).length, 1);
  assert.equal(requests.filter(item => item.method === "thread/list").length, 2);
  assert.ok(requests.filter(item => item.method === "thread/list").every(item => item.params.useStateDbOnly));
  const records = await readLines(join(f.home, "owned-rollout.jsonl"));
  assert.deepEqual(records.filter(item => item.type === "event_msg" && item.payload.type === "user_message")
    .map(item => item.payload.message), ["ORIGINAL_USER"]);
  assert.equal(records.filter(item => item.type === "event_msg" && item.payload.type === "item_completed").length, 2);
  assert.equal(requests.filter(item => item.method === "thread/read").length, 1);
  assert.equal(records.at(-1).ordinal, records.length - 1);
  assert.deepEqual(await readFile(f.source), original);
  await noChildren(f);
});

test("public command resolves exact session IDs with Pi discovery and rejects missing or ambiguous IDs", async t => {
  const f = await fixture(t);
  const agent = join(f.dir, "agent");
  const sessions = join(agent, "sessions");
  await mkdir(sessions, { recursive: true });
  await symlink(join(f.dir, "pi-sessions"), join(sessions, "project"));
  const env = { PI_CODING_AGENT_DIR: agent };
  const id = f.manager.getSessionId();
  const original = await readFile(f.source);
  const missing = await launch(f, ["00000000-0000-0000-0000-000000000000"], env).done;
  assert.equal(missing.code, 1);
  assert.match(missing.stderr, /Pi session ID not found/);
  assert.ok(!existsSync(join(f.home, "fixture-pids.jsonl")));
  const success = await launch(f, [id], env).done;
  assert.equal(success.code, 0, JSON.stringify(success));
  assert.ok(success.stderr.includes(join(sessions, "project", f.source.split("/").at(-1))));
  assert.deepEqual(await readFile(f.source), original);
  await noChildren(f);

  await symlink(join(f.dir, "pi-sessions"), join(sessions, "duplicate"));
  const ambiguous = await launch(f, [id], env).done;
  assert.equal(ambiguous.code, 1);
  assert.match(ambiguous.stderr, /matches multiple files; pass a path/);
  // An explicit existing path remains usable even when discovery is ambiguous.
  const path = join(f.dir, id);
  await symlink(f.source, path);
  const explicit = await launch(f, [path], env).done;
  assert.equal(explicit.code, 0, JSON.stringify(explicit));
  await noChildren(f);
});

test("input rejection and unavailable cwd happen before creating a Codex process", async t => {
  const f = await fixture(t);
  const original = await readFile(f.source);
  for (const tail of ["{truncated", '\n{"type":"message","id":"image","parentId":null,"message":{"role":"user","content":[{"type":"image","data":"abc","mimeType":"image/png"}]}}\n']) {
    await writeFile(f.source, Buffer.concat([original, Buffer.from(tail)]));
    const before = await readFile(f.source);
    const outcome = await launch(f).done;
    assert.equal(outcome.code, 1);
    assert.ok(!existsSync(join(f.home, "fixture-pids.jsonl")));
    assert.deepEqual(await readFile(f.source), before);
    assert.deepEqual(await readdir(f.temp), []);
  }
  await writeFile(f.source, original);
  const missing = await launch(f, [f.source, "--cwd", join(f.dir, "missing")]).done;
  assert.equal(missing.code, 1);
  assert.ok(!existsSync(join(f.home, "fixture-pids.jsonl")));
});

test("legacy sessions migrate only in the private snapshot", async t => {
  const f = await fixture(t);
  const entries = [
    { type: "session", id: "legacy", version: 1, timestamp: new Date().toISOString(), cwd: f.dir },
    { type: "message", message: user("LEGACY_USER"), timestamp: new Date().toISOString() },
    { type: "message", message: assistant([{ type: "text", text: "legacy reply" }]), timestamp: new Date().toISOString() },
  ];
  await writeFile(f.source, entries.map(item => JSON.stringify(item) + "\n").join(""));
  const before = await readFile(f.source);
  const converted = await readSession(f.source);
  assert.equal(converted.visibility, "LEGACY_USER");
  assert.deepEqual(await readFile(f.source), before);
});

test("protocol failures preserve source, report partial publication, and reap children", async t => {
  for (const mode of ["reject", "eof", "malformed", "bad-rollout", "reopen-error", "missing-display"]) {
    const f = await fixture(t);
    const original = await readFile(f.source);
    const outcome = await launch(f, undefined, { PI_IMPORT_FIXTURE_MODE: mode }).done;
    assert.equal(outcome.code, 1, `${mode}: ${outcome.stderr}`);
    assert.equal(outcome.stdout, "");
    assert.match(outcome.stderr, /pi-to-codex:/);
    assert.match(outcome.stderr, /inspect .*before retrying/);
    if (["bad-rollout", "reopen-error", "missing-display"].includes(mode)) assert.match(outcome.stderr, /thread [0-9a-f-]+ may be partially imported/);
    const requests = await readLines(join(f.home, "fixture-requests.jsonl"));
    assert.equal(requests.filter(item => item.method === "thread/resume" && item.params.history).length, 1);
    assert.deepEqual(await readFile(f.source), original);
    await noChildren(f);
  }
});

test("SIGINT cancels a waiting import and cleans up its owned process", async t => {
  const f = await fixture(t);
  const launched = launch(f, undefined, { PI_IMPORT_FIXTURE_MODE: "stall" });
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const log = join(f.home, "fixture-requests.jsonl");
    if (existsSync(log) && (await readLines(log)).some(item => item.method === "thread/resume")) break;
    await new Promise(resolveWait => setTimeout(resolveWait, 20));
  }
  launched.child.kill("SIGINT");
  const outcome = await launched.done;
  assert.equal(outcome.code, 130, outcome.stderr);
  assert.match(outcome.stderr, /cancelled by SIGINT/);
  await noChildren(f);
});

function nativeCodex() {
  if (process.env.DOTFILES_TEST_CODEX_REAL) return process.env.DOTFILES_TEST_CODEX_REAL;
  const wrapper = join(root, "bin/codex");
  for (const entry of process.env.PATH.split(":")) {
    const candidate = join(entry, "codex");
    if (existsSync(candidate) && realpathSync(candidate) !== wrapper) return realpathSync(candidate);
  }
}

test("real Codex terminal UI displays imported messages", { timeout: 20000 }, async t => {
  const native = nativeCodex();
  const tmux = ["/usr/bin/tmux", "/opt/homebrew/bin/tmux"].find(path => existsSync(path));
  if (!native || !tmux) { t.skip("native Codex and tmux are required for the terminal UI check"); return; }
  const f = await fixture(t, native);
  await writeFile(join(f.home, "config.toml"), `model = "gpt-5.4"
model_provider = "fixture"
[model_providers.fixture]
name = "fixture"
base_url = "http://127.0.0.1:1/v1"
wire_api = "responses"
requires_openai_auth = false
[projects."${f.dir}"]
trust_level = "trusted"
`);
  const imported = await launch(f).done;
  assert.equal(imported.code, 0, imported.stderr);
  const id = imported.stdout.match(/Codex thread ([0-9a-f-]+)/)?.[1];
  assert.ok(id, imported.stdout);
  const socket = join(f.dir, "tmux.sock");
  const terminal = (...args) => execute(tmux, ["-S", socket, ...args], {
    env: { ...f.env, TERM: "xterm-256color", TMUX: "" },
  });
  try {
    await terminal("-f", "/dev/null", "new-session", "-d", "-s", "probe", "-x", "120", "-y", "40",
      native, "resume", id, "--no-alt-screen", "--no-daemon", "-C", f.dir);
    let screen = "";
    for (let attempt = 0; attempt < 40; attempt++) {
      await new Promise(resolveWait => setTimeout(resolveWait, 250));
      screen = (await terminal("capture-pane", "-p", "-S", "-100", "-t", "probe")).stdout;
      if (screen.includes("ORIGINAL_ASSISTANT")) break;
    }
    assert.match(screen, /ORIGINAL_USER/);
    assert.match(screen, /ORIGINAL_ASSISTANT/);
  } finally {
    await terminal("kill-server");
  }
});

test("real Codex retains selected compacted context and visible history without an import-time model request", { timeout: 45000 }, async t => {
  const native = nativeCodex();
  if (!native) { t.skip("native Codex is not installed"); return; }
  const f = await fixture(t, native);
  const sm = f.manager;
  const kept = sm.appendMessage(user("KEPT_USER"));
  sm.appendMessage(assistant([{ type: "text", text: "same" }]));
  sm.appendMessage(assistant([{ type: "text", text: "same" }]));
  const selected = sm.getLeafId();
  sm.appendMessage(user("ABANDONED_BRANCH"));
  sm.appendMessage(assistant([{ type: "text", text: "ABANDONED_REPLY" }]));
  sm.branchWithSummary(selected, "BRANCH_SUMMARY");
  sm.appendCompaction("OLDER_SUMMARY", kept, 200);
  const longCallId = "a".repeat(83);
  sm.appendMessage(assistant([call(longCallId, { path: "unicode 雪\\quote\"" }), call("b", { nested: [true, null] })]));
  sm.appendMessage(result("b", "B_RESULT"));
  sm.appendMessage(result(longCallId, "A_FAILED", true));
  sm.appendCompaction("CURRENT_SUMMARY", kept, 100);
  sm.appendMessage({ role: "system", content: "PI_SYSTEM_PROMPT", timestamp: 4 });
  sm.appendCustomMessageEntry("test-context", "CUSTOM_CONTEXT", true);
  const source = sm.getSessionFile();
  const original = await readFile(source);
  const expectedMessages = sdk.convertToLlm(sm.buildSessionContext().messages);
  const expectedText = expectedMessages.filter(item => item.role === "user" || item.role === "assistant")
    .flatMap(item => typeof item.content === "string" ? [item.content] : item.content.filter(block => block.type === "text").map(block => block.text));
  const requests = [];
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    assert.ok(!request.headers["content-encoding"], "request compression disabled in test config");
    requests.push(JSON.parse(Buffer.concat(chunks)));
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    const item = { id: "msg_fixture", type: "message", role: "assistant", status: "completed",
      content: [{ type: "output_text", text: "mock reply", annotations: [] }] };
    response.write(`event: response.output_item.done\ndata: ${JSON.stringify({ type: "response.output_item.done", output_index: 0, item })}\n\n`);
    response.end(`event: response.completed\ndata: ${JSON.stringify({ type: "response.completed", response: {
      id: "resp_fixture", status: "completed", output: [item], usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    } })}\n\n`);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise(resolveClose => server.close(resolveClose)));
  await writeFile(join(f.home, "config.toml"), `model = "gpt-5.4"
model_provider = "fixture"
approval_policy = "never"
sandbox_mode = "read-only"
[features]
enable_request_compression = false
[model_providers.fixture]
name = "fixture"
base_url = "http://127.0.0.1:${server.address().port}/v1"
wire_api = "responses"
requires_openai_auth = false
`);
  const active = new CodexClient({ command: native, env: f.env });
  t.after(() => active.close());
  await active.initialize();
  const live = await active.request("thread/start", { cwd: f.dir });
  await active.request("thread/inject_items", { threadId: live.thread.id,
    items: [{ type: "message", role: "user", content: [{ type: "input_text", text: "OTHER_LIVE_THREAD" }] }] });
  const imported = await launch(f, [source]).done;
  assert.equal(imported.code, 0, imported.stderr);
  assert.match(imported.stderr, /Omitting 1 Pi system message\(s\); using Codex instructions/);
  const id = imported.stdout.match(/Codex thread ([0-9a-f-]+)/)?.[1];
  assert.ok(id, imported.stdout);
  assert.equal(requests.length, 0, "import must not make a provider request");
  const listed = await active.request("thread/list", { modelProviders: [], useStateDbOnly: true });
  assert.ok(listed.data.some(thread => thread.id === id), "another process sees the imported thread in its index");
  const displayed = (await active.request("thread/read", { threadId: id, includeTurns: true })).thread.turns;
  assert.ok(displayed.length > 0, "imported history must have UI turns, not only model context");
  assert.ok(displayed.every(turn => turn.status === "completed"));
  const displayedItems = displayed.flatMap(turn => turn.items);
  const displayedText = displayedItems.flatMap(item => item.type === "userMessage"
    ? item.content.map(block => block.text) : item.type === "agentMessage" ? [item.text] : []);
  assert.deepEqual(displayedText, expectedText, "UI preserves selected text order and repeated occurrences");
  const displayedTools = displayedItems.filter(item => item.type === "dynamicToolCall");
  assert.equal(displayedTools.length, 2);
  assert.deepEqual(displayedTools.map(item => item.tool), ["read", "read"]);
  assert.deepEqual(displayedTools.map(item => item.arguments), [{ path: "unicode 雪\\quote\"" }, { nested: [true, null] }]);
  assert.deepEqual(displayedTools.map(item => item.success), [false, true]);
  assert.deepEqual(displayedTools.map(item => item.contentItems), [
    [{ type: "inputText", text: "A_FAILED" }], [{ type: "inputText", text: "B_RESULT" }],
  ]);
  assert.equal((await active.request("thread/read", { threadId: live.thread.id })).thread.id, live.thread.id);
  await active.request("thread/resume", { threadId: id, excludeTurns: true });
  const completed = new Promise((resolveTurn, rejectTurn) => {
    const timer = setTimeout(() => rejectTurn(new Error("mock turn did not complete")), 15000);
    const receive = line => {
      const notification = JSON.parse(line);
      if (notification.method === "turn/completed") {
        clearTimeout(timer);
        active.lines.off("line", receive);
        resolveTurn(notification.params.turn);
      }
    };
    active.lines.on("line", receive);
  });
  await active.request("turn/start", { threadId: id, input: [{ type: "text", text: "CONTINUE_IMPORTED" }] });
  assert.equal((await completed).status, "completed");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].model, "gpt-5.4", "destination model comes from Codex, not Pi");
  const input = requests[0].input;
  const text = input.filter(item => item.type === "message").flatMap(item => item.content.map(block => block.text).filter(value => value !== undefined));
  for (const expected of expectedText) assert.ok(text.includes(expected), JSON.stringify({ missing: expected, text }));
  assert.equal(text.filter(value => value === "same").length, 2);
  assert.equal(text.filter(value => value === expectedText[0]).length, 1, "visibility event must not duplicate model context");
  for (const dropped of ["ORIGINAL_USER", "ORIGINAL_ASSISTANT", "ABANDONED_BRANCH", "ABANDONED_REPLY", "OLDER_SUMMARY", "PI_SYSTEM_PROMPT"]) {
    assert.ok(!JSON.stringify(input).includes(dropped), `dropped context: ${dropped}`);
  }
  const importedCalls = input.filter(item => item.type === "function_call");
  assert.ok(importedCalls.every(item => item.call_id.length <= 64));
  const importedId = importedCalls[0].call_id;
  assert.notEqual(importedId, "b");
  assert.equal(importedCalls[1].call_id, "b");
  assert.deepEqual(input.filter(item => item.type === "function_call").map(item => JSON.parse(item.arguments)),
    [{ path: "unicode 雪\\quote\"" }, { nested: [true, null] }]);
  assert.deepEqual(input.filter(item => item.type === "function_call_output").map(item => item.call_id), ["b", importedId]);
  assert.deepEqual(JSON.parse(input.find(item => item.type === "function_call_output" && item.call_id === importedId).output),
    { isError: true, content: "A_FAILED" });
  assert.deepEqual(await readFile(source), original);
  const repeated = await launch(f, [source, "--cwd", f.home]).done;
  assert.equal(repeated.code, 0, repeated.stderr);
  const other = repeated.stdout.match(/Codex thread ([0-9a-f-]+)/)?.[1];
  assert.notEqual(other, id);
  assert.equal((await active.request("thread/read", { threadId: other })).thread.cwd, f.home);
  assert.equal(requests.length, 1, "reimport also makes no provider request");
});
