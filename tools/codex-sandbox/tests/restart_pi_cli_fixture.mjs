#!/usr/bin/env node
// Forward the launcher's exact resume arguments to the installed Pi CLI.
// RPC get_state checks session identity without making a model request.
import fs from "node:fs";
import { spawnSync } from "node:child_process";

const result = spawnSync(process.execPath, [process.env.RESTART_PI_CLI,
  ...process.argv.slice(2), "--mode", "rpc", "--no-extensions", "--no-skills",
  "--no-prompt-templates", "--no-themes"], {
  input: '{"type":"get_state"}\n', encoding: "utf8", timeout: 15_000,
});
if (result.error) throw result.error;
const receipt = process.env.RESTART_PI_RECEIPT ??
  `${process.env.RESTART_PI_RECEIPT_DIR}/pane-${process.env.TMUX_PANE.slice(1)}.jsonl`;
fs.writeFileSync(receipt, result.stdout);
process.stdout.write(result.stdout);
process.stderr.write(result.stderr);
process.exit(result.status ?? 1);
