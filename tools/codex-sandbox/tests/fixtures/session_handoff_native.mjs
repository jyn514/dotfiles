import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, realpath, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider, fauxAssistantMessage, InMemoryCredentialStore } from "@earendil-works/pi-ai";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const directory = await realpath(await mkdtemp(join(tmpdir(), "pi-cd-native-")));
const previousCwd = process.cwd();
let session;
try {
  const home = join(directory, "home");
  const workspace = join(home, "src/workspace");
  await mkdir(workspace, { recursive: true });
  execFileSync(process.env.DOTFILES_TEST_JJ_REAL || "jj", ["git", "init", "--colocate", workspace], {
    cwd: directory, env: { ...process.env, HOME: home }, stdio: "pipe",
  });
  const request = join(directory, "handoff.json");
  const validator = join(directory, "validator");
  await symlink(join(root, "tools/codex-sandbox/tests/fixtures/session_handoff_validator.py"), validator);
  process.env.CODEX_SANDBOX_CD_REQUEST = request;
  process.env.CODEX_SANDBOX_CD_VALIDATE = validator;
  process.chdir(workspace);
  const agentDir = join(directory, "agent");
  await mkdir(agentDir);
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const provider = fauxProvider({ provider: "cd-native-fixture", api: "anthropic-messages" });
  provider.setResponses([fauxAssistantMessage("Still running after the failed directory switch.")]);
  const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models.json"), allowModelNetwork: false, refreshOnCreate: false });
  modelRuntime.registerNativeProvider(provider.provider);
  const loader = new DefaultResourceLoader({ cwd: workspace, agentDir, settingsManager,
    noExtensions: true, additionalExtensionPaths: [join(root, "config/pi-agent/pi-extensions/session-handoff.ts")],
    noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPrompt: "Offline directory-switch regression." });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.equal(loader.getExtensions().extensions.length, 1);
  const sessionManager = SessionManager.create(workspace, join(directory, "sessions"));
  sessionManager.appendMessage(fauxAssistantMessage("Existing conversation."));
  const sourceFile = sessionManager.getSessionFile();
  ({ session } = await createAgentSession({ cwd: workspace, agentDir, settingsManager, modelRuntime,
    resourceLoader: loader, sessionManager, model: provider.getModel(), tools: [] }));
  const notifications = [];
  let shutdowns = 0;
  await session.bindExtensions({ shutdownHandler: () => { shutdowns++; },
    uiContext: { notify: (message, level) => notifications.push({ message, level }) } });
  const sourceBefore = await readFile(sourceFile, "utf8");
  await session.prompt(`/cd ${workspace}`);
  assert.equal(await readFile(join(directory, "build-request"), "utf8"), workspace,
    "the native command must actually execute the preparation subprocess");
  assert.ok(notifications.some(({ message, level }) => level === "error" && message.includes("identity.js")));
  assert.equal(shutdowns, 0);
  await assert.rejects(stat(request), { code: "ENOENT" });
  assert.equal(await readFile(sourceFile, "utf8"), sourceBefore);
  assert.equal(sessionManager.getSessionFile(), sourceFile);
  await writeFile(join(directory, "kill-build"), "");
  await session.prompt(`/cd ${workspace}`);
  assert.ok(notifications.some(({ message, level }) => level === "error" && message.includes("did not confirm completion")));
  assert.equal(shutdowns, 0, "a signal-killed builder must not be mistaken for a successful build");
  await assert.rejects(stat(request), { code: "ENOENT" });
  assert.equal(await readFile(sourceFile, "utf8"), sourceBefore);
  await session.prompt("Continue the existing conversation.");
  assert.ok(session.messages.some((message) => message.role === "assistant" &&
    message.content.some((block) => block.type === "text" && block.text.includes("Still running"))));
  assert.equal(shutdowns, 0);
  console.log("Native /cd: failed image preparation preserves the saved conversation and accepts another turn.");
} finally {
  await session?.abort();
  session?.dispose();
  process.chdir(previousCwd);
  await rm(directory, { recursive: true, force: true });
}
