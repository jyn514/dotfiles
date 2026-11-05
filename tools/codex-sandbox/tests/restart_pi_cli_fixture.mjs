#!/usr/bin/env node
// Forward the launcher's exact resume arguments to the installed Pi CLI.
// RPC get_state checks session identity without making a model request.
import fs from "node:fs";
import { spawn } from "node:child_process";

const child = spawn(process.execPath, [process.env.RESTART_PI_CLI,
  ...process.argv.slice(2), "--mode", "rpc", "--no-extensions", "--no-skills",
  "--no-prompt-templates", "--no-themes"], {
  stdio: ["pipe", "pipe", "pipe"],
});
let stdout = "";
let stderr = "";
let response;
let force;
const timeout = setTimeout(() => {
  child.kill("SIGTERM");
  force = setTimeout(() => child.kill("SIGKILL"), 1_000);
}, 60_000);

child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
child.stderr.on("data", data => { stderr += data; });
child.stdout.on("data", data => {
  stdout += data;
  if (response) return;
  for (const line of stdout.split("\n").slice(0, -1)) {
    try {
      const message = JSON.parse(line);
      if (message.type === "response" && message.command === "get_state") {
        response = line + "\n";
        child.kill("SIGTERM");
        force = setTimeout(() => child.kill("SIGKILL"), 1_000);
        break;
      }
    } catch {}
  }
});
child.on("error", error => {
  clearTimeout(timeout);
  process.stderr.write(`restart fixture: ${error.message}\n`);
  process.exit(1);
});
child.on("close", status => {
  clearTimeout(timeout);
  clearTimeout(force);
  if (response) {
    const receipt = process.env.RESTART_PI_RECEIPT ??
      `${process.env.RESTART_PI_RECEIPT_DIR}/pane-${process.env.TMUX_PANE.slice(1)}.jsonl`;
    fs.writeFileSync(receipt, response);
    process.stdout.write(response);
    process.stderr.write(stderr);
    process.exit(0);
  }
  process.stdout.write(stdout);
  process.stderr.write(stderr || "restart fixture: Pi did not return get_state\n");
  process.exit(status ?? 1);
});
child.stdin.end('{"type":"get_state"}\n');
