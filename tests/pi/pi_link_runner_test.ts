import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const runner = fileURLToPath(new URL("./pi_link_test.ts", import.meta.url));

function filteredRun(pattern: string) {
  // Exercise the real Bun-to-Node adapter, including its SDK asset isolation.
  // No fixture may load assets from this deliberately invalid installed path.
  const result = spawnSync(process.execPath, ["test", runner], {
    encoding: "utf8", timeout: 30_000,
    env: { ...process.env, PI_LINK_TEST_NAME_PATTERN: pattern, PI_PACKAGE_DIR: "/not-the-locked-pi-sdk" },
  });
  if (result.error) throw result.error;
  return { status: result.status, output: result.stdout + result.stderr };
}

test("pi-link native filter reaches Node and retains locked SDK assets", () => {
  const result = filteredRun("^managed child loading the configured package");
  expect(result.status).toBe(0);
  expect(result.output).toContain("# pass 1");
  expect(result.output).toContain("managed child loading the configured package registers ordinary link tools and hooks");
  expect(result.output).not.toContain("startup connects without flags");
}, 35_000);

test("pi-link native filter rejects a pattern matching no tests", () => {
  const result = filteredRun("^no-such-pi-link-test$");
  expect(result.status).not.toBe(0);
  expect(result.output).toContain('No native pi-link tests matched "^no-such-pi-link-test$"');
}, 35_000);

test("pi-link native filter reports an invalid regular expression", () => {
  const result = filteredRun("[");
  expect(result.status).not.toBe(0);
  expect(result.output).toContain("Native pi-link regression fixture failed");
  expect(result.output).toContain("Invalid regular expression");
}, 35_000);
