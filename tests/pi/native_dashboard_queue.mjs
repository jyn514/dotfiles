// Opt-in assembled runtime: installed Pi InteractiveMode on a real PTY, the
// patched Dashboard server/bridge, real dotfiles tools and a Chromium browser.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

const enabled = process.env.DOTFILES_TEST_DASHBOARD_QUEUE === "1";
test("real queued ask_user bridges browser and terminal answers exactly once", {
  skip: enabled ? false : "opt in with DOTFILES_TEST_DASHBOARD_QUEUE=1 and explicit patched Dashboard/browser paths",
  timeout: 180_000,
}, async (t) => {
  for (const name of ["DASHBOARD_TEST_CLI", "DASHBOARD_TEST_CORE", "DASHBOARD_TEST_INSTALL", "DASHBOARD_TEST_PLAYWRIGHT", "DASHBOARD_TEST_CHROMIUM"]) {
    assert.ok(process.env[name] && existsSync(process.env[name]), `${name} must name an existing explicit prerequisite`);
  }
  assert.ok(process.env.PI_PACKAGE_DIR, "PI_PACKAGE_DIR must select the installed Pi SDK, not the locked unit-test SDK");
  const runner = join(dirname(fileURLToPath(import.meta.url)), "dashboard_queue/run.py");
  try {
    const result = await promisify(execFile)("python3", [runner], {
      env: { ...process.env, DASHBOARD_TEST_NODE: process.execPath },
      timeout: 155_000, maxBuffer: 4 * 1024 * 1024,
    });
    t.diagnostic(result.stdout);
    assert.equal(JSON.parse(result.stdout).status, "passed");
  } catch (error) {
    assert.fail(`${error.message}\n${error.stdout ?? ""}\n${error.stderr ?? ""}`);
  }
});
