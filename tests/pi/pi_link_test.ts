import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// A fresh Node process prevents other Bun suites' mock.module registrations from
// replacing Pi's loader/SDK/TUI. The native fixture owns only disposable files,
// model providers, and an ephemeral socket port (never the shared :9900 link).
test("pi-link native loader/session/WebSocket reply regressions", () => {
  const fixture = fileURLToPath(new URL("./fixtures/pi-link/native.mjs", import.meta.url));
  const environment = { ...process.env };
  // This fixture imports the locked npm SDK, so it must also use that SDK's
  // bundled assets rather than themes from the separately installed Pi build.
  delete environment.PI_PACKAGE_DIR;
  const result = spawnSync("node", ["--test", "--test-reporter=tap", fixture], {
    encoding: "utf8", timeout: 90_000, env: environment,
  });
  if (result.status !== 0) {
    throw new Error(`Native pi-link regression fixture failed (${result.status}):\n${result.stdout}\n${result.stderr}\n${result.error ?? ""}`);
  }
  expect(result.stdout).toContain("# pass 7");
  expect(result.stdout).toContain("# fail 0");
}, 100_000);
