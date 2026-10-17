// Opt-in integration with a real session-search package, never copied reader output.
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const readerPackage = process.env.PI_SESSION_SEARCH_PACKAGE_DIR;
const titleExtension = fileURLToPath(new URL("../../config/pi-agent/pi-extensions/session-title.ts", import.meta.url));

test("real reader results compose with title enrichment", {
  skip: !readerPackage && "set PI_SESSION_SEARCH_PACKAGE_DIR to an installed package or checkout",
}, async t => {
  const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
  const manifest = JSON.parse(await readFile(path.join(packageDir, "package.json"), "utf8"));
  assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(
    pathToFileURL(path.resolve(packageDir, manifest.exports["."].import)).href
  );
  const root = await mkdtemp(path.join(tmpdir(), "session-reader-title-"));
  const keys = ["HOME", "USERPROFILE", "CODEX_HOME", "PI_SESSION_SEARCH_ROOT",
    "PI_SESSION_SEARCH_CODEX_ROOT", "PI_SESSION_SEARCH_MAX_BYTES"];
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    const home = path.join(root, "home");
    const codexHome = path.join(root, "codex");
    const codexRoot = path.join(codexHome, "sessions");
    const piRoot = path.join(root, "pi");
    await Promise.all([home, codexRoot, piRoot].map(dir => mkdir(dir, { recursive: true })));
    Object.assign(process.env, { HOME: home, USERPROFILE: home, CODEX_HOME: codexHome,
      PI_SESSION_SEARCH_ROOT: piRoot, PI_SESSION_SEARCH_CODEX_ROOT: codexRoot });
    delete process.env.PI_SESSION_SEARCH_MAX_BYTES;

    const loaded = await discoverAndLoadExtensions([path.resolve(readerPackage), titleExtension], root, path.join(root, "agent"));
    assert.deepEqual(loaded.errors, []);
    assert.deepEqual(loaded.warnings, []);
    const reader = loaded.extensions.find(extension => extension.tools.has("read_session"));
    assert.ok(reader, "the supplied package must register read_session");
    const read = reader.tools.get("read_session").definition;
    const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, root, SessionManager.inMemory(root), undefined);
    const notifications = [];
    const errors = [];
    runner.setUIContext({ notify: (message, level) => notifications.push({ message, level }) });
    runner.onError(error => errors.push(error));

    const time = "2026-10-17T10:00:00.000Z";
    const id = n => `${String(n).padStart(8, "0")}-0000-4000-8000-000000000000`;
    const header = (thread, base) => ({
      type: "session_meta", timestamp: time, ordinal: base?.end_ordinal_exclusive ?? 0,
      payload: { id: thread, cwd: root, timestamp: time, history_mode: "paginated",
        ...(base ? { history_base: base } : {}) },
    });
    const message = (entry, ordinal) => ({
      type: "response_item", timestamp: time, ordinal,
      payload: { type: "message", id: entry, role: "user", content: [{ type: "input_text", text: `context ${entry}` }] },
    });
    const jsonl = rows => rows.map(row => JSON.stringify(row) + "\n").join("");
    async function recording(thread, rows, rollout) {
      const file = path.join(codexRoot, `rollout-2026-10-17T10-00-00-${thread}${rollout ? "_" + rollout : ""}.jsonl`);
      await writeFile(file, jsonl(rows));
      return file;
    }

    const databasePath = path.join(codexHome, "state_5.sqlite");
    const database = new DatabaseSync(databasePath);
    try {
      database.exec("CREATE TABLE threads (id TEXT PRIMARY KEY, name TEXT)");
      for (const row of [[id(1), "Named Codex title"], [id(2), null], [id(4), "Versioned thread title"],
        [id(5), "Ancestor title"], [id(6), "Selected child title"]]) {
        database.prepare("INSERT INTO threads VALUES (?, ?)").run(...row);
      }
    } finally {
      database.close();
    }
    const databaseBefore = await readFile(databasePath);
    const named = await recording(id(1), [header(id(1)), message("named-message", 1)]);
    const unnamed = await recording(id(2), [header(id(2)), message("unnamed-message", 1)]);
    const missing = await recording(id(3), [header(id(3)), message("missing-message", 1)]);
    const versionA = await recording(id(4), [header(id(4)), message("version-a", 1)], id(40));
    const versionB = await recording(id(4), [header(id(4)), message("version-b", 1)], id(41));
    const parentRows = [header(id(5)), message("ancestor-message", 1)];
    await recording(id(5), parentRows);
    const child = await recording(id(6), [header(id(6), {
      thread_id: id(5), end_ordinal_exclusive: 2, end_byte_offset: Buffer.byteLength(jsonl(parentRows)),
    }), message("child-message", 3)]);
    const pi = SessionManager.create(root, path.join(piRoot, "--fixture--"));
    pi.appendMessage({ role: "user", content: "Pi conversation", timestamp: Date.now() });
    pi.appendSessionInfo("Named Pi title");

    async function check(params, expected) {
      notifications.length = 0;
      errors.length = 0;
      // Feed the registered reader's actual result into the installed hook runner.
      // Do not manufacture details.sessionFile: that omission caused the ID-read gap.
      const raw = await read.execute("composed-read", params, undefined, undefined, runner.createToolContext("composed-read", undefined));
      assert.notEqual(raw.isError, true, JSON.stringify(raw.content));
      const event = { ...raw, type: "tool_result", toolCallId: "composed-read", toolName: "read_session",
        input: params, isError: false };
      const original = structuredClone(event);
      const enriched = await runner.emitToolResult(event);
      assert.deepEqual(event, original, "do not mutate the original reader result");
      assert.deepEqual(errors, [], "the runner must not catch a title-hook exception");
      assert.deepEqual(notifications, []);
      if (expected.versions) {
        assert.equal(raw.details.sessionFile, undefined);
        assert.equal(raw.details.versions.length, 2);
        assert.deepEqual(new Set(raw.details.versions.map(version => version.sessionFile)), new Set([versionA, versionB]));
        assert.equal(enriched, undefined, "do not select a title for an ambiguous thread");
        return;
      }
      assert.equal(raw.details.sessionFile, await realpath(expected.file));
      if (expected.missing) {
        assert.equal(enriched, undefined, "missing title metadata must leave the reader result untouched");
        return;
      }
      assert.ok(enriched, "the hook must enrich the resolved transcript");
      assert.equal(enriched.isError, false);
      assert.equal(enriched.details.sessionTitle, expected.title);
      assert.equal(enriched.details.sessionTitleWarning, undefined);
      assert.equal(enriched.content[0].text, `Session title: ${expected.title ?? "(untitled)"}`);
      assert.deepEqual(enriched.content.slice(1), raw.content);
      const { sessionTitle, ...details } = enriched.details;
      assert.deepEqual(details, raw.details, "preserve resolved paths, cursors, and message metadata");
      if (expected.entry) assert.equal(raw.details.messages[0].entryId, expected.entry);
    }

    for (const [name, params, expected] of [
      ["named Codex ID", { sessionId: id(1), maxMessages: 1 }, { file: named, title: "Named Codex title" }],
      ["unnamed Codex ID", { sessionId: id(2), maxMessages: 1 }, { file: unnamed, title: undefined }],
      ["missing title metadata", { sessionId: id(3), maxMessages: 1 }, { file: missing, missing: true }],
      ["named Pi ID", { sessionId: pi.getSessionId(), maxMessages: 1 }, { file: pi.getSessionFile(), title: "Named Pi title" }],
      ["relative Pi file", { sessionFile: path.relative(piRoot, pi.getSessionFile()), maxMessages: 1 },
        { file: pi.getSessionFile(), title: "Named Pi title" }],
      ["empty ID read", { sessionId: id(1), maxMessages: 0 }, { file: named, title: "Named Codex title" }],
      ["ambiguous ID", { sessionId: id(4), maxMessages: 1 }, { versions: true }],
      ["selected version", { sessionFile: versionB, maxMessages: 1 },
        { file: versionB, title: "Versioned thread title", entry: "version-b" }],
      ["inherited context", { sessionId: id(6), maxMessages: 1 },
        { file: child, title: "Selected child title", entry: "ancestor-message" }],
    ]) {
      await t.test(name, () => check(params, expected));
    }
    assert.deepEqual(await readFile(databasePath), databaseBefore, "title enrichment must not write the database");
  } finally {
    for (const key of keys) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
    await rm(root, { recursive: true, force: true });
  }
});
