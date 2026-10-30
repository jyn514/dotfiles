import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// A fresh Node process prevents other Bun suites' mock.module registrations from
// replacing Pi's loader/SDK/TUI. The native fixture owns only disposable files,
// model providers, and an ephemeral socket port (never the shared :9900 link).
test("pi-link native loader/session/WebSocket root API regressions", () => {
  const fixture = fileURLToPath(new URL("./fixtures/pi-link/native.mjs", import.meta.url));
  const environment = { ...process.env };
  // This fixture imports the locked npm SDK, so it must also use that SDK's
  // bundled assets rather than themes from the separately installed Pi build.
  delete environment.PI_PACKAGE_DIR;
  const pattern = process.env.PI_LINK_TEST_NAME_PATTERN;
  const args = ["--test", "--test-reporter=tap"];
  if (pattern) args.push(`--test-name-pattern=${pattern}`);
  args.push(fixture);
  const result = spawnSync("node", args, {
    encoding: "utf8", timeout: 90_000, env: environment,
  });
  if (result.status !== 0) {
    throw new Error(`Native pi-link regression fixture failed (${result.status}):\n${result.stdout}\n${result.stderr}\n${result.error ?? ""}`);
  }
  if (pattern) {
    // With no matches, Node emits an empty TAP plan, then reports the fixture
    // file itself as one passing test. Its exit status and pass count mislead.
    if (/^1\.\.0\r?$/m.test(result.stdout)) {
      throw new Error(`No native pi-link tests matched ${JSON.stringify(pattern)}.\n${result.stdout}`);
    }
    expect(Number(result.stdout.match(/^# pass (\d+)\r?$/m)?.[1] ?? 0)).toBeGreaterThan(0);
    process.stdout.write(result.stdout);
  } else {
    expect(result.stdout).toContain("# pass 26");
  }
  expect(result.stdout).toContain("# fail 0");
}, 100_000);
