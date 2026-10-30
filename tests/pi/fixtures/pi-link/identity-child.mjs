// A real child process receives the same inherited environment as the manager's
// spawn path. Keep all session state disposable and use no network/model calls.
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession, DefaultResourceLoader, initTheme, ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider, InMemoryCredentialStore } from "@earendil-works/pi-ai";

initTheme("dark", false);
const directory = await mkdtemp(join(tmpdir(), "pi-link-child-identity-"));
let session;
try {
  const agentDir = join(directory, "agent");
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
  const provider = fauxProvider({ provider: "child-identity", api: "anthropic-messages" });
  const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(directory, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
  modelRuntime.registerNativeProvider(provider.provider);
  const loader = new DefaultResourceLoader({ cwd: directory, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [process.argv[2]], systemPrompt: "Offline identity fixture." });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const sessionManager = SessionManager.inMemory(directory);
  sessionManager.appendCustomEntry("link-active", { active: false });
  ({ session } = await createAgentSession({ cwd: directory, agentDir, settingsManager, modelRuntime,
    resourceLoader: loader, sessionManager, model: provider.getModel() }));
  await session.bindExtensions({ onError(error) { throw error; } });
  const runner = session.extensionRunner;
  const result = await runner.getToolDefinition("link_set_identity").execute("inspect", {}, undefined, undefined, runner.createContext());
  console.log(JSON.stringify({ ...result.details, sessionName: sessionManager.getSessionName(),
    handoff: JSON.parse(process.env.PI_LINK_PARENT_IDENTITY) }));
} finally {
  if (session) {
    await session.extensionRunner.emit({ type: "session_shutdown" });
    session.dispose();
  }
  await rm(directory, { recursive: true, force: true });
}
