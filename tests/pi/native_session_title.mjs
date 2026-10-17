// Node is required: Bun does not implement node:sqlite. No SDK or database mocks.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, realpath, rm, stat, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageDir = process.env.PI_PACKAGE_DIR ?? "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(
  pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href
);
const extension = join(root, "config/pi-agent/pi-extensions/session-title.ts");

function setEnvironment(t, values) {
  const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]));
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  t.after(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });
}

async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), "native-session-title-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const home = join(directory, "home");
  const codexHome = join(directory, "explicit-codex-home");
  const sessions = join(directory, "sessions");
  await Promise.all([home, codexHome, sessions].map(path => mkdir(path)));
  setEnvironment(t, { HOME: home, USERPROFILE: home, CODEX_HOME: codexHome, PI_SESSION_SEARCH_ROOT: sessions });
  const loaded = await discoverAndLoadExtensions([extension], directory, join(directory, "agent"));
  assert.deepEqual(loaded.errors, [], "the installed Pi loader must load the real extension");
  assert.equal(loaded.extensions.length, 1);
  const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, directory,
    SessionManager.inMemory(directory), undefined);
  const notifications = [];
  const errors = [];
  runner.setUIContext({ notify: (message, level) => notifications.push({ message, level }) });
  runner.onError(error => errors.push(error));

  async function read(input, overrides = {}) {
    notifications.length = 0;
    errors.length = 0;
    const event = {
      type: "tool_result", toolCallId: "read-title-test", toolName: "read_session",
      input: typeof input === "string" ? { sessionFile: input } : input,
      content: [
        { type: "text", text: "Original transcript: user asked a question; assistant answered." },
        { type: "image", data: "AA==", mimeType: "image/png" },
      ],
      details: { sessionId: "original-transcript-id", messages: [{ role: "user", text: "keep me" }] },
      structuredContent: { transcript: [{ role: "assistant", content: "Keep structured content too." }] },
      isError: false,
      ...overrides,
    };
    const before = structuredClone(event);
    const started = performance.now();
    const result = await runner.emitToolResult(event);
    const elapsed = performance.now() - started;
    // ExtensionRunner catches exceptions. Checking only that emitToolResult resolves
    // would miss SessionManager.open(Codex) throwing and silently losing the title.
    assert.deepEqual(errors, [], "the registered hook must not throw into Pi's error channel");
    assert.deepEqual(event, before, "enrichment must not mutate the original tool result");
    return { event, result, notifications: [...notifications], elapsed };
  }

  async function rollout(id, name = "filename-is-not-the-thread-id.jsonl", extra = {}) {
    const path = join(sessions, name);
    await writeFile(path, `${JSON.stringify({ type: "session_meta", payload: {
      id, cwd: "/cwd-is-not-the-thread-id", ...extra,
    } })}\n${JSON.stringify({ type: "response_item", payload: { text: "transcript" } })}\n`);
    return path;
  }
  return { directory, home, codexHome, sessions, read, rollout };
}

async function database(home, rows = [], schema = "CREATE TABLE threads (id TEXT PRIMARY KEY, name)") {
  await mkdir(home, { recursive: true });
  const path = join(home, "state_5.sqlite");
  const db = new DatabaseSync(path);
  try {
    db.exec(schema);
    if (rows.length) {
      const insert = db.prepare("INSERT INTO threads (id, name) VALUES (?, ?)");
      for (const [id, name] of rows) insert.run(id, name);
    }
  } finally {
    db.close();
  }
  return path;
}

async function snapshot(path) {
  const info = await stat(path, { bigint: true });
  return { dev: info.dev, ino: info.ino, size: info.size,
    mtimeNs: info.mtimeNs, ctimeNs: info.ctimeNs, bytes: await readFile(path) };
}

function preserved({ event, result }) {
  assert.ok(result, "the hook must decorate this result, not silently skip it");
  assert.equal(result.isError, false, "a title lookup must never turn a successful read into a tool error");
  assert.deepEqual(result.content.slice(1), event.content, "preserve every original content block");
  assert.deepEqual(result.structuredContent, event.structuredContent,
    "Pi drops structuredContent when content is replaced unless the hook returns it too");
  const { sessionTitle, sessionTitleWarning, ...originalDetails } = result.details;
  assert.deepEqual(originalDetails, event.details, "preserve all original details");
}

