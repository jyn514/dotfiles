import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const packageDir = process.env.PI_PACKAGE_DIR;
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const sdk = await import(pathToFileURL(sdkEntry).href);
const { AuthStorage } = await import(pathToFileURL(
  join(packageDir, "dist/core/auth-storage.js"),
).href);

const cwd = resolve(process.argv[2]);
const agentDir = process.env.PI_CODING_AGENT_DIR;
const credentials = AuthStorage.createDefault(process.env.PI_DASHBOARD_TRIAL_AUTH_DIR);
const modelRuntime = await sdk.ModelRuntime.create({
  credentials,
  modelsPath: null,
  modelsStorePath: join(agentDir, "models-store.json"),
});
const settingsManager = sdk.SettingsManager.create(cwd, agentDir);
const sessionManager = sdk.SessionManager.create(cwd, join(agentDir, "sessions"));
const createRuntime = async ({ cwd: runtimeCwd, sessionManager: manager, sessionStartEvent }) => {
  const services = await sdk.createAgentSessionServices({
    cwd: runtimeCwd,
    agentDir,
    settingsManager,
    modelRuntime,
  });
  const result = await sdk.createAgentSessionFromServices({
    services,
    sessionManager: manager,
    sessionStartEvent,
  });
  return { ...result, services, diagnostics: services.diagnostics };
};
const runtime = await sdk.createAgentSessionRuntime(createRuntime, {
  cwd,
  agentDir,
  sessionManager,
});
const mode = new sdk.InteractiveMode(runtime, { tuiMode: "regular" });
await mode.run();
