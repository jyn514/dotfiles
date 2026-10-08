// Exercise the extension through the installed Pi loader and live context getters.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
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
async function sibling(name) {
  for (const modulesDir of installedRequire.resolve.paths(name)) {
    const dir = join(modulesDir, name);
    let pkg;
    try { pkg = JSON.parse(await readFile(join(dir, "package.json"), "utf8")); }
    catch (error) { if (error.code === "ENOENT") continue; throw error; }
    assert.equal(pkg.name, name);
    return import(pathToFileURL(resolve(dir, pkg.exports?.["."]?.import ?? pkg.main)).href);
  }
  throw new Error(`Cannot resolve ${name} from installed Pi`);
}
const { InMemoryCredentialStore, fauxProvider } = await sibling("@earendil-works/pi-ai");
const { visibleWidth } = await sibling("@earendil-works/pi-tui");
const extensionPath = resolve(dirname(fileURLToPath(import.meta.url)),
  "../../config/pi-agent/pi-extensions/footer.ts");
const plain = (s) => s.replace(/\x1b\[[0-9;]*m/g, "");

// Explicit ANSI colors keep the native TUI width calculation in this regression.
const colors = { dim: "\x1b[2m", warning: "\x1b[33m", error: "\x1b[31m" };
const theme = { fg: (color, text) => colors[color] + text + "\x1b[0m" };
const usage = (cost) => ({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0,
  totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: cost } });

test("native footer keeps location/statuses and simplifies stats with live session data", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "pi-native-footer-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(process.env.HOME, "project");
  const agentDir = join(root, "agent");
  await mkdir(agentDir);
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const faux = fauxProvider({ provider: "offline-footer", api: "anthropic-messages" });
  const model = { ...faux.getModel(), id: "footer-model", reasoning: true, contextWindow: 200000 };
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [extensionPath],
    extensionFactories: [(pi) => pi.registerProvider(faux.provider)],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const manager = SessionManager.inMemory(cwd);
  manager.appendSessionInfo("footer title");
  manager.appendMessage({ role: "assistant", content: [], api: model.api,
    provider: model.provider, model: model.id, usage: usage(0.1), stopReason: "stop", timestamp: Date.now() });
  manager.appendMessage({ role: "toolResult", toolCallId: "tool", toolName: "nested",
    content: [], isError: false, timestamp: Date.now(), usage: usage(0.02) });
  manager.appendCompaction("summary", manager.getLeafId(), 100, undefined, false, usage(0.003));
  manager.branchWithSummary(manager.getLeafId(), "branch summary", undefined, false, usage(0.004));
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: manager, model, thinkingLevel: "high", tools: [],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  let context = { tokens: 48000, contextWindow: 200000, percent: 24 };
  t.mock.method(session, "getContextUsage", () => context);
  let component, branchChange, renders = 0, disposed = 0, providers = 1;
  const statuses = new Map([["z", "last\nstatus"], ["a", "first"]]);
  const errors = [];
  await session.bindExtensions({ mode: "tui", uiContext: {
    setFooter(factory) {
      component = factory({ requestRender: () => renders++ }, theme, {
        getGitBranch: () => "main", getExtensionStatuses: () => statuses,
        getAvailableProviderCount: () => providers,
        onBranchChange(callback) { branchChange = callback; return () => disposed++; },
      });
    },
  }, onError: (error) => errors.push(error) });
  assert.deepEqual(errors, []);
  assert.ok(component, "the installed application loaded and enabled the footer");
  const lines = component.render(100).map(plain);
  assert.equal(lines[0], "~/project (main) • footer title");
  assert.match(lines[1], /^24\.0%\/200k \$0\.127 +footer-model • high$/);
  assert.equal(lines[2], "first last status");
  assert.equal(lines[1].includes("auto"), false);
  assert.equal(lines[1].includes("sub"), false);
  assert.equal(visibleWidth(component.render(100)[1]), 100);

  providers = 2;
  assert.match(plain(component.render(100)[1]), /\(offline-footer\) footer-model • high$/);
  assert.equal(plain(component.render(42)[1]).includes("(offline-footer)"), false);
  await session.setModel({ ...model, id: "replacement-model" });
  assert.match(plain(component.render(100)[1]), /replacement-model • high$/);
  manager.appendSessionInfo("renamed");
  assert.equal(plain(component.render(100)[0]), "~/project (main) • renamed");
  manager.appendMessage({ role: "toolResult", toolCallId: "later", toolName: "nested",
    content: [], isError: false, timestamp: Date.now(), usage: usage(0.01) });
  assert.match(plain(component.render(100)[1]), /\$0\.137/);
  session.setThinkingLevel("off");
  assert.match(plain(component.render(100)[1]), /replacement-model • thinking off$/);
  context = { tokens: 150000, contextWindow: 200000, percent: 75 };
  assert.ok(component.render(100)[1].startsWith(colors.warning + "75.0%/200k"));
  context = { tokens: 190000, contextWindow: 200000, percent: 95 };
  assert.ok(component.render(100)[1].startsWith(colors.error + "95.0%/200k"));
  context = { tokens: null, contextWindow: 200000, percent: null };
  assert.match(plain(component.render(100)[1]), /^\?\/200k \$0\.137/);
  context = undefined;
  assert.match(plain(component.render(100)[1]), /^\?\/200k/);
  statuses.clear();
  assert.equal(component.render(100).length, 2);
  for (const width of [1, 5, 12, 20, 40, 80]) {
    assert.ok(component.render(width).every((line) => visibleWidth(line) <= width), `width ${width}`);
  }
  branchChange();
  assert.equal(renders, 1);
  component.dispose();
  assert.equal(disposed, 1);
  assert.equal(faux.state.callCount, 0, "no network/model request for footer data");
});
