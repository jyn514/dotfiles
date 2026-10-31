// Run with Node, not Bun's module mocks: this checks the installed public SDK
// and a real stdio subprocess through the actual /usage command.
import assert from "node:assert/strict";
import { chmod, copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } =
  await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
let aiPackageDir;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  const candidate = join(modulesDir, "@earendil-works/pi-ai");
  try { await readFile(join(candidate, "package.json")); aiPackageDir = candidate; break; }
  catch (error) { if (error.code !== "ENOENT") throw error; }
}
assert.ok(aiPackageDir, "pi-ai must resolve from the installed SDK");
const aiManifest = JSON.parse(await readFile(join(aiPackageDir, "package.json"), "utf8"));
const { InMemoryCredentialStore, fauxProvider } =
  await import(pathToFileURL(resolve(aiPackageDir, aiManifest.exports["."].import)).href);
const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = resolve(here, "../../config/pi-agent/pi-extensions/subscription-usage.ts");
const fixturePath = join(here, "fixtures/subscription-usage-server.mjs");
const payloadPath = join(here, "fixtures/subscription-usage.json");

function env(t, key, value) {
  const old = process.env[key];
  process.env[key] = value;
  t.after(() => { if (old === undefined) delete process.env[key]; else process.env[key] = old; });
}

