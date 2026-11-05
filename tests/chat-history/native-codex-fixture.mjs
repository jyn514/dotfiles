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

const cases = [
  { archived: false, fork: false },
  { archived: true, fork: false },
  { archived: false, fork: true },
  { archived: true, fork: true },
];

const threads = await withClient(async client => {
  const created = [];
  for (const options of cases) {
    const { thread } = await client.request("thread/resume", {
      threadId: randomUUID(), cwd: process.cwd(), history: context.history, excludeTurns: true,
    });
    created.push({ ...options, thread });
  }
  return created;
});
for (const { thread } of threads) await appendDisplayHistory(thread, context);
await withClient(async client => {
  for (const entry of threads) {
    await client.request("thread/resume", { threadId: entry.thread.id, excludeTurns: true });
    await client.request("thread/name/set", { threadId: entry.thread.id, name: "native export regression" });
    if (entry.fork) entry.thread = (await client.request("thread/fork", { threadId: entry.thread.id })).thread;
    if (entry.archived) await client.request("thread/archive", { threadId: entry.thread.id });
  }
});
console.log(JSON.stringify(threads.map(({ archived, fork, thread }) => ({ archived, fork, id: thread.id }))));
