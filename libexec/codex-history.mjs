#!/usr/bin/env node
// Read Codex's displayed text history without resuming a thread or starting a turn.
import { resolve } from "node:path";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { CodexClient } from "./codex-client.mjs";

// These items are deliberately outside a user/assistant text transcript.
const nonMessageTypes = new Set([
  "hookPrompt", "functionCallOutput", "plan", "reasoning", "commandExecution", "fileChange",
  "mcpToolCall", "dynamicToolCall", "collabAgentToolCall", "subAgentActivity", "webSearch",
  "imageView", "sleep", "imageGeneration", "enteredReviewMode", "exitedReviewMode", "contextCompaction",
]);

function message(item, turn) {
  if (typeof item?.id !== "string") throw new Error("Codex returned an item without an ID");
  let text;
  let role;
  if (item.type === "userMessage") {
    role = "user";
    if (!Array.isArray(item.content)) throw new Error(`Codex user message ${item.id} has no content array`);
    text = item.content.map(block => {
      if (block.type !== "text" || typeof block.text !== "string") {
        throw new Error(`unsupported Codex user content ${block.type} in ${item.id}; text export was not written`);
      }
      return block.text;
    }).join("\n");
  } else if (item.type === "agentMessage") {
    role = "assistant";
    if (typeof item.text !== "string") throw new Error(`Codex agent message ${item.id} has no text`);
    text = item.text;
  } else {
    if (!nonMessageTypes.has(item.type)) throw new Error(`unsupported Codex history item ${item.type}`);
    return null;
  }
  if (!text.trim()) return null;
  const seconds = role === "user" ? turn.startedAt : (turn.completedAt ?? turn.startedAt);
  return { type: "transcript_message", id: item.id, turnId: turn.id, role, text,
    phase: item.phase ?? null,
    timestamp: Number.isFinite(seconds) ? new Date(seconds * 1000).toISOString() : null };
}

/**
 * Return {file, segments: [[session_meta, ...transcript_message]]} from persisted UI history.
 * Messages retain occurrence IDs, order, phase, and known turn times, not model context.
 * Only text user/assistant items are exported; other known item types are omitted.
 * Unsupported content, incomplete pagination, and API failures reject before returning a result.
 * This function owns and closes one app-server; it never resumes or mutates a thread.
 */
export async function readCodexHistory(id, codexHome, { signal, command = "codex", expectedFile } = {}) {
  const client = new CodexClient({ signal, command, env: { ...process.env, CODEX_HOME: resolve(codexHome) } });
  let failure;
  try {
    await client.initialize({ name: "dotfiles_chat_history", version: "1.0.0" });
    const { thread } = await client.request("thread/read", { threadId: id });
    if (thread?.id !== id || typeof thread.path !== "string" || typeof thread.cwd !== "string" ||
        (thread.model != null && typeof thread.model !== "string")) {
      throw new Error("Codex returned invalid thread metadata");
    }
    if (expectedFile && realpathSync(thread.path) !== realpathSync(expectedFile)) {
      throw new Error(`Codex selected ${thread.path} instead of ${expectedFile}; use an explicit file for that rollout`);
    }
    const timestamp = Number.isFinite(thread.createdAt) ? new Date(thread.createdAt * 1000).toISOString() : null;
    const events = [{ type: "session_meta", timestamp, payload: {
      session_id: thread.id, id: thread.id, cwd: thread.cwd, model: thread.model ?? "unknown", timestamp,
    } }];
    const cursors = new Set();
    const turns = new Set();
    const items = new Set();
    let cursor;
    do {
      const page = await client.request("thread/turns/list", {
        threadId: id, sortDirection: "asc", itemsView: "full", limit: 100, ...(cursor ? { cursor } : {}),
      });
      if (!Array.isArray(page?.data) || (page.nextCursor != null && typeof page.nextCursor !== "string")) {
        throw new Error("Codex returned an invalid history page");
      }
      for (const turn of page.data) {
        if (typeof turn.id !== "string" || turns.has(turn.id) || !Array.isArray(turn.items) || turn.itemsView !== "full") {
          throw new Error("Codex returned duplicate turns or incomplete history items");
        }
        turns.add(turn.id);
        for (const item of turn.items) {
          const identity = JSON.stringify([turn.id, item.id]);
          if (items.has(identity)) throw new Error(`Codex repeated item ${item.id} in turn ${turn.id}`);
          items.add(identity);
          const entry = message(item, turn);
          if (entry) events.push(entry);
        }
      }
      cursor = page.nextCursor;
      if (cursor != null) {
        if (!cursor || cursors.has(cursor)) throw new Error("Codex returned a repeated or empty history cursor");
        cursors.add(cursor);
      }
    } while (cursor != null);
    return { file: thread.path, segments: [events] };
  } catch (error) { failure = error; throw error; }
  finally {
    try { await client.close(); }
    catch (cleanup) {
      if (failure) failure.message += `; cleanup: ${cleanup.message}`;
      else throw cleanup;
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const controller = new AbortController();
  for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => controller.abort(new Error(`received ${signal}`)));
  try {
    const [id, home, expectedFile, ...extra] = process.argv.slice(2);
    if (!id || !home || extra.length) throw new Error("expected THREAD_ID CODEX_HOME [EXPECTED_FILE]");
    console.log(JSON.stringify(await readCodexHistory(id, home, { signal: controller.signal, expectedFile })));
  } catch (error) {
    console.error(`codex-history: ${error.message}`);
    process.exitCode = 1;
  }
}
