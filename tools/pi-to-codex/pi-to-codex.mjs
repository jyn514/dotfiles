#!/usr/bin/env node

import { spawn, execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { mkdtemp, open, readFile, rm, stat } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs, promisify } from "node:util";

const execute = promisify(execFile);
const usage = `usage: pi-to-codex FILE_OR_SESSION_ID [--cwd DIRECTORY]

Import the selected Pi branch, text tool calls, and compacted context into Codex.
Prints the new thread ID and resume command; does not make a model request.
Requires Node, the installed Pi SDK, cp, cmp, and Codex (tested with 0.162.1).
Uses unstable Codex history injection and its internal paginated rollout format.
Accepts an exact Pi session UUID; existing paths take precedence.
`;

export async function loadPi() {
  const candidates = process.env.PI_PACKAGE_DIR ? [process.env.PI_PACKAGE_DIR] : [
    join(homedir(), ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"),
    "/opt/agent-pi/src/packages/coding-agent",
  ];
  const found = candidates.find(directory => existsSync(join(directory, "package.json")));
  if (!found) throw new Error("installed Pi SDK not found; set PI_PACKAGE_DIR to its package directory");
  const directory = realpathSync(found);
  const manifest = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
  const entry = manifest.exports?.["."]?.import;
  if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof entry !== "string") {
    throw new Error("installed Pi SDK has no public root import export");
  }
  const sdk = await import(pathToFileURL(resolve(directory, entry)).href);
  if (typeof sdk.SessionManager?.open !== "function" || typeof sdk.convertToLlm !== "function") {
    throw new Error("installed Pi SDK lacks SessionManager.open or convertToLlm");
  }
  return sdk;
}

export async function resolveSessionSource(source, signal) {
  const path = resolve(source);
  try {
    await stat(path);
    return path;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(source)) {
    throw new Error(`Pi session file not found: ${path}`);
  }
  const sdk = await loadPi();
  const matches = (await sdk.SessionManager.listAll(undefined, signal))
    .filter(session => session.id.toLowerCase() === source.toLowerCase());
  if (!matches.length) throw new Error(`Pi session ID not found: ${source}`);
  if (matches.length > 1) {
    throw new Error(`Pi session ID ${source} matches multiple files; pass a path:\n${matches.map(session => session.path).join("\n")}`);
  }
  return matches[0].path;
}

function textBlocks(content) {
  if (typeof content === "string") return [{ type: "text", text: content }];
  if (!Array.isArray(content) || content.some(block => block.type !== "text" || typeof block.text !== "string")) {
    throw new Error("only text content is supported; images and unknown content blocks cannot be imported");
  }
  return content;
}

