#!/usr/bin/env node
import fs from "node:fs";

if (!process.env.RESTART_PI_RECEIPT_DIR || !process.env.TMUX_PANE) {
  console.error("restart state fixture: receipt directory and tmux pane are required");
  process.exit(2);
}
const receipt = `${process.env.RESTART_PI_RECEIPT_DIR}/pane-${process.env.TMUX_PANE.slice(1)}.json`;
fs.writeFileSync(receipt, JSON.stringify({ argv: process.argv.slice(2), cwd: process.cwd() }));
