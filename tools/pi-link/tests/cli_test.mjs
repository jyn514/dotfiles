import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmod, copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const cli = process.env.PI_LINK_TEST_CLI || fileURLToPath(new URL("../bin/pi-link.mjs", import.meta.url));
const fakePi = fileURLToPath(new URL("./fake-pi.mjs", import.meta.url));
const custom = (customType, data) => ({ type: "custom", customType, data });
const legacy = (name) => custom("link-name", { name });
const saved = (name, group = "", extra = {}) => custom("link-identity", {
  name, group, nameOrigin: "agent", groupOrigin: "user", ...extra,
});

async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), "pi-link-cli-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const sessions = join(directory, "sessions");
  const bin = join(directory, "bin");
  await mkdir(sessions);
  await mkdir(bin);
  await copyFile(fakePi, join(bin, "pi"));
  await chmod(join(bin, "pi"), 0o755);
  const env = {
    ...process.env,
    PI_CODING_AGENT_DIR: join(directory, "agent"),
    PI_CODING_AGENT_SESSION_DIR: sessions,
    PATH: `${bin}${delimiter}${process.env.PATH}`,
  };
  return {
    async session(id, entries, cwd = directory) {
      const path = join(sessions, `${id}.jsonl`);
      await writeFile(path, [
        { type: "session", version: 3, id, timestamp: "2026-01-01T00:00:00.000Z", cwd },
        ...entries,
      ].map((entry) => JSON.stringify(entry)).join("\n") + "\n");
      return path;
    },
    run(...args) {
      const result = spawnSync(process.execPath, [cli, ...args], {
        cwd: directory, env, encoding: "utf8", timeout: 10_000,
      });
      assert.ifError(result.error);
      return result;
    },
  };
}

function resolved(f, name, path) {
  const result = f.run("--resolve", name);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, path);
}
function absent(f, name) {
  const result = f.run("--resolve", name);
  assert.equal(result.status, 2, result.stderr);
  assert.equal(result.stdout, "");
}
function resumed(f, name, path) {
  const result = f.run(name, "--model", "fixture-model");
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    args: ["--session", path, "--link", "--model", "fixture-model"], linkName: name,
  });
  assert.doesNotMatch(result.stderr, /Starting new session/);
}

test("identity-only sessions are listed, resolved, and resumed under their saved name", async (t) => {
  const f = await fixture(t);
  const path = await f.session("current", [saved("reviewer", "prose")]);
  const listed = f.run("--list");
  assert.equal(listed.status, 0, listed.stderr);
  assert.match(listed.stdout, /reviewer@prose/);
  resolved(f, "reviewer@prose", path);
  resumed(f, "reviewer@prose", path);
});

for (const [label, entries, name, obsolete] of [
  ["legacy then current", [legacy("old@one"), saved("latest", "two")], "latest@two", "old@one"],
  ["current then legacy", [saved("old", "one"), legacy(" latest@two ")], "latest@two", "old@one"],
  ["current then current", [saved("old", "one"), saved("latest", "two")], "latest@two", "old@one"],
]) {
  test(`${label}: latest valid saved entry wins over history and session-name fallback`, async (t) => {
    const f = await fixture(t);
    const path = await f.session("ordered", [...entries, { type: "session_info", name: "session-fallback" }]);
    resolved(f, name, path);
    absent(f, obsolete);
    absent(f, "session-fallback");
    const listed = f.run("--list");
    assert.equal(listed.status, 0, listed.stderr);
    assert.ok(listed.stdout.includes(name), listed.stdout);
    assert.ok(!listed.stdout.includes(obsolete), listed.stdout);
    resumed(f, name, path);
  });
}

for (const [name, entry] of [
  ["reader@", saved("reader", "", { explicitGroup: true })],
  ["@", saved("", "", { explicitGroup: true })],
  ["reader@g@nested", saved("reader", "g@nested")],
  ["reader", saved("reader")],
]) {
  test(`saved spelling ${JSON.stringify(name)} reaches the launcher unchanged`, async (t) => {
    const f = await fixture(t);
    const path = await f.session("spelling", [entry]);
    resolved(f, name, path);
    resumed(f, name, path);
    if (name === "reader@") absent(f, "reader");
    if (name === "reader") absent(f, "reader@");
  });
}

const malformed = [
  legacy(" \n"),
  custom("link-name", { name: 42 }),
  { type: "message", customType: "link-name", data: { name: "forged" } },
  saved("forged", "", { nameOrigin: "unknown" }),
  saved("forged", "", { groupOrigin: "unknown" }),
  saved("forged@injected"),
  saved("forged", "", { explicitGroup: "true" }),
  custom("link-identity", null),
  custom("link-identity", { name: "forged", group: "" }),
];
test("malformed records neither select a session nor make it a listed link session", async (t) => {
  const f = await fixture(t);
  await f.session("invalid", malformed);
  absent(f, "forged");
  const listed = f.run("--list");
  assert.equal(listed.status, 0, listed.stderr);
  assert.match(listed.stdout, /No pi-link sessions found/);
});

test("malformed later entries preserve a valid saved identity or the session-name fallback", async (t) => {
  const f = await fixture(t);
  const current = await f.session("valid", [saved("kept", "review"), ...malformed]);
  const fallback = await f.session("fallback", [
    { type: "session_info", name: "before" }, ...malformed,
    { type: "session_info", name: " fallback\n name " },
  ]);
  resolved(f, "kept@review", current);
  resolved(f, "fallback name", fallback);
  absent(f, "before");
  resumed(f, "fallback name", fallback);
  const listed = f.run("--list");
  assert.equal(listed.status, 0, listed.stderr);
  assert.match(listed.stdout, /kept@review/);
  assert.doesNotMatch(listed.stdout, /fallback name/);
});

test("current identities retain cwd scope and ambiguity rejection before launching", async (t) => {
  const f = await fixture(t);
  const local = await f.session("local", [saved("shared")]);
  await f.session("foreign", [saved("shared")], "/disposable-foreign-cwd");
  resolved(f, "shared", local);
  resumed(f, "shared", local);
  const global = f.run("--resolve", "shared", "--global");
  assert.equal(global.status, 1, global.stderr);
  assert.match(global.stderr, /Multiple sessions named/);
  await f.session("duplicate", [saved("shared")]);
  for (const args of [["--resolve", "shared"], ["shared"]]) {
    const result = f.run(...args);
    assert.equal(result.status, 1, result.stderr);
    assert.equal(result.stdout, "", "ambiguous lookup must not execute even the fake Pi");
    assert.match(result.stderr, /Multiple sessions named/);
  }
});

test("a genuine miss still starts a new session through the existing handoff", async (t) => {
  const f = await fixture(t);
  const result = f.run("unseen");
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { args: ["--link"], linkName: "unseen" });
  assert.match(result.stderr, /Starting new session/);
});