export function convertMessages(messages) {
  const history = [];
  const display = [];
  const addDisplay = item => {
    const displayed = { id: `pi_item_${display.length}`, ...item };
    display.push(displayed);
    return displayed;
  };
  const calls = new Map();
  // Reserve source IDs before assigning replacements, including calls seen later.
  const reservedIds = new Set(messages.filter(message => message.role === "assistant" && Array.isArray(message.content))
    .flatMap(message => message.content.filter(block => block.type === "toolCall").map(block => block.id)));
  let nextCall = 0;
  let omittedReasoning = 0;
  let omittedSystem = 0;
  let visibility;
  for (const message of messages) {
    if (message.role === "system") {
      // Pi persists prompts (including compaction snapshots); Codex owns instructions.
      omittedSystem += 1;
    } else if (message.role === "user") {
      const content = textBlocks(message.content).map(block => ({ type: "input_text", text: block.text }));
      history.push({ type: "message", role: "user", content });
      addDisplay({ type: "UserMessage", content: content.map(block => ({ type: "text", text: block.text, text_elements: [] })) });
      const text = content.map(block => block.text).join("\n");
      if (visibility === undefined && text.trim()) visibility = text;
    } else if (message.role === "assistant") {
      if (!Array.isArray(message.content)) throw new Error("assistant content must be an array");
      let content = [];
      const flush = () => {
        if (content.length) {
          history.push({ type: "message", role: "assistant", content });
          addDisplay({ type: "AgentMessage", content: content.map(block => ({ type: "Text", text: block.text })) });
        }
        content = [];
      };
      for (const block of message.content) {
        if (block.type === "text" && typeof block.text === "string") {
          content.push({ type: "output_text", text: block.text });
        } else if (block.type === "thinking") {
          omittedReasoning += 1;
        } else if (block.type === "toolCall") {
          flush();
          if (typeof block.id !== "string" || !block.id || calls.has(block.id)) {
            throw new Error(`invalid or duplicate tool-call ID: ${block.id}`);
          }
          if (typeof block.name !== "string" || !block.name || !block.arguments ||
              typeof block.arguments !== "object" || Array.isArray(block.arguments)) {
            throw new Error(`invalid tool call: ${block.id}`);
          }
          let id = block.id;
          if (id.length > 64) {
            do { id = `pi_import_${++nextCall}`; } while (reservedIds.has(id));
            reservedIds.add(id);
          }
          const displayed = addDisplay({ type: "DynamicToolCall", tool: block.name,
            arguments: block.arguments, status: "in_progress" });
          calls.set(block.id, { name: block.name, id, displayed, completed: false });
          history.push({ type: "function_call", call_id: id, name: block.name,
            arguments: JSON.stringify(block.arguments) });
        } else {
          throw new Error(`unsupported assistant content: ${block.type}`);
        }
      }
      flush();
    } else if (message.role === "toolResult") {
      const call = calls.get(message.toolCallId);
      if (!call || call.completed || call.name !== message.toolName) {
        throw new Error(`unmatched, duplicate, or misnamed tool result: ${message.toolCallId}`);
      }
      const text = textBlocks(message.content).map(block => block.text).join("\n");
      history.push({ type: "function_call_output", call_id: call.id,
        output: message.isError ? JSON.stringify({ isError: true, content: text }) : text });
      Object.assign(call.displayed, { status: message.isError ? "failed" : "completed",
        success: !message.isError, content_items: [{ type: "inputText", text }] });
      call.completed = true;
    } else {
      throw new Error(`unsupported message role: ${message.role}`);
    }
  }
  for (const [id, call] of calls) {
    if (!call.completed) throw new Error(`tool call has no result: ${id}`);
  }
  if (visibility === undefined) throw new Error("selected context has no user text for Codex's resume picker");
  return { history, display, visibility, omittedReasoning, omittedSystem };
}

export async function readSession(source, cwdOverride, signal) {
  const sdk = await loadPi();
  const temporary = await mkdtemp(join(tmpdir(), "pi-to-codex-"));
  let failure;
  try {
    const copy = join(temporary, "session.jsonl");
    await execute("cp", [resolve(source), copy], { signal });
    await execute("cmp", [resolve(source), copy], { signal });
    const entries = (await readFile(copy, "utf8")).split("\n").filter(line => line.trim()).map((line, index) => {
      try { return JSON.parse(line); }
      catch { throw new Error(`invalid JSON in source snapshot at line ${index + 1}`); }
    });
    const header = entries[0];
    if (header?.type !== "session" || !Number.isInteger(header.version) ||
        header.version < 1 || header.version > sdk.CURRENT_SESSION_VERSION) {
      throw new Error("source must start with a supported Pi session header");
    }
    // Opening an older session can rewrite it. Only the private snapshot is writable.
    const manager = sdk.SessionManager.open(copy);
    const cwd = resolve(cwdOverride ?? manager.getCwd());
    if (!(await stat(cwd)).isDirectory()) throw new Error(`destination cwd is not a directory: ${cwd}`);
    return { ...convertMessages(sdk.convertToLlm(manager.buildSessionContext().messages)), cwd };
  } catch (error) { failure = error; throw error; }
  finally {
    try { await rm(temporary, { recursive: true, force: true }); }
    catch (cleanup) {
      if (failure) failure.message += `; snapshot cleanup: ${cleanup.message}`;
      else throw cleanup;
    }
  }
}

export class CodexClient {
  constructor({ command = "codex", signal, env = process.env } = {}) {
    this.pending = new Map();
    this.nextId = 0;
    this.diagnostics = "";
    this.signal = signal;
    signal?.throwIfAborted();
    this.process = spawn(command, ["app-server", "--stdio"], { stdio: ["pipe", "pipe", "pipe"], env });
    this.exited = new Promise(resolveExit => this.process.once("close", (code, signal) => {
      this.status = { code, signal };
      this.fail(new Error(`Codex app-server exited (${code ?? signal})${this.diagnostics ? `: ${this.diagnostics.trim()}` : ""}`));
      resolveExit(this.status);
    }));
    this.process.on("error", error => this.fail(error));
    this.process.stdin.on("error", error => this.fail(error));
    this.process.stderr.setEncoding("utf8");
    this.process.stderr.on("data", chunk => { this.diagnostics = (this.diagnostics + chunk).slice(-16384); });
    this.lines = createInterface({ input: this.process.stdout });
    this.lines.on("line", line => {
      try {
        const message = JSON.parse(line);
        if (message.method !== undefined) {
          if (message.id !== undefined) this.send({ id: message.id,
            error: { code: -32601, message: "importer does not implement server requests" } });
          return;
        }
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else if (Object.hasOwn(message, "result")) pending.resolve(message.result);
        else pending.reject(new Error("Codex returned a response without a result"));
      } catch (error) { this.fail(error); }
    });
    this.abort = () => { this.fail(signal.reason); this.process.kill("SIGTERM"); };
    signal?.addEventListener("abort", this.abort, { once: true });
  }

