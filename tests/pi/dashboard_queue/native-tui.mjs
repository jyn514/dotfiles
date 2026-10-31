import assert from "node:assert/strict";
import { appendFileSync, existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const packageDir = process.env.PI_PACKAGE_DIR;
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const sdk = await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
let ai;
for (const directory of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  try {
    const root = join(directory, "@earendil-works/pi-ai");
    const metadata = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
    ai = await import(pathToFileURL(resolve(root, metadata.exports["."].import)).href);
    break;
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}
assert.ok(ai, "installed Pi AI public export required");
const log = (type, data = {}) => appendFileSync(process.env.PROBE_EVENTS, JSON.stringify({ type, at: Date.now(), ...data }) + "\n");
process.on("uncaughtException", error => { log("uncaught", { stack: error.stack }); process.exit(1); });
process.on("unhandledRejection", error => { log("unhandled", { message: String(error), stack: error?.stack }); process.exit(1); });
const cwd = process.env.PROBE_WORKSPACE;
const agentDir = process.env.PI_CODING_AGENT_DIR;
mkdirSync(agentDir, { recursive: true });
const questions = [
  { title: "Literal queue option", question: "Choose a literal option.\nCancel is an answer, not cancellation.", options: ["Cancel", "Keep"] },
  { title: "Multiline queue answer", question: "Give two lines of free text.", options: ["Preset"] },
  { title: "Native terminal answer", question: "Answer this one through the unchanged Alt+A panel." },
  { title: "Obsolete queue question", question: "The model must cancel only this question.", options: ["Obsolete"] },
];
const faux = ai.fauxProvider({ provider: "dashboard-queue-regression" });
let calls = 0;
const response = (context, content, tool = false) => {
  log("provider-request", { index: ++calls, messages: context.messages });
  return ai.fauxAssistantMessage(content, tool ? { stopReason: "toolUse" } : {});
};
faux.setResponses([
  context => response(context, ai.fauxToolCall("ask_user", { questions }), true),
  context => {
    const queued = context.messages.findLast(message => message.role === "toolResult" && message.toolName === "ask_user");
    assert.ok(queued && !queued.isError, "the real ask_user tool must succeed in TUI mode");
    const ids = JSON.stringify(queued.content).match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g);
    assert.equal(ids?.length, 4, "real tool returns four immediate queue IDs");
    log("queue-ids", { ids });
    return response(context, ai.fauxToolCall("cancel_ask_user", { question_ids: [ids[3]] }), true);
  },
  context => response(context, "INDEPENDENT_WORK_COMPLETED_WITH_PENDING_QUESTIONS"),
  ...Array.from({ length: 3 }, () => context => response(context, "REAL_QUEUE_STEERING_RECEIVED")),
]);
// Read the persisted global package declaration and its machine-local symlink,
// exactly as normal reload does. No explicit bridge path or extension bypass.
const settingsManager = sdk.SettingsManager.create(cwd, agentDir);
const resourceLoaderOptions = {
  noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
  extensionFactories: [pi => pi.registerProvider(faux.provider)],
  systemPrompt: "Disposable offline integration regression. No external services.",
};
if (process.argv.includes("--probe-core-package")) {
  const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager, ...resourceLoaderOptions });
  await loader.reload();
  const errors = loader.getExtensions().errors;
  log("core-package-load", { errors });
  if (errors.length > 0) {
    assert.match(JSON.stringify(errors), /pi-dashboard-shared[^\n]*config\.js|shared\/config\.js/);
  }
  writeFileSync(process.env.PROBE_INFO, JSON.stringify({ loaded: errors.length === 0, errors }, null, 2));
  process.exit(0);
}
const modelRuntime = await sdk.ModelRuntime.create({
  credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
  modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
});
let loadedExtensionPaths = [];
const createRuntime = async ({ cwd, sessionManager, sessionStartEvent }) => {
  const services = await sdk.createAgentSessionServices({
    cwd, agentDir, settingsManager, modelRuntime,
    resourceLoaderOptions,
  });
  const loaded = services.resourceLoader.getExtensions();
  loadedExtensionPaths = loaded.extensions.map(extension => extension.path);
  log("extension-load", { errors: loaded.errors, paths: loadedExtensionPaths });
  assert.deepEqual(loaded.errors, []);
  const publicPackageRoot = realpathSync(join(agentDir, "pi-dashboard"));
  const publicManifest = JSON.parse(readFileSync(join(publicPackageRoot, "package.json"), "utf8"));
  assert.equal(publicManifest.name, "@blackbelt-technology/pi-dashboard-extension");
  for (const entry of publicManifest.pi.extensions) {
    const declared = realpathSync(resolve(publicPackageRoot, entry));
    assert.ok(loadedExtensionPaths.some(path => existsSync(path) && realpathSync(path) === declared),
      "the public resource loader must discover the bridge from the persisted package declaration");
  }
  const result = await sdk.createAgentSessionFromServices({
    services, sessionManager, sessionStartEvent, model: faux.getModel(), tools: ["ask_user", "cancel_ask_user"],
  });
  return { ...result, services, diagnostics: services.diagnostics };
};
const manager = sdk.SessionManager.create(cwd, join(agentDir, "sessions"));
manager.appendSessionInfo("Dashboard queue regression");
const runtime = await sdk.createAgentSessionRuntime(createRuntime, { cwd, agentDir, sessionManager: manager });
runtime.session.subscribe(event => {
  if (["message_end", "agent_start", "agent_end", "agent_settled", "tool_execution_start", "tool_execution_end"].includes(event.type)) {
    log("pi-event", { event });
  }
});
writeFileSync(process.env.PROBE_INFO, JSON.stringify({
  sessionId: manager.getSessionId(), sessionFile: manager.getSessionFile(), sdk: sdkEntry,
  entrypoint: "public SDK InteractiveMode on real PTY (not bin/pi or HostPiOwner)",
  registration: { settings: join(agentDir, "settings.json"), packages: settingsManager.getPackages(), loadedExtensions: loadedExtensionPaths }, pid: process.pid,
}, null, 2));
const mode = new sdk.InteractiveMode(runtime, {
  initialMessage: "Queue all four questions, cancel the obsolete one, then finish independent work without waiting for answers.",
  tuiMode: "regular",
});
process.on("SIGTERM", () => process.exit(0));
await mode.run();
