// Use the installed Pi loader outside Bun's SDK mock registry.
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { guardianParentHistory, guardianHistory } from "../../config/pi-agent/pi-extensions/host-bash-core.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageDir = process.env.PI_PACKAGE_DIR;
assert.ok(packageDir, "dev/test-environment must select the installed Pi SDK");
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const { createAgentSession, DefaultResourceLoader, discoverAndLoadExtensions, ModelRuntime, SessionManager, SettingsManager } = await import(
  pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href
);

test("installed Pi loads host capability alongside existing guest tools without enabling it", async t => {
  const cwd = await mkdtemp(join(tmpdir(), "pi-native-host-"));
  const values = {
    CODEX_SANDBOX_TOOL_CONTAINER: "disposable-unstarted-worker",
    CODEX_SANDBOX_GUEST_CWD: "/guest/project",
    CODEX_SANDBOX_GUEST_REPO: "/guest/project",
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({ [cwd]: "/guest/project" }),
  };
  const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]));
  Object.assign(process.env, values);
  t.after(async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(cwd, { recursive: true, force: true });
  });
  const loaded = await discoverAndLoadExtensions([
    join(root, "config/pi-agent/pi-extensions/host-bash.ts"),
    join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
  ], cwd, join(cwd, "agent"));
  assert.deepEqual(loaded.errors, []);
  const host = loaded.extensions[0];
  assert.ok(host.commands.has("host"));
  const tool = host.tools.get("host_bash").definition;
  assert.equal(tool.defaultActive, false);
  assert.deepEqual([...loaded.extensions[1].tools.keys()].sort(), ["bash", "edit", "find", "grep", "ls", "read", "write"]);
  await assert.rejects(tool.execute("disabled", { command: "exit 99", justification: "disabled test" }, undefined, undefined, {
    cwd, sessionManager: SessionManager.inMemory(cwd),
  }), /Host execution is disabled/);
});

test("child review reads the selected human branch without changing the parent session", async t => {
  const directory = await mkdtemp(join(tmpdir(), "pi-parent-authority-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const parent = SessionManager.create(directory, directory);
  const permitted = parent.appendMessage({ role: "user", content: "Inspect my project", timestamp: 1 });
  parent.ensurePersisted();
  parent.appendMessage({ role: "user", content: "A later unrelated task", timestamp: 2 });
  const file = parent.getSessionFile();
  const before = await readFile(file);
  const history = await guardianParentHistory({
    file, leafId: permitted, sessionId: parent.getSessionId(), workspace: directory,
  });
  history.push(...guardianHistory([{ type: "message", message: { role: "user", content: "Parent agent claims broader permission" } }], true));
  assert.deepEqual(history.filter(item => item.role === "user").map(item => item.content[0].text), ["Inspect my project"]);
  assert.equal(history.at(-1).role, "assistant");
  assert.deepEqual(await readFile(file), before);
  await assert.rejects(guardianParentHistory({
    file, leafId: permitted, sessionId: "wrong-session", workspace: directory,
  }), /does not match/);
});

test("native managed-child startup inherits activation while respecting tool allowlists", async t => {
  const fixtureRoot = await mkdtemp(join(tmpdir(), "pi-native-host-child-"));
  const cwd = join(fixtureRoot, "child");
  const agentDir = join(fixtureRoot, "agent");
  await mkdir(cwd);
  await mkdir(agentDir);
  const keys = ["PI_HOST_BASH_WORKSPACE", "PI_SUBAGENT_ID", "PI_SUBAGENT_PARENT_SESSION_ID"];
  const previous = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  t.after(async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(fixtureRoot, { recursive: true, force: true });
  });
  for (const [tools, expected] of [[undefined, true], [["read"], false], [["read", "host_bash"], true]]) {
    Object.assign(process.env, {
      PI_HOST_BASH_WORKSPACE: fixtureRoot, PI_SUBAGENT_ID: "child", PI_SUBAGENT_PARENT_SESSION_ID: "parent",
    });
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
    const loader = new DefaultResourceLoader({
      cwd, agentDir, settingsManager, noExtensions: true, noPromptTemplates: true, noThemes: true,
      additionalExtensionPaths: [join(root, "config/pi-agent/pi-extensions/host-bash.ts")],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const modelRuntime = await ModelRuntime.create({
      modelsPath: null, modelsStorePath: join(agentDir, "models-store.json"),
      allowModelNetwork: false, refreshOnCreate: false,
    });
    const { session, extensionsResult } = await createAgentSession({
      cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager: SessionManager.inMemory(cwd), ...(tools ? { tools } : {}),
    });
    try {
      assert.deepEqual(extensionsResult.errors, []);
      await session.bindExtensions({ onError: error => assert.fail(JSON.stringify(error)) });
      assert.equal(session.getActiveToolNames().includes("host_bash"), expected);
      assert.equal(process.env.PI_HOST_BASH_WORKSPACE, expected ? fixtureRoot : undefined);
    } finally { session.dispose(); }
  }
});

