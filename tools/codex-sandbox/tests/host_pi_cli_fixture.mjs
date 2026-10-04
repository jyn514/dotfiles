#!/usr/bin/env node
// Native Pi process fixture: exercise the real wrapper/launcher handoff and
// controller readiness wire without installing extensions or using credentials.
import fs from "node:fs";
import net from "node:net";

if (!process.env.FAKE_HOST_PI_READY) process.exit(Number(process.env.FAKE_AGENT_EXIT || 0));
const args = process.argv.slice(2);
const index = args.indexOf("--session");
const session = index >= 0 ? args[index + 1] : `${process.env.FAKE_HOST_PI_READY}.jsonl`;
const marker = index >= 0 ? `${session}.fixture-ready` : process.env.FAKE_HOST_PI_READY;
const info = { owner: process.env.CODEX_SANDBOX_PI_OWNER,
  attachment: process.env.CODEX_SANDBOX_PI_ATTACHMENT, session,
  container: process.env.CODEX_SANDBOX_TOOL_CONTAINER, pid: process.pid };
for (const [signal, code] of [["SIGHUP", 129], ["SIGINT", 130], ["SIGTERM", 143]]) {
  process.on(signal, () => process.exit(code));
}
const socket = net.createConnection(info.owner);
socket.on("connect", () => socket.write(`${JSON.stringify({ op: "ready", attachment: info.attachment, session })}\n`));
let buffer = "";
socket.on("data", (chunk) => {
  buffer += chunk;
  if (!buffer.includes("\n")) return;
  const answer = JSON.parse(buffer.slice(0, buffer.indexOf("\n")));
  if (!answer.ok) throw new Error(answer.error);
  socket.end();
  fs.writeFileSync(marker, JSON.stringify(info));
  if (process.env.FAKE_AGENT_BLOCK !== "1") process.exit(Number(process.env.FAKE_AGENT_EXIT || 0));
  setInterval(() => {
    if (fs.existsSync(`${session}.fixture-exit`)) process.exit(0);
  }, 30);
});
socket.on("error", (error) => { console.error(error); process.exit(2); });
