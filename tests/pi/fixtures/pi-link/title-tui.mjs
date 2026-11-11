// Exercise the public InteractiveMode with its real OSC title writer, offline.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { setImmediate as nextTurn } from "node:timers/promises";
async function publicImport(directory) {
  const manifest = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
  return import(pathToFileURL(resolve(directory, manifest.exports["."].import)).href);
}
const installed = process.env.PI_LINK_TITLE_PACKAGE_DIR;
const sdk = installed ? await publicImport(installed) : await import("@earendil-works/pi-coding-agent");
let ai;
if (installed) {
  const require = createRequire(join(installed, "package.json"));
  for (const directory of require.resolve.paths("@earendil-works/pi-ai")) {
    try { ai = await publicImport(join(directory, "@earendil-works/pi-ai")); break; }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  assert.ok(ai, "installed SDK's Pi AI package must be available");
} else ai = await import("@earendil-works/pi-ai");
const { createAgentSessionFromServices, createAgentSessionRuntime, createAgentSessionServices,
  InteractiveMode, ModelRuntime, SessionManager, SettingsManager } = sdk;
const { fauxProvider, InMemoryCredentialStore } = ai;

const directory = await mkdtemp(join(tmpdir(), "pi-link-title-tui-"));
let runtime;
try {
  const agentDir = join(directory, "agent");
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const provider = fauxProvider({ provider: "title-tui", api: "anthropic-messages" });
  const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(directory, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
  modelRuntime.registerNativeProvider(provider.provider);
  const createRuntime = async ({ cwd, sessionManager, sessionStartEvent }) => {
    const services = await createAgentSessionServices({ cwd, agentDir, settingsManager, modelRuntime,
      resourceLoaderOptions: {
        noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
        additionalExtensionPaths: [process.argv[2]], systemPrompt: "Offline terminal title regression.",
      } });
    assert.deepEqual(services.resourceLoader.getExtensions().errors, []);
    const result = await createAgentSessionFromServices({ services, sessionManager, sessionStartEvent,
      model: provider.getModel(), tools: [] });
    return { ...result, services, diagnostics: services.diagnostics };
  };
  const manager = SessionManager.inMemory(directory);
  manager.appendCustomEntry("link-active", { active: false });
  runtime = await createAgentSessionRuntime(createRuntime, { cwd: directory, agentDir, sessionManager: manager });
  const mode = new InteractiveMode(runtime, { tuiMode: "regular" });
  await mode.init();
  await nextTurn();
  const checkpoint = (phase, expected) =>
    process.stdout.write(`\nTITLE_CHECKPOINT ${JSON.stringify({ phase, expected })}\n`);
  const initialName = manager.getSessionName();
  assert.match(initialName, /^t-[a-f0-9]{4}$/);
  checkpoint("startup", initialName);

  const rename = async (name) => {
    const runner = runtime.session.extensionRunner;
    await runner.getCommand("link-name").handler(name, runner.createCommandContext());
    await nextTurn();
  };
  await rename("plain-link-name");
  checkpoint("link-rename", "plain-link-name");
  runtime.session.setSessionName("Explicit title");
  await nextTurn();
  assert.equal(manager.getSessionName(), "Explicit title");
  checkpoint("explicit-title", "plain-link-name");
  await rename("different-link-name");
  assert.equal(manager.getSessionName(), "Explicit title", "link renames preserve the saved descriptive title");
  checkpoint("preserved-title", "different-link-name");
  runtime.session.setSessionName("");
  await nextTurn();
  checkpoint("cleared-title", "different-link-name");

  await runtime.newSession({ setup: (next) => {
    next.appendCustomEntry("link-active", { active: false });
    next.appendCustomEntry("link-name", { name: "replacement-link" });
    next.appendSessionInfo("Replacement descriptive title");
  } });
  await nextTurn();
  assert.equal(runtime.session.sessionManager.getSessionName(), "Replacement descriptive title");
  checkpoint("new-session", "replacement-link");
} finally {
  if (runtime) await runtime.dispose();
  await rm(directory, { recursive: true, force: true });
}
// InteractiveMode owns stdin/UI timers until the process exits.
process.exit(0);
