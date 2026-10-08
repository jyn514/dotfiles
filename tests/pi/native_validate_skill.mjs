// Run with Node: Bun's SDK module mocks must not replace either native loader.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageDir = process.env.PI_PACKAGE_DIR ?? "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
assert.equal(typeof manifest.exports?.["."]?.import, "string");
const sdkUrl = pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href;
const { discoverAndLoadExtensions, getAgentDir, loadSkills } = await import(sdkUrl);
const extension = join(root, "config/pi-agent/pi-extensions/validate-skill.ts");
const connector = join(root, "tools/codex-sandbox/tests/fixtures/local-tool-connect.py");

function skill(name) {
  return `---\nname: ${name}\ndescription: A validation fixture.\n---\n`;
}

async function eventually(predicate, worker, errors) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    assert.equal(worker.exitCode, null, errors());
    await new Promise(resolveDelay => setTimeout(resolveDelay, 20));
  }
  throw new Error(`worker did not start: ${errors()}`);
}

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

async function loadTool(cwd) {
  const loaded = await discoverAndLoadExtensions([extension], cwd, join(cwd, "agent"));
  assert.deepEqual(loaded.errors, []);
  const tool = loaded.extensions[0]?.tools.get("validate_skill")?.definition;
  assert.ok(tool, "the installed Pi must load the actual validation extension");
  return tool;
}

async function check(tool, cwd, path, signal) {
  const result = await tool.execute("validation-test", { path }, signal, undefined, { cwd });
  assert.deepEqual(JSON.parse(result.content[0].text), JSON.parse(JSON.stringify(result.details)));
  return result.details;
}

// The worker and connector are real production code. Only the host's filesystem
// view for one absolute path is mocked; this models two namespaces without
// requiring privileged mount operations. A separate process retains the real
// guest file and native SDK. This is not a container mount conformance test.
test("native validation routes guest paths through the worker, without host fallback", async t => {
  const directory = await mkdtemp(join(tmpdir(), "native-validate-skill-"));
  const host = join(directory, "host");
  const guest = join(directory, "guest");
  const guestHome = join(directory, "guest-home");
  await Promise.all([host, guest, guestHome].map(path => mkdir(path)));
  const target = join(guest, "SKILL.md");
  await writeFile(join(host, "SKILL.md"), skill("host-skill"));
  await writeFile(target, skill("guest-skill"));
  await writeFile(join(guestHome, "SKILL.md"), skill("guest-home"));
  await symlink(target, join(guest, "alias.md"));
  const socket = join(directory, "worker.sock");
  const worker = spawn(process.execPath, [join(root, "tools/codex-sandbox/image/tool-worker.mjs")], {
    cwd: guest,
    env: { ...process.env, HOME: guestHome, CODEX_SANDBOX_TOOL_SOCKET: socket,
      CODEX_SANDBOX_PI_TOOL_MODULE: sdkUrl },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let errors = "";
  worker.stderr.on("data", chunk => { errors += chunk; });
  t.after(async () => {
    if (worker.exitCode === null && worker.signalCode === null) {
      const exit = once(worker, "exit");
      worker.kill();
      await exit;
    }
    await rm(directory, { recursive: true, force: true });
  });
  await eventually(() => fs.existsSync(socket), worker, () => errors);
  setEnvironment(t, {
    CODEX_SANDBOX_TOOL_CONTAINER: "local-test-worker-not-container",
    CODEX_SANDBOX_TOOL_CONNECT: connector,
    CODEX_SANDBOX_TOOL_SOCKET: socket,
  });
  const tool = await loadTool(host);

  await t.test("relative paths use worker cwd, not host session cwd", async () => {
    assert.deepEqual(await check(tool, host, "SKILL.md"), {
      loaded: true, name: "guest-skill", diagnostics: [],
    });
  });

  await t.test("the same absolute path uses the guest view, not the host view", async t => {
    const originalRead = fs.readFileSync;
    let hostReads = 0;
    t.mock.method(fs, "readFileSync", function(path, ...args) {
      if (path === target) {
        hostReads++;
        return skill("host-decoy");
      }
      return originalRead.call(this, path, ...args);
    });
    syncBuiltinESMExports();
    t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
    // Establish that the counterfactual host loader really sees a different file.
    assert.equal(loadSkills({ cwd: host, agentDir: getAgentDir(),
      skillPaths: [target], includeDefaults: false }).skills[0]?.name, "host-decoy");
    const before = hostReads;
    assert.deepEqual(await check(tool, host, target), {
      loaded: true, name: "guest-skill", diagnostics: [],
    });
    assert.equal(hostReads, before, "routed validation must not read the host file");
  });

  await t.test("path syntax and symlinks resolve in the worker", async () => {
    for (const path of ["@SKILL.md", "alias.md", "~/SKILL.md"]) {
      assert.deepEqual(await check(tool, host, path), {
        loaded: true, name: path.startsWith("~") ? "guest-home" : "guest-skill", diagnostics: [],
      });
    }
  });

  await t.test("missing and malformed files retain native guest diagnostics", async () => {
    const missing = await check(tool, host, "missing.md");
    assert.equal(missing.loaded, false);
    assert.equal(missing.diagnostics[0]?.path, join(guest, "missing.md"));
    await writeFile(target, "---\nname: [\n---\n");
    const malformed = await check(tool, host, "SKILL.md");
    assert.equal(malformed.loaded, false);
    assert.ok(malformed.diagnostics.length > 0);
    assert.equal(malformed.diagnostics[0]?.path, target);
    await writeFile(target, skill("guest-skill"));
  });

  await t.test("missing connector rejects instead of validating a valid host file", async t => {
    setEnvironment(t, { CODEX_SANDBOX_TOOL_CONNECT: undefined });
    await assert.rejects(check(tool, host, "SKILL.md"), /attachment is unavailable/);
  });

  await t.test("a disconnected worker rejects instead of falling back to the host", async t => {
    setEnvironment(t, { CODEX_SANDBOX_TOOL_SOCKET: join(directory, "missing.sock") });
    await assert.rejects(check(tool, host, "SKILL.md", AbortSignal.timeout(3000)), /ENOENT|ECONNREFUSED/);
  });

  await t.test("an aborted call rejects without a host result", async () => {
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(check(tool, host, "SKILL.md", controller.signal), /cancelled/);
  });
});

test("native validation keeps the local loader outside a sandbox", async t => {
  const cwd = await mkdtemp(join(tmpdir(), "native-local-skill-"));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  setEnvironment(t, { CODEX_SANDBOX_TOOL_CONTAINER: undefined });
  await writeFile(join(cwd, "SKILL.md"), skill("local-skill"));
  const tool = await loadTool(cwd);
  assert.deepEqual(await check(tool, cwd, "SKILL.md"), {
    loaded: true, name: "local-skill", diagnostics: [],
  });
});