function titled(read, title) {
  preserved(read);
  assert.deepEqual(read.notifications, []);
  assert.equal(read.result.details.sessionTitle, title);
  assert.equal(read.result.details.sessionTitleWarning, undefined);
  assert.deepEqual(read.result.content[0], {
    type: "text", text: `Session title: ${title ?? "(untitled)"}`,
  });
}

function warned(read) {
  preserved(read);
  const warning = read.result.details.sessionTitleWarning;
  assert.equal(typeof warning, "string");
  assert.ok(warning.trim(), "the model and UI must get a useful warning");
  assert.equal(read.result.details.sessionTitle, undefined);
  assert.equal(read.result.content[0].type, "text");
  assert.ok(read.result.content[0].text.startsWith("Warning: "));
  assert.ok(read.result.content[0].text.includes(warning));
  assert.equal(read.result.content.some(block => block.text?.includes("(untitled)")), false,
    "lookup failure is not evidence that the session is untitled");
  assert.deepEqual(read.notifications, [{ message: warning, level: "warning" }]);
}

test("native Pi read_session enrichment still uses saved Pi session_info titles", async t => {
  const f = await fixture(t);
  const manager = SessionManager.create(f.directory, f.sessions);
  manager.appendMessage({ role: "user", content: "A real persisted Pi conversation", timestamp: Date.now() });
  manager.appendSessionInfo("Old Pi title");
  manager.appendSessionInfo("Latest Pi title");
  const path = manager.getSessionFile();
  assert.ok(path);
  const before = await snapshot(path);
  titled(await f.read(relative(f.sessions, path)), "Latest Pi title");
  assert.deepEqual(await snapshot(path), before, "reading a Pi title must not append session entries");
  manager.appendSessionInfo("");
  titled(await f.read(path), undefined);
  // Pi reads do not depend on a Codex database existing.
  await assert.rejects(stat(join(f.codexHome, "state_5.sqlite")), { code: "ENOENT" });
});

test("Codex titles come from a bound header ID, not filename, cwd, or transcript", async t => {
  const f = await fixture(t);
  const hostileId = "thread' OR 1=1; DROP TABLE threads; --";
  const path = await f.rollout(hostileId);
  const db = await database(f.codexHome, [
    ["filename-is-not-the-thread-id", "Filename decoy"],
    ["/cwd-is-not-the-thread-id", "Cwd decoy"],
    ["unrelated-first-row", "First row decoy"],
    [hostileId, "  Header-bound title  "],
  ]);
  const beforeDb = await snapshot(db);
  const beforeRollout = await snapshot(path);
  titled(await f.read(relative(f.sessions, path)), "Header-bound title");
  assert.deepEqual(await snapshot(db), beforeDb, "title lookup must not replace, migrate, or write the database");
  assert.deepEqual(await snapshot(path), beforeRollout, "Codex JSONL must never be rewritten by SessionManager.open");
  const inspect = new DatabaseSync(db, { readOnly: true });
  try { assert.equal(inspect.prepare("SELECT count(*) AS n FROM threads").get().n, 4); }
  finally { inspect.close(); }
});

test("ID-only Codex reads enrich from the reader's resolved sessionFile", async t => {
  const f = await fixture(t);
  await database(f.codexHome, [["named-thread", "Resolved Codex title"], ["unnamed-thread", null]]);
  for (const [id, title] of [["named-thread", "Resolved Codex title"], ["unnamed-thread", undefined]]) {
    const path = await f.rollout(id, `${id}.jsonl`);
    titled(await f.read({ sessionId: id }, {
      details: { sessionFile: path, messages: [{ role: "user", text: "keep ID-read context" }] },
    }), title);
  }
});

