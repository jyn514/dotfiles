#!/usr/bin/env node

import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { createInterface } from "node:readline";

if (process.argv.includes("--version")) {
  console.log("codex-cli fixture-1");
  process.exit(0);
}

const home = process.env.CODEX_HOME;
mkdirSync(home, { recursive: true });
const mode = process.env.PI_IMPORT_FIXTURE_MODE;
const state = join(home, "fixture-thread.json");
appendFileSync(join(home, "fixture-pids.jsonl"), JSON.stringify(process.pid) + "\n");
const lines = createInterface({ input: process.stdin });
let diagnosticChunks;
lines.on("line", async line => {
  const request = JSON.parse(line);
  if (request.method === undefined) return;
  appendFileSync(join(home, "fixture-requests.jsonl"), JSON.stringify(request) + "\n");
  if (mode === "stderr") {
    if (request.method === "fixture/stderr") diagnosticChunks = request.params.chunks.slice();
    else if (request.method !== "fixture/next-stderr") throw new Error("unexpected stderr fixture request");
    const chunk = Buffer.from(diagnosticChunks.shift(), "base64");
    const last = diagnosticChunks.length === 0;
    process.stderr.write(chunk, () => { if (last) process.exit(7); });
    return;
  }
  if (request.id === undefined) return;
  const reply = result => process.stdout.write(JSON.stringify({ id: request.id, result }) + "\n");
  const reject = () => process.stdout.write(JSON.stringify({ id: request.id,
    error: { code: -32600, message: "fixture rejected import" } }) + "\n");
  if (request.method === "initialize") {
    // Server and client request IDs are independent; this must not resolve initialize.
    process.stdout.write(JSON.stringify({ id: request.id, method: "fixture/question", params: {} }) + "\n");
    reply({});
  } else if (request.method === "thread/resume") {
    if (mode === "reject" || (mode === "reopen-error" && !request.params.history)) { reject(); return; }
    if (mode === "eof") { process.exit(7); }
    if (mode === "malformed") { process.stdout.write("not json\n"); return; }
    if (mode === "stall") { setInterval(() => {}, 1000); return; }
    if (request.params.history) {
      const thread = { id: randomUUID(), path: join(home, "owned-rollout.jsonl"), indexed: false, config: request.params.config };
      const records = [{ type: "session_meta", ordinal: 0,
        payload: { id: mode === "bad-rollout" ? "different-thread" : thread.id, history_mode: "paginated" } },
      ...request.params.history.map((payload, index) => ({ type: "response_item", ordinal: index + 1, payload }))];
      writeFileSync(thread.path, records.map(record => JSON.stringify(record) + "\n").join(""));
      writeFileSync(state, JSON.stringify(thread));
      reply({ thread });
    } else reply({ thread: JSON.parse(readFileSync(state)) });
  } else if (request.method === "thread/name/set") {
    if (mode === "index-update-error") { reject(); return; }
    const thread = JSON.parse(readFileSync(state));
    if (request.params.threadId !== thread.id) throw new Error("named an unrelated thread");
    thread.name = request.params.name;
    thread.indexed = mode !== "missing-index";
    writeFileSync(state, JSON.stringify(thread));
    reply({});
  } else if (request.method === "thread/read") {
    const thread = JSON.parse(readFileSync(state));
    const records = readFileSync(thread.path, "utf8").trim().split("\n").map(line => JSON.parse(line));
    const items = records.filter(record => record.payload?.type === "item_completed").map(record => {
      const item = record.payload.item;
      if (item.type === "UserMessage") return { id: item.id, type: "userMessage", content: item.content };
      if (item.type === "AgentMessage") return { id: item.id, type: "agentMessage", text: item.content.map(block => block.text).join("") };
      return { id: item.id, type: "dynamicToolCall", tool: item.tool, arguments: item.arguments,
        success: item.success, contentItems: item.content_items };
    });
    reply({ thread: { ...thread, turns: mode === "missing-display" ? [] : [{ status: "completed", items }] } });
  } else if (request.method === "turn/start") {
    const thread = JSON.parse(readFileSync(state));
    const records = readFileSync(thread.path, "utf8").trim().split("\n").map(line => JSON.parse(line));
    const input = records.filter(record => record.type === "response_item").map(record => record.payload);
    input.push({ type: "message", role: "user", content: [{ type: "input_text", text: request.params.input[0].text }] });
    if (mode === "bad-context") input.splice(0, 1);
    const config = thread.config;
    const provider = config.model_providers[config.model_provider];
    reply({ turn: { id: "fixture-turn", status: "inProgress" } });
    if (mode === "turn-malformed") { process.stdout.write("not-json\n"); return; }
    if (mode === "turn-eof") process.exit(1);
    const response = await fetch(`${provider.base_url}/responses`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: config.model, input }) });
    await response.text();
    process.stdout.write(JSON.stringify({ method: "turn/completed", params: { threadId: thread.id,
      turn: { id: "fixture-turn", status: response.ok ? "completed" : "failed" } } }) + "\n");
  } else if (request.method === "thread/list") {
    const thread = JSON.parse(readFileSync(state));
    reply(request.params.cursor ? { data: thread.indexed ? [thread] : [], nextCursor: null } :
      { data: [{ id: "other-thread" }], nextCursor: "second-page" });
  } else {
    throw new Error(`unexpected import method: ${request.method}`);
  }
});
