import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, realpathSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, symlink, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { appendDisplayHistory, CodexClient, convertMessages, loadPi, loadPiPackage, readSession } from "../pi-to-codex.mjs";

import { piBuildIdentity } from "../compatibility.mjs";

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, "../../..");
const command = join(root, "bin/pi-to-codex");
const sdk = await loadPi();
const execute = promisify(execFile);
const nativeFeatures = "[features]\nplugins = false\napps = false\n";
const usage = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const user = text => ({ role: "user", content: text, timestamp: 1 });
const assistant = content => ({ role: "assistant", content, api: "anthropic-messages", provider: "anthropic",
  model: "source-model", usage, stopReason: "stop", timestamp: 2 });
const call = (id, args = {}) => ({ type: "toolCall", id, name: "read", arguments: args });
const result = (id, text, isError = false) => ({ role: "toolResult", toolCallId: id, toolName: "read",
  content: [{ type: "text", text }], isError, timestamp: 3 });

async function fixture(t, native = false, { cleanup = true } = {}) {
  const dir = await mkdtemp(join(tmpdir(), "pi-to-codex-test-"));
  if (cleanup) t.after(() => rm(dir, { recursive: true, force: true }));
  const home = join(dir, "codex");
  const bin = join(dir, "bin");
  const temp = join(dir, "temporary");
  await Promise.all([mkdir(home), mkdir(bin), mkdir(temp)]);
  await writeFile(join(home, "dotfiles.config.toml"), "");
  if (native) {
    // Native fixtures do not need optional marketplace clones or app services.
    await writeFile(join(home, "config.toml"), nativeFeatures);
    await symlink(native, join(bin, "codex"));
  } else await symlink(join(directory, "fixtures/codex.mjs"), join(bin, "codex"));
  const manager = sdk.SessionManager.create(dir, join(dir, "pi-sessions"));
  manager.appendMessage(user("ORIGINAL_USER"));
  manager.appendMessage(assistant([{ type: "text", text: "ORIGINAL_ASSISTANT" }]));
  const source = manager.getSessionFile();
  return { dir, home, temp, source, manager,
    env: { ...process.env, HOME: dir, CODEX_HOME: home, TMPDIR: temp, PATH: `${bin}:${process.env.PATH}` } };
}

function launch(f, args = [f.source], extra = {}, { cwd } = {}) {
  const child = spawn(process.execPath, [command, ...args], { env: { ...f.env, ...extra }, cwd, stdio: ["ignore", "pipe", "pipe"] });
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

test("CodexClient preserves stderr diagnostics across UTF-8 boundaries", async t => {
  const cases = [];
  for (const character of ["é", "中", "🙂"]) {
    const text = `diagnostic:\n${character}\ncontext`;
    const bytes = Buffer.from(text);
    for (let split = 1; split < Buffer.byteLength(character); split++) {
      const at = bytes.indexOf(Buffer.from(character)) + split;
      cases.push({ name: `${character} split ${split}`, text, chunks: [bytes.subarray(0, at), bytes.subarray(at)] });
    }
  }
  cases.push(
    { name: "ASCII", text: "ASCII failure", chunks: [Buffer.from("ASCII failure")] },
    { name: "UTF-16 tail limit", text: "中".repeat(16384), chunks: [Buffer.from("prefix:" + "中".repeat(16384))] },
    { name: "incomplete UTF-8 at EOF", text: "failure: �", chunks: [Buffer.concat([Buffer.from("failure: "), Buffer.from([0xe2, 0x82])])] },
  );
  for (const { name, text, chunks } of cases) await t.test(name, async t => {
    const f = await fixture(t);
    const client = new CodexClient({ command: join(f.dir, "bin/codex"),
      env: { ...f.env, PI_IMPORT_FIXTURE_MODE: "stderr" } });
    t.after(() => client.close().catch(() => {}));
    let received = 0;
    let released = 0;
    const boundaries = chunks.map(chunk => chunk.length);
    for (let i = 1; i < boundaries.length; i++) boundaries[i] += boundaries[i - 1];
    const stream = client.process.stderr;
    const push = stream.push;
    // Deliver each raw fragment before allowing the child to write the next:
    // the real pipe cannot coalesce the UTF-8 boundary under test.
    stream.push = function (chunk, encoding) {
      const result = push.call(this, chunk, encoding);
      if (chunk) {
        received += chunk.length;
        while (released < boundaries.length - 1 && received >= boundaries[released]) {
          released++;
          client.send({ method: "fixture/next-stderr" });
        }
      }
      return result;
    };
    await assert.rejects(client.request("fixture/stderr", { chunks: chunks.map(chunk => chunk.toString("base64")) }),
      { message: `Codex app-server exited (7): ${text}` });
    assert.equal(received, boundaries.at(-1));
    await noChildren(f);
  });
});

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
  assert.deepEqual(requests.filter(item => item.method === "thread/name/set").map(item => item.params),
    [{ threadId: JSON.parse(await readFile(join(f.home, "fixture-thread.json"))).id, name: "ORIGINAL_USER" }]);
  const methods = requests.map(item => item.method);
  assert.ok(methods.indexOf("thread/name/set") > methods.lastIndexOf("thread/resume"));
  assert.ok(methods.indexOf("thread/name/set") < methods.indexOf("thread/list"));
  const records = await readLines(join(f.home, "owned-rollout.jsonl"));
  assert.deepEqual(records.filter(item => item.type === "event_msg" && item.payload.type === "user_message")
    .map(item => item.payload.message), ["ORIGINAL_USER"]);
  assert.equal(records.filter(item => item.type === "event_msg" && item.payload.type === "item_completed").length, 2);
  assert.equal(requests.filter(item => item.method === "thread/read").length, 1);
  assert.equal(records.at(-1).ordinal, records.length - 1);
  assert.deepEqual(await readFile(f.source), original);
  await noChildren(f);
});

