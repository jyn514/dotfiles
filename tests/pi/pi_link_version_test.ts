import { test } from "bun:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

test("pi-link accepts host build metadata while preserving its version floor and prerelease rejection", () => {
	const result = spawnSync("node", [path.join(repoRoot, "tests/pi/fixtures/pi-link/version.mjs")], {
		cwd: repoRoot,
		encoding: "utf8",
		env: { ...process.env, PI_LINK_TEST_SOURCE: process.env.PI_LINK_TEST_SOURCE ?? path.join(repoRoot, "tools/pi-link") },
		timeout: 60_000,
	});
	assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}\n${result.error ?? ""}`);
}, 65_000);
