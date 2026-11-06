import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";

const sourceDir = process.env.PI_LINK_TEST_SOURCE
	?? fileURLToPath(new URL("../../../../tools/pi-link", import.meta.url));
const directory = mkdtempSync(path.join(tmpdir(), "pi-link-version-"));
try {
	const source = readFileSync(path.join(sourceDir, "index.ts"), "utf8");
	const extensionDir = path.join(directory, "extension");
	const agentDir = path.join(directory, "agent");
	const cwd = path.join(directory, "cwd");
	for (const dir of [extensionDir, agentDir, cwd]) mkdirSync(dir);
	for (const file of ["identity.ts", "identity-format.mjs", "messaging.ts", "package.json"]) {
		copyFileSync(path.join(sourceDir, file), path.join(extensionDir, file));
	}
	symlinkSync(path.join(sourceDir, "node_modules"), path.join(extensionDir, "node_modules"), "dir");
	const cases = [
		["0.84.2", true],
		["0.84.4", true],
		["1.5.0", true],
		["0.84.2+abcdef12", true],
		["1.5.0+abe12d3b", true],
		["1.5.0+build.123", true],
		["1.5.0+build-123", true],
		["0.84.1", false],
		["0.84.1+abcdef12", false],
		["1.5.0-rc.1", false],
		["1.5.0-rc.1+abcdef12", false],
		["1.5.0+", false],
		["1.5.0+bad..metadata", false],
		["1.5.0+bad_metadata", false],
		["1.5", false],
	];
	for (const [version, supported] of cases) {
		// Substitute only the imported host version; run the real factory and registration path.
		assert.ok(source.includes("VERSION as PI_VERSION,"));
		const extensionPath = path.join(extensionDir, `version-${version}.ts`);
		writeFileSync(extensionPath, `const PI_VERSION = ${JSON.stringify(version)};\n${source.replace("VERSION as PI_VERSION,", "")}`);
		const result = await discoverAndLoadExtensions([extensionPath], cwd, agentDir);
		assert.equal(result.extensions.length, supported ? 1 : 0, `${version}: ${JSON.stringify(result.errors)}`);
		assert.equal(result.errors.length, supported ? 0 : 1, version);
		if (!supported) assert.match(result.errors[0].error, /pi-link requires Pi >=0\.84\.2/);
	}
	console.log("pi-link host version cases passed");
} finally {
	rmSync(directory, { recursive: true, force: true });
}