async function setup(t, scenario = "success") {
  const root = await mkdtemp(join(tmpdir(), "pi-native-subscription-usage-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "project");
  const agentDir = join(root, "agent");
  const bin = join(root, "bin");
  await Promise.all([mkdir(cwd), mkdir(agentDir), mkdir(bin)]);
  await copyFile(fixturePath, join(bin, "codex"));
  await chmod(join(bin, "codex"), 0o755);
  const trace = join(root, "trace.jsonl");
  env(t, "PATH", `${bin}:${process.env.PATH}`);
  env(t, "USAGE_FIXTURE_PAYLOAD", payloadPath);
  env(t, "USAGE_FIXTURE_TRACE", trace);
  env(t, "USAGE_FIXTURE_SCENARIO", scenario);
  t.mock.method(globalThis, "fetch", async () => { throw new Error("No direct network or Pi-token requests allowed"); });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const faux = fauxProvider({ provider: "offline-usage-model", api: "anthropic-messages" });
  let agentStarts = 0;
  let commandContext;
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [extensionPath],
    extensionFactories: [(pi) => {
      pi.registerProvider(faux.provider);
      pi.registerCommand("capture-usage-context", { handler: async (_args, ctx) => { commandContext = ctx; } });
      pi.on("before_agent_start", () => { agentStarts++; });
    }],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const loaded = loader.getExtensions().extensions.find((extension) => extension.path === extensionPath);
  assert.ok(loaded?.commands.has("usage"), "the installed loader loads and registers the actual extension");
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: SessionManager.inMemory(cwd), model: faux.getModel(), tools: [],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  t.mock.method(modelRuntime, "getAuth", () => { throw new Error("Pi model credentials must not be accessed"); });
  const notifications = [];
  const extensionErrors = [];
  await session.bindExtensions({ mode: "tui", uiContext: {
    notify: (text, level) => notifications.push({ text, level }),
  }, onError: (error) => extensionErrors.push(error) });
  return {
    root, session, trace, notifications, extensionErrors,
    context: () => commandContext,
    checkNoModelTurn() {
      assert.equal(agentStarts, 0);
      assert.equal(faux.state.callCount, 0);
      assert.deepEqual(session.messages, []);
    },
  };
}

async function rows(trace) {
  return (await readFile(trace, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
}
function assertGone(pid) {
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" }, "the command must reap its subprocess before returning");
}

const resetText = (timestamp) => {
  const date = new Date(timestamp * 1000);
  return `${date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} on ` +
    date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};

test("native /usage launches host Codex, shows the multi-bucket result once, and makes no model turn", async (t) => {
  const fixture = await setup(t);
  await fixture.session.prompt("/usage extra");
  assert.deepEqual(fixture.notifications, [{ text: "Usage: /usage (no arguments)", level: "warning" }]);
  await assert.rejects(readFile(fixture.trace), { code: "ENOENT" });
  fixture.notifications.length = 0;
  await fixture.session.prompt("/usage");
  assert.deepEqual(fixture.extensionErrors, []);
  assert.equal(fixture.notifications.length, 1);
  assert.equal(fixture.notifications[0].level, "info");
  assert.deepEqual(fixture.notifications[0].text.split("\n").map((line) => line.trim().replace(/: +/u, ": ")), [
    "Codex-account usage",
    `Weekly limit: [${"█".repeat(19)}░] 96% left (resets ${resetText(1791970680)})`,
    "Credits: 62500 credits",
    `Luna Reserve Weekly limit: [${"█".repeat(20)}] 100% left (resets ${resetText(1792001400)})`,
  ]);
  assert.equal(fixture.notifications[0].text.includes("private-"), false);
  const requests = await rows(fixture.trace);
  assert.deepEqual(requests[0].args, ["app-server"]);
  assert.deepEqual(requests.filter((row) => row.method).map((row) => row.method), [
    "initialize", "initialized", "account/rateLimits/read",
  ]);
  assert.deepEqual(requests.find((row) => row.method === "account/rateLimits/read").params, { excludeResetCreditDetails: true });
  assertGone(requests[0].pid);
  fixture.checkNoModelTurn();
});

for (const scenario of ["rpc-auth", "rpc-private", "invalid-json"]) {
  test(`native /usage reports ${scenario} safely and reaps its subprocess`, async (t) => {
    const fixture = await setup(t, scenario);
    await fixture.session.prompt("/usage");
    assert.deepEqual(fixture.extensionErrors, []);
    assert.equal(fixture.notifications.length, 1);
    assert.equal(fixture.notifications[0].level, "error");
    assert.equal(fixture.notifications[0].text.includes("private-"), false);
    if (scenario === "rpc-auth") assert.match(fixture.notifications[0].text, /codex login on the host/u);
    assertGone((await rows(fixture.trace))[0].pid);
    fixture.checkNoModelTurn();
  });
}

for (const invalidated of [false, true]) {
  test(`native /usage resolves UI ownership after the subprocess completes (invalidated=${invalidated})`, async (t) => {
    const fixture = await setup(t, "hold");
    const release = join(fixture.root, "release");
    env(t, "USAGE_FIXTURE_RELEASE", release);
    await fixture.session.prompt("/capture-usage-context");
    const pending = fixture.session.prompt("/usage");
    // Release even if an assertion fails, so the test does not leave a process waiting.
    try {
      const deadline = Date.now() + 5000;
      while (true) {
        try { if ((await readFile(fixture.trace, "utf8")).includes('"method":"account/rateLimits/read"')) break; }
        catch (error) { if (error.code !== "ENOENT") throw error; }
        assert.ok(Date.now() < deadline, "the fixture must receive the usage request");
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      let nativeGuardError;
      if (invalidated) {
        fixture.session.dispose();
        try { void fixture.context().ui; } catch (error) { nativeGuardError = error; }
        assert.ok(nativeGuardError instanceof Error, "Pi must reject outgoing context access");
      }
      await writeFile(release, "ready");
      await pending;
      if (invalidated) {
        assert.deepEqual(fixture.notifications, []);
        assert.deepEqual(fixture.extensionErrors, [{
          extensionPath: "command:usage", event: "command", error: nativeGuardError.message,
        }]);
      } else {
        assert.equal(fixture.notifications.length, 1);
        assert.equal(fixture.notifications[0].level, "info");
        assert.deepEqual(fixture.extensionErrors, []);
      }
      assertGone((await rows(fixture.trace))[0].pid);
      fixture.checkNoModelTurn();
    } finally {
      await writeFile(release, "ready");
      await pending;
    }
  });
}