test("ID-only Pi reads use the reader's resolved sessionFile too", async t => {
  const f = await fixture(t);
  const manager = SessionManager.create(f.directory, f.sessions);
  manager.appendMessage({ role: "user", content: "A persisted Pi conversation", timestamp: Date.now() });
  manager.appendSessionInfo("Resolved Pi title");
  const path = manager.getSessionFile();
  assert.ok(path);
  titled(await f.read({ sessionId: manager.getSessionId() }, {
    details: { sessionFile: path, messages: [{ role: "user", text: "Pi context" }] },
  }), "Resolved Pi title");
});

test("the resolved path wins if the caller's alias disappears after the read", { skip: process.platform === "win32" }, async t => {
  const f = await fixture(t);
  const path = await f.rollout("thread");
  await database(f.codexHome, [["thread", "Resolved before alias removal"]]);
  const alias = join(f.sessions, "caller-alias.jsonl");
  await symlink(path, alias);
  const resolved = await realpath(alias);
  await unlink(alias);
  titled(await f.read({ sessionFile: alias }, {
    details: { sessionFile: resolved, messages: [{ role: "user", text: "already read through alias" }] },
  }), "Resolved before alias removal");
});

test("CODEX_HOME overrides HOME/.codex and the default follows HOME when unset", async t => {
  const f = await fixture(t);
  const path = await f.rollout("same-thread");
  await database(f.codexHome, [["same-thread", "Explicit home title"]]);
  const defaultHome = join(f.home, ".codex");
  await database(defaultHome, [["same-thread", "Default home title"]]);
  titled(await f.read(path), "Explicit home title");
  delete process.env.CODEX_HOME;
  titled(await f.read(path), "Default home title");
});

test("Codex null and blank names are legitimately untitled without a warning", async t => {
  const f = await fixture(t);
  await database(f.codexHome, [["null", null], ["empty", ""], ["whitespace", " \t\n "]]);
  for (const id of ["null", "empty", "whitespace"]) {
    await t.test(id, async () => titled(await f.read(await f.rollout(id)), undefined));
  }
});

test("Codex missing metadata quietly leaves the transcript unchanged", async t => {
  const f = await fixture(t);
  const path = await f.rollout("missing-thread");
  const db = await database(f.codexHome, [["another-thread", "Do not guess this title"]]);
  const before = await snapshot(db);
  const read = await f.read(path);
  assert.equal(read.result, undefined, "no row means no title enrichment, not an untitled label or warning");
  assert.deepEqual(read.notifications, []);
  assert.deepEqual(await snapshot(db), before);
});

// Decision table: matching string/null names enrich; absent metadata leaves the
// result alone; malformed or inaccessible sources warn without losing the read.
for (const [name, schema, rows] of [
  ["missing threads table", "CREATE TABLE unrelated (id TEXT)", []],
  ["missing name column", "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT)", []],
  ["missing id column", "CREATE TABLE threads (thread_id TEXT PRIMARY KEY, name TEXT)", []],
  ["numeric name", undefined, [["thread", 42]]],
  ["blob name", undefined, [["thread", new Uint8Array([116, 105, 116, 108, 101])]]],
]) {
  test(`Codex ${name} warns without losing the transcript`, async t => {
    const f = await fixture(t);
    const path = await f.rollout("thread");
    const db = await database(f.codexHome, rows, schema);
    const before = await snapshot(db);
    warned(await f.read(path));
    assert.deepEqual(await snapshot(db), before);
  });
}

test("a missing Codex database warns and is never created by a title read", async t => {
  const f = await fixture(t);
  const path = await f.rollout("thread");
  const db = join(f.codexHome, "state_5.sqlite");
  await assert.rejects(stat(db), { code: "ENOENT" });
  warned(await f.read(path));
  await assert.rejects(stat(db), { code: "ENOENT" });
});

