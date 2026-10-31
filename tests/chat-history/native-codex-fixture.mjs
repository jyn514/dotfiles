// Create an owned synthetic import through the same native path as pi-to-codex.
import { randomUUID } from "node:crypto";
import { CodexClient, appendDisplayHistory, convertMessages } from "../../tools/pi-to-codex/importer.mjs";

const context = convertMessages([
  { role: "user", content: "imported summary" },
  { role: "assistant", content: [{ type: "text", text: "model-only" }] },
  { role: "user", content: "repeat" },
  { role: "assistant", content: [{ type: "text", text: "done" }] },
  { role: "user", content: "repeat" },
  { role: "assistant", content: [{ type: "text", text: "done" }] },
]);
// UI history and model context are distinct authorities. The exporter must use UI items.
context.display = context.display.filter(item => item.content?.[0]?.text !== "model-only");

async function withClient(work) {
  const client = new CodexClient();
  try { await client.initialize(); return await work(client); }
  finally { await client.close(); }
}

let thread = await withClient(async client => (await client.request("thread/resume", {
  threadId: randomUUID(), cwd: process.cwd(), history: context.history, excludeTurns: true,
})).thread);
await appendDisplayHistory(thread, context);
await withClient(async client => {
  await client.request("thread/resume", { threadId: thread.id, excludeTurns: true });
  await client.request("thread/name/set", { threadId: thread.id, name: "native export regression" });
  if (process.argv.includes("--fork")) {
    thread = (await client.request("thread/fork", { threadId: thread.id })).thread;
  }
  if (process.argv.includes("--archived")) await client.request("thread/archive", { threadId: thread.id });
});
console.log(JSON.stringify({ id: thread.id }));
