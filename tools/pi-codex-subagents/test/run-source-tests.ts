#!/usr/bin/env bun
/** Run this package's test phases against changed core sources, never installed Pi artifacts. */
import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const coreRoot = resolve(process.env.PI_TEST_CORE_ROOT ?? "/src/llms/pi");
// Short roots keep owned Unix sockets below the platform path-length limit.
const root = mkdtempSync(join(tmpdir(), "pi-src-"));
const defaults = [
  "source-core.test.ts", "fork.test.ts", "discovery.test.ts", "held-tool-roundtrip.test.ts", "held-tool.test.ts",
  "manager-single-suspension.test.ts", "manager-suspension.test.ts", "capture-retry.test.ts", "discard-live-child.test.ts",
  "restore-startup-failure.test.ts", "manager-link.test.ts", "link-integration.test.ts",
  "boundary-integration.test.ts",
  "parent-child-roundtrip.test.ts", "pause-exit-rpc.test.ts",
  "../handoff.test.ts", "../suspension.test.ts", "../core.test.ts", "../peek.test.ts",
].map(file => join(here, file));
try {
  // Rebase the core repository's authoritative workspace aliases, including
  // transitive agent, AI compat, TUI, and other workspace imports.
  const original = JSON.parse(readFileSync(join(coreRoot, "tsconfig.json"), "utf8"));
  const paths = Object.fromEntries(Object.entries(original.compilerOptions.paths).map(([key, values]) => [
    key, (values as string[]).map((value) => resolve(coreRoot, value)),
  ]));
  const config = join(root, "tsconfig.json");
  writeFileSync(config, JSON.stringify({ compilerOptions: { baseUrl: coreRoot, paths } }));
  const requested = process.argv.slice(2);
  const isTestPath = (value: string) => /\.test\.[cm]?[jt]sx?$/.test(value);
  const selected = requested.filter(isTestPath);
  const flags = requested.filter(value => !isTestPath(value));
  const files = selected.length ? selected.map(file => resolve(file)) : defaults;
  let failures = 0;
  for (const [index, file] of files.entries()) {
    // Separate interpreters are mandatory: legacy core.test.ts uses mock.module,
    // which would otherwise replace the SDK consumed by native integration tests.
    const owned = join(root, `p${index}`);
    const home = join(owned, "h");
    const temporary = join(owned, "t");
    mkdirSync(home, { recursive: true });
    mkdirSync(temporary);
    const env = {
      PATH: process.env.PATH ?? "",
      HOME: home,
      TMPDIR: temporary,
      XDG_CONFIG_HOME: join(home, ".config"),
      XDG_CACHE_HOME: join(home, ".cache"),
      XDG_STATE_HOME: join(home, ".local/state"),
      PI_CODING_AGENT_DIR: join(home, ".pi/agent"),
      PI_OFFLINE: "1",
      PI_SUBAGENT_TEMP_DIR: owned,
      PI_TEST_OWNED_ROOT: owned,
      PI_TEST_CORE_ROOT: coreRoot,
      PI_TEST_CORE_TSCONFIG: config,
      PI_TEST_BUN: process.execPath,
      PI_SUBAGENT_PI_BIN: join(here, "source-rpc-child.sh"),
      ...(process.env.PI_TEST_LINK_SOURCE ? { PI_TEST_LINK_SOURCE: resolve(process.env.PI_TEST_LINK_SOURCE) } : {}),
      ...(process.env.PI_TEST_COMMIT_BOUNDARY_SOURCE ? { PI_TEST_COMMIT_BOUNDARY_SOURCE: resolve(process.env.PI_TEST_COMMIT_BOUNDARY_SOURCE) } : {}),
      ...(process.env.DOTFILES_TEST_BB_REAL ? { DOTFILES_TEST_BB_REAL: process.env.DOTFILES_TEST_BB_REAL } : {}),
    };
    console.error(`\n[source tests ${index + 1}/${files.length}] ${file}`);
    const child = Bun.spawn([process.execPath, "--no-install", `--tsconfig-override=${config}`, "test", "--no-orphans", file, ...flags], {
      env, stdin: "inherit", stdout: "inherit", stderr: "inherit",
    });
    const exit = await child.exited;
    if (exit !== 0) {
      failures++;
      console.error(`[source tests] FAILED (exit ${exit}): ${file}`);
    }
  }
  console.error(`\n[source tests] ${files.length - failures}/${files.length} isolated phases passed.`);
  process.exitCode = failures ? 1 : 0;
} finally {
  rmSync(root, { recursive: true, force: true });
}
