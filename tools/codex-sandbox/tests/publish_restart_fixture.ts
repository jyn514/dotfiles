import { mock } from "bun:test";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const packageDirs = process.env.PI_PACKAGE_DIR ? [process.env.PI_PACKAGE_DIR] : [
  join(homedir(), ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"),
  "/opt/agent-pi/src/packages/coding-agent",
];
const installedDir = packageDirs.find(dir => existsSync(join(dir, "package.json")));
if (!installedDir) throw new Error("Installed Pi SDK not found; set PI_PACKAGE_DIR to its package directory");
const packageDir = realpathSync(installedDir);
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const publicEntry = manifest.exports?.["."]?.import;
if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof publicEntry !== "string") {
  throw new Error(`Pi package has no supported public import export: ${packageDir}`);
}
const sdk = await import(pathToFileURL(resolve(packageDir, publicEntry)).href);
mock.module("@earendil-works/pi-coding-agent", () => sdk);
const { SessionManager } = sdk;
const { publishRestartSession } = await import("../../../config/pi-agent/pi-extensions/session-side.ts");

await publishRestartSession({ exec: async (command: string, args: string[]) => {
  // Inject another launch generation at the publication boundary, when requested.
  if (args[0] === "set-option" && process.argv[3]) {
    const replacement = spawnSync(command, ["set-option", "-p", "-t", process.env.TMUX_PANE!,
      "@codex_sandbox_restart", process.argv[3]], { encoding: "utf8" });
    if (replacement.error || replacement.status !== 0) throw replacement.error ?? Error(replacement.stderr);
  }
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.error) throw result.error;
  return { code: result.status ?? 1, stdout: result.stdout, stderr: result.stderr, killed: false };
} } as any, SessionManager.open(process.argv[2]));
console.log(JSON.stringify({ cli: resolve(packageDir, manifest.bin.pi) }));