  fail(error) {
    this.failure ??= error;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(this.failure);
    }
    this.pending.clear();
  }

  send(message) { this.process.stdin.write(JSON.stringify(message) + "\n"); }

  request(method, params) {
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex did not answer ${method} within 30 seconds`));
      }, 30000);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ id, method, params });
    });
  }

  async initialize() {
    await this.request("initialize", { clientInfo: { name: "pi_to_codex", version: "1.0.0" },
      capabilities: { experimentalApi: true } });
    this.send({ method: "initialized", params: {} });
  }

  async close() {
    this.process.stdin.end();
    let timer;
    let killTimer;
    try {
      timer = setTimeout(() => {
        this.process.kill("SIGTERM");
        killTimer = setTimeout(() => this.process.kill("SIGKILL"), 1000);
      }, 1000);
      const status = await this.exited;
      if (status.code !== 0) throw new Error(`Codex app-server did not exit cleanly (${status.code ?? status.signal})`);
    } finally {
      clearTimeout(timer);
      clearTimeout(killTimer);
      this.lines.close();
      this.signal?.removeEventListener("abort", this.abort);
    }
  }
}

async function withClient(work, signal) {
  const client = new CodexClient({ signal });
  let failure;
  try {
    await client.initialize();
    return await work(client);
  } catch (error) { failure = error; throw error; }
  finally {
    try { await client.close(); }
    catch (cleanup) {
      if (failure) failure.message += `; cleanup: ${cleanup.message}`;
      else throw cleanup;
    }
  }
}

function displayEvents(threadId, items) {
  const events = [];
  let turnId;
  const complete = () => {
    if (turnId) events.push({ type: "task_complete", turn_id: turnId, last_agent_message: null });
  };
  for (const item of items) {
    if (!turnId || item.type === "UserMessage") {
      complete();
      turnId = randomUUID();
      events.push({ type: "task_started", turn_id: turnId, model_context_window: null });
    }
    events.push({ type: "item_completed", thread_id: threadId, turn_id: turnId, item, completed_at_ms: 0 });
  }
  complete();
  return events;
}

export async function appendDisplayHistory(thread, context) {
  if (typeof thread.path !== "string" || typeof thread.id !== "string") {
    throw new Error("Codex did not return a persisted thread path and ID");
  }
  const file = await open(thread.path, "r+");
  try {
    const before = await file.stat({ bigint: true });
    const bytes = await file.readFile();
    if (!bytes.length || bytes.at(-1) !== 10) throw new Error("Codex rollout is empty or incomplete");
    const records = bytes.toString("utf8").trimEnd().split("\n").map(line => JSON.parse(line));
    const meta = records[0];
    if (meta.type !== "session_meta" || meta.payload?.id !== thread.id || meta.payload?.history_mode !== "paginated") {
      throw new Error("unsupported Codex rollout header; visibility update was not written");
    }
    let ordinal = -1;
    for (const record of records) {
      if (!Number.isSafeInteger(record.ordinal) || record.ordinal <= ordinal) {
        throw new Error("unsupported Codex rollout ordinals; visibility update was not written");
      }
      ordinal = record.ordinal;
    }
    const after = await file.stat({ bigint: true });
    if (after.size !== before.size || after.mtimeNs !== before.mtimeNs) {
      throw new Error("new Codex rollout changed before the visibility update");
    }
    // Paginated UI history reads canonical items; response_items are model context only.
    // The legacy user event separately supplies the picker's has_user_event metadata.
    const events = [{ type: "user_message", message: context.visibility, images: [], local_images: [], text_elements: [] },
      ...displayEvents(thread.id, context.display)];
    if (!Number.isSafeInteger(ordinal + events.length)) throw new Error("Codex rollout ordinal overflow");
    const timestamp = new Date().toISOString();
    const addition = Buffer.from(events.map(payload => JSON.stringify({ type: "event_msg", timestamp,
      ordinal: ++ordinal, payload }) + "\n").join(""));
    // readFile left the descriptor at EOF; writeFile completes partial writes.
    await file.writeFile(addition);
    await file.sync();
  } finally { await file.close(); }
}

async function visible(client, id) {
  let cursor = null;
  const seen = new Set();
  do {
    const page = await client.request("thread/list", { modelProviders: [], useStateDbOnly: true, limit: 100, cursor });
    if (!Array.isArray(page?.data)) throw new Error("Codex returned an invalid thread list");
    if (page.data.some(thread => thread.id === id)) return true;
    cursor = page.nextCursor;
    if (cursor !== null && cursor !== undefined && (typeof cursor !== "string" || !cursor || seen.has(cursor))) {
      throw new Error("Codex returned an invalid thread-list cursor");
    }
    seen.add(cursor);
  } while (cursor);
  return false;
}

export async function importSession(source, { cwd, signal, report = console.error } = {}) {
  const profilePath = join(process.env.CODEX_HOME || join(homedir(), ".codex"), "dotfiles.config.toml");
  // app-server rejects --profile. Its thread API accepts configuration overrides.
  const { stdout } = await execute("python3", [join(dirname(fileURLToPath(import.meta.url)), "read-profile.py"),
    profilePath], { signal });
  const config = JSON.parse(stdout);
  source = await resolveSessionSource(source, signal);
  report(`Reading selected Pi context from ${source}...`);
  const context = await readSession(source, cwd, signal);
  signal?.throwIfAborted();
  if (context.omittedSystem) report(`Omitting ${context.omittedSystem} Pi system message(s); using Codex instructions.`);
  if (context.omittedReasoning) report(`Omitting ${context.omittedReasoning} provider-specific reasoning block(s).`);
  report(`Importing into Codex in ${context.cwd}...`);
  let thread;
  let attempted = false;
  try {
    await withClient(async client => {
      attempted = true;
      const result = await client.request("thread/resume", { threadId: randomUUID(), history: context.history,
        cwd: context.cwd, config, excludeTurns: true });
      thread = result.thread;
    }, signal);
    // The fresh ID has not been published. Its sole writer must exit before
    // appending native display history and the picker's visibility event.
    signal?.throwIfAborted();
    await appendDisplayHistory(thread, context);
    await withClient(client => client.request("thread/resume", { threadId: thread.id, config, excludeTurns: true }), signal);
    // Closing the second writer flushes the reconstructed has_user_event metadata.
    await withClient(async client => {
      if (!(await visible(client, thread.id))) throw new Error("imported thread is absent from Codex's resume index");
      const result = await client.request("thread/read", { threadId: thread.id, includeTurns: true });
      const items = result.thread?.turns?.flatMap(turn => turn.items);
      if (!items || items.length !== context.display.length ||
          items.some((item, index) => item.id !== context.display[index].id)) {
        throw new Error("imported UI history does not match the selected Pi context");
      }
    }, signal);
    return { id: thread.id, items: context.history.length };
  } catch (error) {
    if (thread?.id) error.message += `; thread ${thread.id} may be partially imported; inspect it before retrying`;
    else if (attempted) error.message += "; injection may have created a thread; inspect recent Codex sessions before retrying";
    throw error;
  }
}

async function main() {
  const controller = new AbortController();
  let interrupted;
  const handlers = Object.fromEntries(["SIGINT", "SIGTERM"].map(signal => [signal, () => {
    interrupted = signal;
    controller.abort(new Error(`cancelled by ${signal}`));
  }]));
  try {
    const { values, positionals } = parseArgs({ options: { cwd: { type: "string" }, help: { type: "boolean", short: "h" } },
      allowPositionals: true });
    if (values.help) { process.stdout.write(usage); return; }
    if (positionals.length !== 1) throw new Error(usage.trim());
    for (const [signal, handler] of Object.entries(handlers)) process.on(signal, handler);
    const result = await importSession(positionals[0], { cwd: values.cwd, signal: controller.signal });
    console.log(`Imported ${result.items} history items into Codex thread ${result.id}.`);
    console.log(`Resume with: codex resume '${result.id.replaceAll("'", "'\\''")}'`);
  } catch (error) {
    console.error(`pi-to-codex: ${error.message}`);
    process.exitCode = interrupted === "SIGINT" ? 130 : interrupted === "SIGTERM" ? 143 : 1;
  } finally {
    for (const [signal, handler] of Object.entries(handlers)) process.off(signal, handler);
  }
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