test("imported names normalize whitespace and bound Unicode text without changing history", async t => {
  const f = await fixture(t);
  const text = `  \n ${"🙂  雪\t".repeat(90)}\n tail`;
  const records = await readLines(f.source);
  records.find(record => record.message?.role === "user").message.content = text;
  await writeFile(f.source, records.map(record => JSON.stringify(record) + "\n").join(""));
  const outcome = await launch(f).done;
  assert.equal(outcome.code, 0, outcome.stderr);
  const requests = await readLines(join(f.home, "fixture-requests.jsonl"));
  const named = requests.find(item => item.method === "thread/name/set").params.name;
  assert.equal(named, "🙂 雪 ".repeat(20));
  assert.equal(Array.from(named).length, 80);
  const injected = requests.find(item => item.method === "thread/resume" && item.params.history);
  assert.equal(injected.params.history[0].content[0].text, text);
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
  for (const mode of ["reject", "eof", "malformed", "bad-rollout", "reopen-error", "index-update-error", "missing-index", "missing-display"]) {
    const f = await fixture(t);
    const original = await readFile(f.source);
    const outcome = await launch(f, undefined, { PI_IMPORT_FIXTURE_MODE: mode }).done;
    assert.equal(outcome.code, 1, `${mode}: ${outcome.stderr}`);
    assert.equal(outcome.stdout, "");
    assert.match(outcome.stderr, /pi-to-codex:/);
    assert.match(outcome.stderr, /inspect .*before retrying/);
    if (["bad-rollout", "reopen-error", "index-update-error", "missing-index", "missing-display"].includes(mode)) {
      assert.match(outcome.stderr, /thread [0-9a-f-]+ may be partially imported/);
    }
    if (mode === "missing-index") assert.match(outcome.stderr, /absent from Codex's resume index/);
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

test("imported threads use the dotfiles profile instead of base approval defaults", { timeout: 30000 }, async t => {
  const native = nativeCodex();
  if (!native) { t.skip("native Codex is not installed"); return; }
  const f = await fixture(t, native);
  await writeFile(join(f.home, "config.toml"), 'approvals_reviewer = "user"\nmodel = "base-model"\n' + nativeFeatures);
  for (const reviewer of ["auto_review", "user"]) {
    await writeFile(join(f.home, "dotfiles.config.toml"),
      `approvals_reviewer = "${reviewer}"\nmodel = "profile-model"\n`);
    const imported = await launch(f).done;
    assert.equal(imported.code, 0, imported.stderr);
    const id = imported.stdout.match(/Codex thread ([0-9a-f-]+)/)?.[1];
    assert.ok(id, imported.stdout);
    const client = new CodexClient({ command: native, env: f.env });
    try {
      await client.initialize();
      const resumed = await client.request("thread/resume", { threadId: id, excludeTurns: true });
      assert.equal(resumed.approvalsReviewer, reviewer);
      assert.equal(resumed.model, "profile-model");
    } finally { await client.close(); }
  }
});

test("native metadata update recovers an already-created unindexed import without duplicating history", { timeout: 30000 }, async t => {
  const native = nativeCodex();
  if (!native) { t.skip("native Codex is not installed"); return; }
  const f = await fixture(t, native);
  const context = await readSession(f.source);
  const withNative = async work => {
    const client = new CodexClient({ command: native, env: f.env });
    try {
      await client.initialize();
      return await work(client);
    } finally { await client.close(); }
  };
  // Reproduce the previous import path: persist history, append display events,
  // then resume and close without an explicit metadata update.
  const thread = await withNative(async client => (await client.request("thread/resume", {
    threadId: "00000000-0000-4000-8000-000000000000", history: context.history,
    cwd: context.cwd, excludeTurns: true,
  })).thread);
  await appendDisplayHistory(thread, context);
  await withNative(client => client.request("thread/resume", { threadId: thread.id, excludeTurns: true }));
  const before = await readLines(thread.path);
  const indexed = await withNative(client => client.request("thread/list", { modelProviders: [], useStateDbOnly: true }));
  t.diagnostic(`previous import path indexed: ${indexed.data.some(item => item.id === thread.id)}`);

  // A native metadata operation on the resumed writer commits the reconstructed
  // preview. It must not inject a duplicate prompt or start a model turn.
  await withNative(async client => {
    await client.request("thread/resume", { threadId: thread.id, excludeTurns: true });
    await client.request("thread/name/set", { threadId: thread.id, name: "Recovered Pi session" });
  });
  await withNative(async client => {
    const listed = await client.request("thread/list", { modelProviders: [], useStateDbOnly: true });
    const recovered = listed.data.find(item => item.id === thread.id);
    assert.ok(recovered, "fresh process sees the recovered thread in the database-only index");
    assert.equal(recovered.name, "Recovered Pi session");
    const read = await client.request("thread/read", { threadId: thread.id, includeTurns: true });
    assert.deepEqual(read.thread.turns.flatMap(turn => turn.items).map(item => item.id), context.display.map(item => item.id));
  });
  const after = await readLines(thread.path);
  // Native resumes may persist configuration-only settings snapshots (0.162.1
  // does). Those are not model messages or displayed history.
  const history = records => records.filter(record => record.type === "response_item" ||
    (record.type === "event_msg" && record.payload.type !== "thread_settings_applied"));
  assert.deepEqual(history(after), history(before), "recovery neither appends model messages nor duplicates UI events");
});

test("missing and invalid profiles fail before creating an imported thread", async t => {
  for (const contents of [null, "invalid = ["]) {
    const f = await fixture(t);
    const profile = join(f.home, "dotfiles.config.toml");
    if (contents === null) await rm(profile);
    else await writeFile(profile, contents);
    const imported = await launch(f).done;
    assert.notEqual(imported.code, 0);
    assert.equal(existsSync(join(f.home, "fixture-pids.jsonl")), false);
  }
});

test("real Codex terminal UI displays imported messages", { timeout: 20000 }, async t => {
  const native = nativeCodex();
  const tmux = ["/usr/bin/tmux", "/opt/homebrew/bin/tmux"].find(path => existsSync(path));
  if (!native || !tmux) { t.skip("native Codex and tmux are required for the terminal UI check"); return; }
  const f = await fixture(t, native);
  await writeFile(join(f.home, "config.toml"), `model = "gpt-5.4"
model_provider = "fixture"
${nativeFeatures}[model_providers.fixture]
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
  const f = await fixture(t, native, { cleanup: false });
  let active;
  let server;
  // Node skips later after-hooks when one fails. Close the client before its
  // provider and storage, and still attempt all cleanup if any step fails.
  t.after(async () => {
    const failures = [];
    try { if (active) await active.close(); } catch (error) { failures.push(error); }
    try {
      if (server?.listening) {
        server.closeAllConnections();
        await new Promise((resolveClose, rejectClose) => server.close(error => error ? rejectClose(error) : resolveClose()));
      }
    } catch (error) { failures.push(error); }
    try { await rm(f.dir, { recursive: true, force: true }); } catch (error) { failures.push(error); }
    if (failures.length) throw new AggregateError(failures, "retained-context fixture cleanup failed");
  });
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
  server = createServer(async (request, response) => {
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
  await writeFile(join(f.home, "config.toml"), `model = "gpt-5.4"
model_provider = "fixture"
approval_policy = "never"
sandbox_mode = "read-only"
${nativeFeatures}enable_request_compression = false
[model_providers.fixture]
name = "fixture"
base_url = "http://127.0.0.1:${server.address().port}/v1"
wire_api = "responses"
requires_openai_auth = false
`);
  active = new CodexClient({ command: native, env: f.env });
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

async function compatibilityFixture(t) {
  const f = await fixture(t);
  f.env.XDG_CACHE_HOME = join(f.dir, "cache");
  f.cache = join(f.env.XDG_CACHE_HOME, "pi-to-codex/compatibility.json");
  f.audit = join(f.dir, "audit.jsonl");
  const packageInfo = await loadPiPackage();
  const alias = join(f.dir, "pi-install/node/node_modules/@earendil-works/pi-coding-agent");
  await mkdir(dirname(alias), { recursive: true });
  await symlink(packageInfo.directory, alias);
  f.revision = join(f.dir, "pi-install/node/.source-revision");
  await writeFile(f.revision, "a".repeat(40) + "\n");
  f.env.PI_PACKAGE_DIR = alias;
  const original = await readFile(join(directory, "fixtures/codex.mjs"), "utf8");
  await rm(join(f.dir, "bin/codex"));
  f.install = async (mode = "normal", version = "fixture-1") => {
    const audit = `appendFileSync(${JSON.stringify(f.audit)}, JSON.stringify({ event: "start", pid: process.pid,
      argv: process.argv.slice(2), cwd: process.cwd(), home: process.env.HOME, codexHome: process.env.CODEX_HOME,
      sqliteHome: process.env.CODEX_SQLITE_HOME, configHome: process.env.XDG_CONFIG_HOME,
      envKeys: Object.keys(process.env) }) + "\\n");\n`;
    const auditRequest = `appendFileSync(${JSON.stringify(f.audit)}, JSON.stringify({ event: "request",
      home: process.env.HOME, ...request }) + "\\n");\n`;
    const script = original.replace('if (process.argv.includes("--version"))', audit + 'if (process.argv.includes("--version"))')
      .replace('codex-cli fixture-1', `codex-cli ${version}`)
      .replace('const mode = process.env.PI_IMPORT_FIXTURE_MODE;', `const mode = ${JSON.stringify(mode)};`)
      .replace('if (request.method === undefined) return;', 'if (request.method === undefined) return;\n' + auditRequest);
    await writeFile(join(f.dir, "bin/codex"), script, { mode: 0o755 });
  };
  await f.install();
  return f;
}

async function audit(f) { return existsSync(f.audit) ? readLines(f.audit) : []; }

async function noCompatibilityChildren(f) {
  for (const row of (await audit(f)).filter(row => row.event === "start")) {
    assert.throws(() => process.kill(row.pid, 0), { code: "ESRCH" });
    if (row.home !== f.dir) assert.equal(existsSync(dirname(row.home)), false, "disposable compatibility home removed");
  }
}

test("preflight resolves Python before isolating mise trust state", async t => {
  const { stdout } = await execute("python3", ["-c", "import sys; print(sys.executable)"]);
  const python = stdout.trim();
  for (const failResolution of [false, true]) await t.test(`resolution failure: ${failResolution}`, async t => {
    const f = await compatibilityFixture(t);
    const log = join(f.dir, "python.jsonl");
    await writeFile(join(f.dir, "bin/python3"), `#!${process.execPath}
import { appendFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
appendFileSync(${JSON.stringify(log)}, JSON.stringify({ home: process.env.HOME, args: process.argv.slice(2) }) + "\\n");
if (process.env.HOME !== ${JSON.stringify(f.dir)}) {
  console.error("mise config is not trusted in private HOME");
  process.exit(1);
}
if (${failResolution} && process.argv[2] === "-c") {
  console.error("Python resolution failed");
  process.exit(1);
}
const result = spawnSync(${JSON.stringify(python)}, process.argv.slice(2), { stdio: "inherit" });
process.exit(result.status ?? 1);
`, { mode: 0o755 });
    const result = await launch(f).done;
    if (failResolution) {
      assert.notEqual(result.code, 0);
      assert.match(result.stderr, /Python resolution failed/);
      assert.equal(existsSync(f.cache), false);
      assert.equal(existsSync(join(f.home, "fixture-pids.jsonl")), false);
    } else {
      assert.equal(result.code, 0, result.stderr);
      assert.match(result.stdout, /Imported 2 history items/);
      assert.equal(existsSync(f.cache), true);
    }
    const invocations = await readLines(log);
    assert.ok(invocations.every(row => row.home === f.dir), "private probe bypasses the shim");
    await noCompatibilityChildren(f);
  });
});

test("compatibility preflight imports once privately, captures local context, and skips probe startup on cache hits", async t => {
  const f = await compatibilityFixture(t);
  await writeFile(join(f.home, "dotfiles.config.toml"), 'model = "REAL_PROFILE_MUST_NOT_REACH_PROBE"\n');
  Object.assign(f.env, { OPENAI_API_KEY: "PRIVATE_AUTH", OPENAI_BASE_URL: "http://invalid.invalid",
    CODEX_SQLITE_HOME: join(f.dir, "real-sqlite"), HTTP_PROXY: "http://invalid.invalid" });
  const first = await launch(f).done;
  assert.equal(first.code, 0, first.stderr);
  assert.match(first.stderr, /Checking Pi\/Codex compatibility/);
  const receipt = await readFile(f.cache);
  assert.equal(JSON.parse(receipt).pi.revision, "a".repeat(40));
  const cold = await audit(f);
  const privateStarts = cold.filter(row => row.event === "start" && row.home !== f.dir);
  assert.ok(privateStarts.some(row => row.argv[0] === "app-server"));
  assert.equal(privateStarts.filter(row => row.argv[0] === "--version").length, 1);
  for (const row of privateStarts) {
    for (const forbidden of ["OPENAI_API_KEY", "OPENAI_BASE_URL", "HTTP_PROXY"]) assert.ok(!row.envKeys.includes(forbidden));
    assert.notEqual(row.codexHome, f.home);
    assert.notEqual(row.sqliteHome, f.env.CODEX_SQLITE_HOME);
    assert.equal(row.cwd, dirname(row.home));
  }
  const privateRequests = cold.filter(row => row.event === "request" && row.home !== f.dir);
  assert.equal(privateRequests.filter(row => row.method === "thread/resume" && row.params.history).length, 1);
  assert.equal(privateRequests.filter(row => row.method === "turn/start").length, 1);
  assert.equal(privateRequests.filter(row => row.method === "thread/start").length, 0);
  assert.ok(!JSON.stringify(privateRequests).includes("REAL_PROFILE_MUST_NOT_REACH_PROBE"));
  const realRequests = cold.filter(row => row.event === "request" && row.home === f.dir);
  assert.equal(realRequests.filter(row => row.method === "thread/resume" && row.params.history).length, 1);
  assert.equal(realRequests.filter(row => row.method === "turn/start").length, 0);
  const priorMtime = (await stat(f.cache, { bigint: true })).mtimeNs;
  const second = await launch(f).done;
  assert.equal(second.code, 0, second.stderr);
  assert.ok(!second.stderr.includes("Checking Pi/Codex compatibility"));
  const warm = (await audit(f)).slice(cold.length);
  assert.equal(warm.filter(row => row.event === "start" && row.home !== f.dir && row.argv[0] === "--version").length, 1);
  assert.equal(warm.filter(row => row.event === "start" && row.home !== f.dir && row.argv[0] === "app-server").length, 0);
  assert.deepEqual(await readFile(f.cache), receipt);
  assert.equal((await stat(f.cache, { bigint: true })).mtimeNs, priorMtime);
  await noCompatibilityChildren(f);
});

test("public preflight and publication traverse the repository Codex wrapper without generating interactive config", async t => {
  const f = await compatibilityFixture(t);
  f.env.PATH = `${join(root, "bin")}:${f.env.PATH}`;
  const result = await launch(f).done;
  assert.equal(result.code, 0, result.stderr);
  assert.match(result.stdout, /Imported 2 history items into Codex thread/);
  const rows = await audit(f);
  assert.ok(rows.some(row => row.event === "start" && row.home !== f.dir && row.argv[0] === "--version"));
  assert.ok(rows.some(row => row.event === "start" && row.home !== f.dir && row.argv[0] === "app-server"));
  assert.ok(rows.some(row => row.event === "start" && row.home === f.dir && row.argv[0] === "app-server"));
  assert.equal(existsSync(f.cache), true);
  assert.equal(existsSync(join(f.home, "config.toml")), false, "wrapper must not generate interactive configuration");
  assert.equal(existsSync(join(f.home, "rules")), false, "wrapper must not generate interactive permission rules");
  await noCompatibilityChildren(f);
});

test("publication preserves launch cwd while its thread uses the destination cwd and the probe uses private root", async t => {
  const f = await compatibilityFixture(t);
  const launchCwd = join(f.dir, "launch");
  const destinationCwd = join(f.dir, "destination");
  await Promise.all([mkdir(launchCwd), mkdir(destinationCwd)]);
  const result = await launch(f, [f.source, "--cwd", destinationCwd], {}, { cwd: launchCwd }).done;
  assert.equal(result.code, 0, result.stderr);
  const rows = await audit(f);
  const realStarts = rows.filter(row => row.event === "start" && row.home === f.dir);
  assert.ok(realStarts.length > 0);
  assert.ok(realStarts.every(row => row.cwd === launchCwd), "real app-servers inherit the CLI launch cwd");
  const publication = rows.find(row => row.event === "request" && row.home === f.dir &&
    row.method === "thread/resume" && row.params.history);
  assert.equal(publication.params.cwd, destinationCwd, "thread destination remains independent of startup cwd");
  assert.notEqual(destinationCwd, launchCwd);
  const probeStarts = rows.filter(row => row.event === "start" && row.home !== f.dir && row.argv[0] === "app-server");
  assert.ok(probeStarts.length > 0);
  assert.ok(probeStarts.every(row => row.cwd === dirname(row.home)), "all probe app-servers start in the private root");
  await noCompatibilityChildren(f);
});

test("Codex version and recorded Pi revision invalidate cache independently of Pi semver; corrupt receipts rerun", async t => {
  const f = await compatibilityFixture(t);
  const run = async () => {
    const before = (await audit(f)).length;
    const result = await launch(f).done;
    assert.equal(result.code, 0, result.stderr);
    assert.equal((await audit(f)).slice(before).filter(row => row.event === "request" && row.home !== f.dir &&
      row.method === "thread/resume" && row.params.history).length, 1);
    return JSON.parse(await readFile(f.cache, "utf8"));
  };
  const original = await run();
  await writeFile(f.revision, "b".repeat(40) + "\n");
  const piChanged = await run();
  assert.equal(piChanged.pi.version, original.pi.version);
  assert.equal(piChanged.pi.revision, "b".repeat(40));
  await f.install("normal", "fixture-2");
  const codexChanged = await run();
  assert.equal(codexChanged.codex, "codex-cli fixture-2");
  assert.deepEqual(codexChanged.pi, piChanged.pi);
  await writeFile(f.cache, "{corrupt");
  await run();
  await writeFile(f.cache, JSON.stringify({ ...codexChanged, format: 0 }));
  await run();
  await noCompatibilityChildren(f);
});

test("failed compatibility checks preserve older receipts and cannot publish into the real Codex home", async t => {
  for (const mode of ["missing-index", "missing-display", "bad-context", "turn-malformed", "turn-eof"]) await t.test(mode, async t => {
    const f = await compatibilityFixture(t);
    assert.equal((await launch(f).done).code, 0);
    const receipt = await readFile(f.cache);
    const realBefore = await readLines(join(f.home, "fixture-requests.jsonl"));
    const source = await readFile(f.source);
    await f.install(mode, "incompatible-version");
    const failed = await launch(f).done;
    assert.notEqual(failed.code, 0, failed.stdout);
    assert.equal(failed.stdout, "");
    assert.deepEqual(await readFile(f.cache), receipt);
    assert.deepEqual(await readFile(f.source), source);
    assert.deepEqual(await readLines(join(f.home, "fixture-requests.jsonl")), realBefore);
    await noCompatibilityChildren(f);
  });
});

test("cancelled cold compatibility checks leave no receipt, real thread, or owned process", { timeout: 15000 }, async t => {
  const f = await compatibilityFixture(t);
  await f.install("stall");
  const running = launch(f);
  const deadline = Date.now() + 10000;
  let reached = false;
  while (Date.now() < deadline) {
    if ((await audit(f)).some(row => row.event === "request" && row.method === "thread/resume")) { reached = true; break; }
    await new Promise(resolveWait => setTimeout(resolveWait, 20));
  }
  assert.equal(reached, true, "cold probe reached injection before cancellation");
  running.child.kill("SIGINT");
  const result = await running.done;
  assert.equal(result.code, 130, result.stderr);
  assert.equal(existsSync(f.cache), false);
  assert.equal(existsSync(join(f.home, "fixture-pids.jsonl")), false);
  await noCompatibilityChildren(f);
});

test("Pi overrides without recorded provenance remain supported but cannot reuse a durable compatibility receipt", async t => {
  const f = await compatibilityFixture(t);
  const installed = await loadPiPackage();
  const override = join(f.dir, "unrecorded-sdk");
  await mkdir(override);
  await writeFile(join(override, "package.json"), JSON.stringify({ name: installed.manifest.name,
    version: installed.manifest.version, type: "module", exports: { ".": { import: "./index.mjs" } } }));
  await writeFile(join(override, "index.mjs"), `export * from ${JSON.stringify(pathToFileURL(join(installed.directory, installed.manifest.exports["."].import)).href)};\n`);
  f.env.PI_PACKAGE_DIR = override;
  for (let repeat = 0; repeat < 2; repeat++) {
    const result = await launch(f).done;
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stderr, /no usable recorded build revision/);
    assert.equal(existsSync(f.cache), false);
  }
  await noCompatibilityChildren(f);
});

test("Pi build identity reads recorded lexical install, source-install, and guest authorities without consulting Git", async t => {
  const dir = await mkdtemp(join(tmpdir(), "pi-build-identity-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  for (const [name, packagePath, markerPath] of [
    ["installed", "node/node_modules/@earendil-works/pi-coding-agent", "node/.source-revision"],
    ["source", "source/packages/coding-agent", "node/.source-revision"],
    ["guest", "src/packages/coding-agent", "REVISION"],
  ]) {
    const root = join(dir, name);
    const path = join(root, packagePath);
    await mkdir(path, { recursive: true });
    await mkdir(dirname(join(root, markerPath)), { recursive: true });
    await writeFile(join(root, markerPath), "c".repeat(40));
    const identity = await piBuildIdentity({ sdk: { VERSION: "1.3.0" }, manifest: { version: "1.3.0" },
      directory: path, installedDirectory: path });
    assert.equal(identity.revision, "c".repeat(40), name);
  }
});

test("real input, cwd, and profile rejection happen before compatibility lookup or probe startup", async t => {
  for (const mode of ["input", "cwd", "profile"]) await t.test(mode, async t => {
    const f = await compatibilityFixture(t);
    let args;
    if (mode === "input") await writeFile(f.source, "not a Pi session\n");
    if (mode === "cwd") args = [f.source, "--cwd", join(f.dir, "missing-directory")];
    if (mode === "profile") await writeFile(join(f.home, "dotfiles.config.toml"), "invalid = [");
    const result = await launch(f, args).done;
    assert.notEqual(result.code, 0);
    assert.deepEqual(await audit(f), []);
    assert.equal(existsSync(f.cache), false);
  });
});
