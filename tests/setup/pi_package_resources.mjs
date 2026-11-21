import assert from "node:assert/strict";
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
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
const { extensions, errors, runtime } = loader.getExtensions();
runtime.getSettings = () => ({});
assert.deepEqual(errors, []);
for (const name of ["pi-codex-goal", "pi-codex-subagents"]) {
    assert.ok(extensions.some(extension => realpathSync(extension.path).startsWith(
        realpathSync(join(agentDir, "packages", name)) + "/")), name);
}
assert.ok(!extensions.some(extension => realpathSync(extension.path).startsWith(
    realpathSync(join(agentDir, "packages/pi-session-search")) + "/")));
const toolNames = extensions.flatMap(extension => [...extension.tools.keys()]);
assert.equal(toolNames.filter(name => name === "read_session").length, 1);
assert.equal(toolNames.filter(name => name === "search_sessions").length, 1);
const reader = extensions.find(extension => extension.tools.has("read_session")).tools.get("read_session").definition;
const transcript = join(cwd, "frozen-session.jsonl");
writeFileSync(transcript, [
    JSON.stringify({ type: "session", id: "fixture", cwd, timestamp: "2026-01-01T00:00:00Z" }),
    JSON.stringify({ type: "message", timestamp: "2026-01-01T00:00:01Z", message: { role: "user", content: "installed reader fixture" } }),
].join("\n") + "\n");
const result = await reader.execute("setup-reader", { sessionFile: transcript }, undefined, undefined, { cwd });
assert.match(result.content[0].text, /installed reader fixture/);
assert.deepEqual(result.details.toolExecution, { target: "host", source: "default" });
// Existing live settings still select the original package and the bundle.
const oldSelection = await discoverAndLoadExtensions([
    join(agentDir, "pi-extensions/index.ts"), join(agentDir, "packages/pi-session-search"),
], cwd, agentDir);
assert.deepEqual(oldSelection.errors, []);
const oldTools = oldSelection.extensions.flatMap(extension => [...extension.tools.keys()]);
assert.equal(oldTools.filter(name => name === "read_session").length, 1);
assert.equal(oldTools.filter(name => name === "search_sessions").length, 1);
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
