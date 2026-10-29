import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// Native Node exercises the shipped CLI; the only launched Pi is a disposable fake.
test("pi-link CLI resolves saved identities before its launcher handoff", () => {
  const fixture = fileURLToPath(new URL("../../tools/pi-link/tests/cli_test.mjs", import.meta.url));
  const result = spawnSync("node", ["--test", "--test-reporter=tap", fixture], {
    encoding: "utf8", timeout: 30_000,
  });
  if (result.status !== 0) {
    throw new Error(`Native pi-link CLI fixture failed (${result.status}):\n${result.stdout}\n${result.stderr}\n${result.error ?? ""}`);
  }
  expect(result.stdout).toContain("# fail 0");
  expect(result.stdout).toContain("# pass 12");
}, 35_000);
