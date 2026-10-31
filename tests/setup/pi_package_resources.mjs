import assert from "node:assert/strict";
import { readFileSync, realpathSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const sdk = realpathSync(process.env.PI_PACKAGE_DIR);
const manifest = JSON.parse(readFileSync(join(sdk, "package.json"), "utf8"));
const { DefaultPackageManager, DefaultResourceLoader, SettingsManager, discoverAndLoadExtensions } =
    await import(pathToFileURL(resolve(sdk, manifest.exports["."].import)).href);
const agentDir = process.argv[2];
const cwd = process.argv[3];
const settingsManager = SettingsManager.create(cwd, agentDir);
const packages = new DefaultPackageManager({ cwd: agentDir, agentDir, settingsManager });
for (const entry of settingsManager.getPackages()) {
    const source = typeof entry === "string" ? entry : entry.source;
    await packages.install(source);
    assert.ok(packages.getInstalledPath(source, "user"), source);
}
const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager, noContextFiles: true, noThemes: true,
});
await loader.reload();
const { extensions, errors } = loader.getExtensions();
assert.deepEqual(errors, []);
for (const name of ["pi-codex-goal", "pi-session-search", "pi-codex-subagents"]) {
    assert.ok(extensions.some(extension => realpathSync(extension.path).startsWith(
        realpathSync(join(agentDir, "packages", name)) + "/")), name);
}
const toolNames = extensions.flatMap(extension => [...extension.tools.keys()]);
for (const name of ["search_sessions", "read_session", "create_goal", "get_goal", "update_goal"]) {
    assert.ok(toolNames.includes(name), name);
}
assert.ok(loader.getPrompts().prompts.some(prompt => prompt.name === "create-goal"));
assert.equal(loader.getSkills().skills.filter(skill =>
    realpathSync(skill.filePath).startsWith(
        realpathSync(join(agentDir, "packages/pi-codex-subagents")) + "/")).length, 0);
// The public entry defers implementation until session_start. Load the factory
// separately to check its runtime peers without starting a session or child.
const subagents = await discoverAndLoadExtensions([
    join(agentDir, "packages/pi-codex-subagents/implementation.ts"),
], cwd, agentDir);
assert.deepEqual(subagents.errors, []);
assert.ok(subagents.extensions[0].tools.has("spawn_agent"));
console.log("portable packages: local install, Pi peers, tools, goal prompt, subagent factory");