for (const [name, header] of [
  ["empty header", ""],
  ["invalid JSON", "{not json}\n"],
  ["null header", "null\n"],
  ["missing payload", '{"type":"session_meta"}\n'],
  ["null payload", '{"type":"session_meta","payload":null}\n'],
  ["missing ID", '{"type":"session_meta","payload":{}}\n'],
  ["numeric ID", '{"type":"session_meta","payload":{"id":42}}\n'],
  ["blank ID", '{"type":"session_meta","payload":{"id":"  "}}\n'],
  ["oversized header", `${JSON.stringify({ type: "session_meta", payload: {
    id: "thread", padding: "x".repeat(8 * 1024 * 1024),
  } })}\n`],
]) {
  test(`Codex ${name} warns non-fatally`, async t => {
    const f = await fixture(t);
    await database(f.codexHome, [["thread", "Do not guess this title"]]);
    const path = join(f.sessions, "thread.jsonl");
    await writeFile(path, header);
    const before = await snapshot(path);
    warned(await f.read(path));
    assert.deepEqual(await snapshot(path), before);
  });
}

test("the header bound does not reject a large transcript after a small valid header", async t => {
  const f = await fixture(t);
  const path = await f.rollout("thread");
  await database(f.codexHome, [["thread", "Title before large transcript"]]);
  const header = (await readFile(path, "utf8")).split("\n")[0];
  await writeFile(path, `${header}\n${JSON.stringify({ type: "response_item", payload: {
    text: "x".repeat(8 * 1024 * 1024),
  } })}\n`);
  titled(await f.read(path), "Title before large transcript");
});

test("unrelated tools, failed reads, and read_session chooser modes are untouched", async t => {
  const f = await fixture(t);
  const nonexistent = join(f.sessions, "does-not-exist.jsonl");
  for (const [name, input, overrides] of [
    ["unrelated tool", { sessionFile: nonexistent }, { toolName: "read" }],
    ["failed read", { sessionFile: nonexistent }, { isError: true }],
    ["version chooser", { sessionId: "thread" }, { details: { versions: [
      { index: 1, sessionFile: nonexistent }, { index: 2, sessionFile: `${nonexistent}.other` },
    ] } }],
    ["legacy ID-only read without resolved path", { sessionId: "thread" }, {}],
    ["non-string path", { sessionFile: 42 }, {}],
  ]) {
    await t.test(name, async () => {
      const read = await f.read(input, overrides);
      assert.equal(read.result, undefined);
      assert.deepEqual(read.notifications, []);
    });
  }
});

test("a live SQLite WAL reader sees the committed title before checkpointing", async t => {
  const f = await fixture(t);
  const path = await f.rollout("thread");
  const dbPath = await database(f.codexHome, [["thread", "Checkpointed old title"]]);
  const writer = new DatabaseSync(dbPath);
  try {
    assert.equal(writer.prepare("PRAGMA journal_mode=WAL").get().journal_mode, "wal");
    writer.exec("PRAGMA wal_autocheckpoint=0; PRAGMA wal_checkpoint(TRUNCATE)");
    const checkpointed = await readFile(dbPath);
    writer.prepare("UPDATE threads SET name = ? WHERE id = ?").run("Live uncheckpointed title", "thread");
    assert.ok((await stat(`${dbPath}-wal`)).size > 32, "the title must actually live in WAL frames");
    assert.deepEqual(await readFile(dbPath), checkpointed, "the main file still has the old title");
    const before = await snapshot(dbPath);
    titled(await f.read(path), "Live uncheckpointed title");
    assert.deepEqual(await snapshot(dbPath), before);
  } finally { writer.close(); }
});

test("an exclusively locked database times out quickly and preserves the transcript", async t => {
  const f = await fixture(t);
  const path = await f.rollout("thread");
  const dbPath = await database(f.codexHome, [["thread", "Locked title"]]);
  const writer = new DatabaseSync(dbPath);
  try {
    writer.exec("BEGIN EXCLUSIVE");
    const read = await f.read(path);
    warned(read);
    assert.ok(read.elapsed >= 50, `expected a short busy wait, got ${read.elapsed}ms`);
    assert.ok(read.elapsed < 1500, `title lookup blocked transcript access for ${read.elapsed}ms`);
  } finally {
    writer.exec("ROLLBACK");
    writer.close();
  }
  titled(await f.read(path), "Locked title");
});
