/** Fault injection at the native RPC transport, never a replacement session/helper. */
import { spawn } from "node:child_process";
import { existsSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { createInterface } from "node:readline";
import { CHECKPOINT_NOTIFY, checkpointRestoreResult } from "../checkpoint.ts";

const root = process.env.PI_TEST_OWNED_ROOT;
if (!root || !process.env.PI_TEST_CORE_TSCONFIG) throw new Error("Use owned source-test storage.");
const rel = relative(realpathSync(root), realpathSync(process.cwd()));
if (rel === ".." || rel.startsWith("../") || rel.startsWith("/")) throw new Error("RPC filter cwd is not owned.");
const control = join(process.cwd(), "checkpoint-transport.json");
const mode = existsSync(control) ? JSON.parse(readFileSync(control, "utf8")).result : undefined;
const child = spawn(process.env.PI_TEST_BUN!, ["--no-install", `--tsconfig-override=${process.env.PI_TEST_CORE_TSCONFIG}`,
  new URL("./source-rpc-child.ts", import.meta.url).pathname, ...process.argv.slice(2)], { env: process.env, stdio: ["pipe", "pipe", "pipe"] });
process.stdin.pipe(child.stdin);
child.stdin.on("error", () => {});
child.stderr.pipe(process.stderr);
createInterface({ input: child.stdout }).on("line", line => {
  const event = JSON.parse(line);
  if (event.type === "extension_ui_request" && event.method === "notify" && event.message?.startsWith(CHECKPOINT_NOTIFY)) {
    const result = checkpointRestoreResult(JSON.parse(event.message.slice(CHECKPOINT_NOTIFY.length)));
    if (result && mode) {
      writeFileSync(join(process.cwd(), "checkpoint-result-filtered"), String(mode));
      if (mode === "missing") return;
      if (mode === "error") {
        process.stdout.write(JSON.stringify({ type: "extension_error", extensionPath: "opaque-helper-path", event: "command", error: "Injected helper failure without a result" }) + "\n");
        return;
      }
      if (mode === "malformed") {
        event.message = CHECKPOINT_NOTIFY + JSON.stringify({ version: 1, restored: "invalid" });
        process.stdout.write(JSON.stringify(event) + "\n");
        return;
      }
    }
  }
  process.stdout.write(line + "\n");
});
child.on("error", error => { process.stderr.write(error.message + "\n"); process.exitCode = 1; });
child.on("close", code => { process.exitCode = code ?? 1; process.stdin.destroy(); });
