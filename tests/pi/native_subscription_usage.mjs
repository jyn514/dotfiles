// Run with Node, not Bun's module mocks: this checks the installed public SDK.
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
// pi-ai is import-only. Resolve its manifest via the installed SDK's search
// paths, then use its public import export rather than an internal module.
let aiPackageDir;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  const candidate = join(modulesDir, "@earendil-works/pi-ai");
  try {
    await readFile(join(candidate, "package.json"));
    aiPackageDir = candidate;
    break;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
assert.ok(aiPackageDir, "pi-ai must resolve from the installed SDK");
const aiManifest = JSON.parse(await readFile(join(aiPackageDir, "package.json"), "utf8"));
assert.equal(aiManifest.name, "@earendil-works/pi-ai");
const { InMemoryCredentialStore, fauxProvider } =
  await import(pathToFileURL(resolve(aiPackageDir, aiManifest.exports["."].import)).href);
const extensionPath = resolve(dirname(fileURLToPath(import.meta.url)),
  "../../config/pi-agent/pi-extensions/subscription-usage.ts");
const usageUrl = "https://chatgpt.com/backend-api/wham/usage";

for (const authType of ["runtime key", "fresh OAuth"]) {
  test(`native /usage resolves ${authType} and shows subscription limits without an LLM turn`, async (t) => {
    const root = await mkdtemp(join(tmpdir(), "pi-native-subscription-usage-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const cwd = join(root, "project");
    const agentDir = join(root, "agent");
    await Promise.all([mkdir(cwd), mkdir(agentDir)]);
    const account = "offline-usage-account";
    const token = ["offline-fixture", Buffer.from(JSON.stringify({
      "https://api.openai.com/auth": { chatgpt_account_id: account },
    })).toString("base64url"), "not-a-signature"].join(".");
    const reset = Date.parse("2026-10-14T12:34:00Z") / 1000;
    const reserveReset = Date.parse("2026-10-15T15:45:00Z") / 1000;
    const requests = [];
    t.mock.method(globalThis, "fetch", async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      assert.equal(url, usageUrl, "only the account-usage endpoint may be requested; no real network");
      const headers = new Headers(init?.headers);
      requests.push({ url, headers });
      assert.equal(headers.get("authorization"), `Bearer ${token}`);
      assert.equal(headers.get("chatgpt-account-id"), account);
      assert.equal(headers.get("accept"), "application/json");
      assert.equal(headers.has("x-openai-codex-luna-reserve"), false,
        "passive usage reads must not enable reserve fallback");
      assert.equal(init.redirect, "error");
      assert.ok(init.signal instanceof AbortSignal);
      return Response.json({
        rate_limit: { primary_window: { used_percent: 25, limit_window_seconds: 604800, reset_at: reset } },
        credits: { has_credits: true, unlimited: false, balance: "42.50" },
        additional_rate_limits: [{ limit_name: "gpt-reserve", rate_limit: {
          primary_window: { used_percent: 60, limit_window_seconds: 604800, reset_at: reserveReset },
        } }],
      });
    });
    const credentials = new InMemoryCredentialStore();
    assert.deepEqual(await credentials.list(), [], "no persisted or personal credentials");
    if (authType === "fresh OAuth") {
      await credentials.modify("openai-codex", async () => ({
        type: "oauth", access: token, refresh: "offline-unused-refresh",
        expires: Date.now() + 3600000, accountId: account,
      }));
    }
    const modelRuntime = await ModelRuntime.create({
      credentials, modelsPath: null, modelsStorePath: join(agentDir, "models-store.json"),
      allowModelNetwork: false, refreshOnCreate: false,
    });
    if (authType === "runtime key") await modelRuntime.setRuntimeApiKey("openai-codex", token);
    // Call through unchanged: the extension's real ModelRegistry.getProviderAuth
    // facade must reach ModelRuntime, not a fake registry or auth.json parser.
    const realGetAuth = modelRuntime.getAuth.bind(modelRuntime);
    const authCalls = [];
    t.mock.method(modelRuntime, "getAuth", async (...args) => {
      authCalls.push(args[0]);
      return realGetAuth(...args);
    });
    const faux = fauxProvider({ provider: "offline-usage-model", api: "anthropic-messages" });
    let agentStarts = 0;
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const loader = new DefaultResourceLoader({
      cwd, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: [extensionPath],
      extensionFactories: [(pi) => {
        pi.registerProvider(faux.provider);
        // The installed Codex provider is OAuth-only: a runtime API key alone
        // does not enable key auth. Configure that public auth method for this
        // fixture; the distinct fallback must lose to setRuntimeApiKey above.
        if (authType === "runtime key") {
          pi.registerProvider("openai-codex", {
            apiKey: "offline-unused-configured-key",
            headers: { "x-openai-codex-luna-reserve": "1" },
          });
        }
        pi.on("before_agent_start", () => { agentStarts++; });
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const loaded = loader.getExtensions().extensions.find((extension) => extension.path === extensionPath);
    assert.ok(loaded, "the installed loader must load the actual extension file");
    assert.equal(loaded.commands.has("usage"), true, "/usage must be registered by the loaded extension");
    const { session, extensionsResult } = await createAgentSession({
      cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager: SessionManager.inMemory(cwd), model: faux.getModel(), tools: [],
    });
    t.after(() => session.dispose());
    assert.deepEqual(extensionsResult.errors, []);
    const notifications = [];
    const extensionErrors = [];
    await session.bindExtensions({ mode: "tui", uiContext: {
      notify: (text, level) => notifications.push({ text, level }),
    }, onError: (error) => extensionErrors.push(error) });
    assert.deepEqual(session.messages, []);
    await session.prompt("/usage");
    assert.deepEqual(extensionErrors, []);
    assert.deepEqual(authCalls, ["openai-codex"], "the command uses Pi's real provider auth resolution");
    assert.equal(requests.length, 1, `exactly one account-usage request: ${JSON.stringify(notifications)}`);
    assert.equal(notifications.length, 1);
    assert.equal(notifications[0].level, "info");
    const text = notifications[0].text;
    const resetText = (timestamp) => {
      const date = new Date(timestamp * 1000);
      return `${date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} on ` +
        date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    };
    assert.deepEqual(text.split("\n").map((line) => line.trim().replace(/: +/u, ": ")), [
      `Weekly limit: [${"█".repeat(15)}${"░".repeat(5)}] 75% left (resets ${resetText(reset)})`,
      "Credits: 42.50 credits",
      `Luna Reserve Weekly limit: [${"█".repeat(8)}${"░".repeat(12)}] 40% left (resets ${resetText(reserveReset)})`,
    ], "visible notification includes weekly/reserve bars, credit balance, and each reset");
    assert.equal(text.includes(token), false);
    assert.equal(text.includes(account), false);
    assert.equal(agentStarts, 0, "a slash command must not start an LLM turn");
    assert.equal(faux.state.callCount, 0, "the selected model receives no request");
    assert.deepEqual(session.messages, [], "no user, assistant, or system LLM messages are added");
  });
}
