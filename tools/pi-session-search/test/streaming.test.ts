/*
Copyright 2026 Adobe. All rights reserved.
This file is licensed to you under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License. You may obtain a copy
of the License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
OF ANY KIND, either express or implied. See the License for the specific language
governing permissions and limitations under the License.
*/

import { strict as assert } from "node:assert";
import { closeSync, mkdirSync, mkdtempSync, openSync, rmSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import registerExtension, { formatHitsForCommand, readSessionWindow, searchSessions } from "../index.ts";

const MAX_RECORD_BYTES = 5 * 1024 * 1024;
const CHUNK_BYTES = 64 * 1024;
const BASE_TIME = Date.parse("2026-04-23T06:00:00.000Z");

function message(text: string, index = 0, role = "user"): string {
	return JSON.stringify({
		type: "message",
		timestamp: new Date(BASE_TIME + index * 1000).toISOString(),
		message: { role, content: text },
	});
}

function timestamp(index: number): string {
	return new Date(BASE_TIME + index * 1000).toISOString();
}

describe("streaming JSONL records", () => {
	let root: string;
	let sessionFile: string;
	let originalRoot: string | undefined;
	let originalMax: string | undefined;
	const header = JSON.stringify({
		type: "session", id: "streaming-session", cwd: "/streaming", timestamp: timestamp(0),
	});

	beforeEach(() => {
		originalRoot = process.env.PI_SESSION_SEARCH_ROOT;
		originalMax = process.env.PI_SESSION_SEARCH_MAX_BYTES;
		root = mkdtempSync(join(tmpdir(), "pi-session-streaming-"));
		const dir = join(root, "--streaming--");
		mkdirSync(dir);
		sessionFile = join(dir, "2026-04-23T06-00-00-000Z_streaming.jsonl");
		process.env.PI_SESSION_SEARCH_ROOT = root;
		delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
	});

	afterEach(() => {
		if (originalRoot === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = originalRoot;
		if (originalMax === undefined) delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
		else process.env.PI_SESSION_SEARCH_MAX_BYTES = originalMax;
		rmSync(root, { recursive: true, force: true });
	});

	function writeRecords(records: string[], separator = "\n", trailing = true): void {
		writeFileSync(sessionFile, [header, ...records].join(separator) + (trailing ? separator : ""));
	}

	it("searches and reads near the end of a >5 MiB file made of modest records", async () => {
		const count = 96;
		const records = Array.from({ length: count }, (_, i) =>
			message(`filler-${i}: ${"x".repeat(60 * 1024)}`, i));
		records.push(message("near-end-needle", count, "assistant"));
		writeRecords(records);
		assert.ok(statSync(sessionFile).size > MAX_RECORD_BYTES);
		const result = await searchSessions({ query: "near-end-needle" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.hits[0].sessionId, "streaming-session");
		assert.equal(result.scannedFiles, 1);
		assert.equal(result.skippedFiles, 0);
		assert.equal(result.skippedRecords, 0);
		assert.equal(result.incompleteCoverage, false);
		const window = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(count), contextMessages: 0, maxMessages: 1,
		});
		assert.match(window, /Showing messages 97–97 of 97/);
		assert.match(window, /near-end-needle/);
		assert.ok(!window.includes("filler-"));
	});

	it("streams a >64 MiB transcript in a fresh process with a 32 MiB heap", () => {
		const count = 1100;
		const fd = openSync(sessionFile, "w");
		try {
			writeFileSync(fd, header + "\n");
			for (let i = 0; i < count; i++) writeFileSync(fd, message("x".repeat(60 * 1024), i) + "\n");
			writeFileSync(fd, message("bounded-heap-near-end-needle", count) + "\n");
		} finally {
			closeSync(fd);
		}
		assert.ok(statSync(sessionFile).size > 64 * 1024 * 1024);
		const script = join(root, "bounded-heap.mts");
		const moduleUrl = new URL("../index.ts", import.meta.url).href;
		// A separate script and argv avoid passing executable source through a shell.
		writeFileSync(script, `
import { strict as assert } from "node:assert";
import { searchSessions, readSessionWindow } from ${JSON.stringify(moduleUrl)};
const result = await searchSessions({ query: "bounded-heap-near-end-needle" });
assert.equal(result.hits.length, 1);
assert.equal(result.skippedRecords, 0);
assert.equal(result.incompleteCoverage, false);
const window = await readSessionWindow({
  sessionFile: ${JSON.stringify(sessionFile)},
  aroundTimestamp: ${JSON.stringify(timestamp(count))},
  contextMessages: 0,
  maxMessages: 1,
});
assert.match(window, /Showing messages 1101–1101 of 1101/);
assert.match(window, /bounded-heap-near-end-needle/);
console.log("bounded-heap-success");
`);
		const child = spawnSync(process.execPath, [
			"--max-old-space-size=32", "--experimental-strip-types", script,
		], { encoding: "utf8", env: process.env });
		assert.equal(child.error, undefined);
		assert.equal(child.signal, null, child.stderr);
		assert.equal(child.status, 0, child.stderr);
		assert.match(child.stdout, /bounded-heap-success/);
	});

	it("skips an oversized valid JSON record before JSON.parse and continues for both tools", async () => {
		const oversized = message(`oversized-parse-marker${"x".repeat(MAX_RECORD_BYTES)}`, 1);
		writeRecords([message("before", 0), oversized, message("after-oversized-needle", 2)]);
		const originalParse = JSON.parse;
		let attemptedOversizedParse = false;
		JSON.parse = function (text: string, reviver?: Parameters<typeof JSON.parse>[1]) {
			if (Buffer.byteLength(text) > MAX_RECORD_BYTES) attemptedOversizedParse = true;
			return originalParse(text, reviver);
		};
		try {
			// Positive control: an unguarded whole-line parser really does trip the spy.
			JSON.parse(oversized);
			assert.equal(attemptedOversizedParse, true, "spy must detect the unbounded parse baseline");
			attemptedOversizedParse = false;
			const result = await searchSessions({ query: "after-oversized-needle" });
			assert.equal(attemptedOversizedParse, false, "search record cap must precede JSON.parse");
			assert.equal(result.hits.length, 1);
			assert.equal(result.skippedRecords, 1);
			assert.equal(result.skippedFiles, 0);
			assert.equal(result.incompleteCoverage, true);
			const window = await readSessionWindow({ sessionFile });
			assert.match(window, /Showing messages 1–2 of 2/);
			assert.equal(attemptedOversizedParse, false, "window record cap must precede JSON.parse");
			assert.match(window, /Incomplete coverage: skipped 1 oversized records?\b/);
			assert.match(window, /after-oversized-needle/);
			assert.ok(!window.includes("oversized-parse-marker"));
		} finally {
			JSON.parse = originalParse;
		}
	});

	it("counts multiple oversized records once each, not once per chunk or window pass", async () => {
		writeRecords(["x".repeat(MAX_RECORD_BYTES + 1), message("survivor"), "y".repeat(MAX_RECORD_BYTES + 1)]);
		const result = await searchSessions({ query: "survivor" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedRecords, 2);
		assert.equal(result.incompleteCoverage, true);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–1 of 1/);
		assert.match(window, /Incomplete coverage: skipped 2 oversized records?\b/);
	});

	it("handles an oversized final line without a newline", async () => {
		writeRecords([message("survivor-before-eof"), "z".repeat(MAX_RECORD_BYTES + 1)], "\n", false);
		const result = await searchSessions({ query: "survivor-before-eof" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedRecords, 1);
		assert.equal(result.incompleteCoverage, true);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–1 of 1/);
		assert.match(window, /Incomplete coverage: skipped 1 oversized records?\b/);
	});

	it("accepts a record exactly at the byte cap and rejects the next byte", async () => {
		const overhead = Buffer.byteLength(message(""));
		const atCap = message("x".repeat(MAX_RECORD_BYTES - overhead));
		assert.equal(Buffer.byteLength(atCap), MAX_RECORD_BYTES);
		writeRecords([atCap, message("y".repeat(MAX_RECORD_BYTES - overhead + 1)), message("boundary-survivor", 2)]);
		const result = await searchSessions({ query: "boundary-survivor" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedRecords, 1);
		const window = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(2), contextMessages: 0, maxMessages: 1,
		});
		assert.match(window, /Showing messages 2–2 of 2/);
		assert.match(window, /Incomplete coverage: skipped 1 oversized records?\b/);
	});

	it("enforces the record limit in UTF-8 bytes rather than UTF-16 code units", async () => {
		const oversized = message("界".repeat(Math.ceil(MAX_RECORD_BYTES / 3)));
		assert.ok(oversized.length < MAX_RECORD_BYTES);
		assert.ok(Buffer.byteLength(oversized) > MAX_RECORD_BYTES);
		writeRecords([oversized, message("utf8-cap-survivor", 1)]);
		const result = await searchSessions({ query: "utf8-cap-survivor" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedRecords, 1);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–1 of 1/);
		assert.match(window, /Incomplete coverage: skipped 1 oversized records?\b/);
	});

	it("decodes UTF-8 text straddling a 64 KiB read boundary without replacement characters", async () => {
		const empty = message("");
		const prefix = empty.slice(0, empty.indexOf('"content":"') + '"content":"'.length);
		const padding = CHUNK_BYTES - 1 - Buffer.byteLength(header + "\n" + prefix);
		assert.ok(padding > 0);
		const text = "a".repeat(padding) + "界🙂boundary-needle";
		writeRecords([message(text)]);
		const bytes = Buffer.from(header + "\n" + message(text));
		assert.equal(bytes[CHUNK_BYTES - 1], Buffer.from("界")[0]);
		const result = await searchSessions({ query: "界🙂boundary-needle" });
		assert.equal(result.hits.length, 1);
		assert.match(result.hits[0].snippet, /界🙂boundary-needle/);
		assert.equal(result.skippedRecords, 0);
		assert.equal(result.incompleteCoverage, false);
		const window = await readSessionWindow({ sessionFile });
		assert.ok(window.includes(text));
		assert.ok(!window.includes("\uFFFD"));
	});

	it("handles CRLF, blank and malformed records, and a final record with no newline", async () => {
		writeRecords(["", "{ malformed", message("crlf-first"), " ", message("unterminated-last", 1, "assistant")], "\r\n", false);
		const result = await searchSessions({ query: "unterminated-last" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedRecords, 0, "malformed records are not oversized records");
		assert.equal(result.incompleteCoverage, false);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–2 of 2/);
		assert.match(window, /crlf-first/);
		assert.match(window, /unterminated-last/);
		assert.ok(!window.includes("Incomplete coverage"));
	});

	it("counts only nonempty user/assistant messages, including assistant tool calls", async () => {
		writeRecords([
			message("eligible-user", 0), message("", 1), message("not-eligible-tool-result", 2, "toolResult"),
			JSON.stringify({ type: "custom", timestamp: timestamp(3), message: { role: "user", content: "not-a-message" } }),
			JSON.stringify({ type: "message", timestamp: timestamp(4), message: { role: "assistant", content: [{ type: "thinking", thinking: "hidden" }] } }),
			JSON.stringify({ type: "message", timestamp: timestamp(5), message: { role: "assistant", content: [{ type: "toolCall", name: "eligible_tool", arguments: {} }] } }),
			message("eligible-assistant", 6, "assistant"),
		]);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–3 of 3/);
		assert.match(window, /eligible-user/);
		assert.match(window, /\[tool: eligible_tool/);
		assert.match(window, /eligible-assistant/);
		assert.ok(!window.includes("not-eligible"));
		assert.ok(!window.includes("not-a-message"));
	});

	it("preserves the first nearest tie and searches non-monotonic timestamps in file order", async () => {
		writeRecords([
			message("first-tie", 12), message("second-tie", 8),
			message("far-future", 100), message("late-file-exact", 10), message("far-past", 0),
		]);
		const exact = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(10), contextMessages: 0, maxMessages: 1,
		});
		assert.match(exact, /Showing messages 4–4 of 5/);
		assert.match(exact, /late-file-exact/);
		writeRecords([message("first-tie", 12), message("second-tie", 8), message("far-future", 100)]);
		const tied = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(10), contextMessages: 0, maxMessages: 1,
		});
		assert.match(tied, /Showing messages 1–1 of 3/);
		assert.match(tied, /first-tie/);
		assert.ok(!tied.includes("second-tie"));
	});

	it("preserves context window indexes and clips maxMessages from the window start", async () => {
		writeRecords(Array.from({ length: 8 }, (_, i) => message(`indexed-${i}`, i)));
		const window = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(4), contextMessages: 2, maxMessages: 3,
		});
		assert.match(window, /Showing messages 3–5 of 8/);
		for (const i of [2, 3, 4]) assert.ok(window.includes(`indexed-${i}`));
		for (const i of [0, 1, 5, 6, 7]) assert.ok(!window.includes(`indexed-${i}`));
		const end = await readSessionWindow({
			sessionFile, aroundTimestamp: timestamp(7), contextMessages: 2, maxMessages: 10,
		});
		assert.match(end, /Showing messages 6–8 of 8/);
		const initial = await readSessionWindow({ sessionFile, maxMessages: 2 });
		assert.match(initial, /Showing messages 1–2 of 8/);
	});

	it("applies the configured byte cap to each record, not the whole file, in both tools", async () => {
		const cap = 1024;
		process.env.PI_SESSION_SEARCH_MAX_BYTES = String(cap);
		const atCap = message("x".repeat(cap - Buffer.byteLength(message("", 5))), 5);
		const overCap = message("y".repeat(cap + 1 - Buffer.byteLength(message("", 6))), 6);
		assert.equal(Buffer.byteLength(atCap), cap);
		assert.equal(Buffer.byteLength(overCap), cap + 1);
		writeRecords([
			...Array.from({ length: 5 }, (_, i) => message("small-record ".repeat(30), i)),
			atCap, overCap, message("configured-cap-survivor", 7),
		]);
		assert.ok(statSync(sessionFile).size > cap);
		const result = await searchSessions({ query: "configured-cap-survivor" });
		assert.equal(result.hits.length, 1);
		assert.equal(result.skippedFiles, 0);
		assert.equal(result.skippedRecords, 1);
		assert.equal(result.incompleteCoverage, true);
		const window = await readSessionWindow({ sessionFile });
		assert.match(window, /Showing messages 1–7 of 7/);
		assert.match(window, /configured-cap-survivor/);
		assert.ok(window.includes("x".repeat(100)), "exact-cap record must be eligible");
		assert.ok(!window.includes("y".repeat(100)), "over-cap record must be excluded");
		assert.match(window, /Incomplete coverage: skipped 1 oversized records?\b/);
	});

	it("supports maxMessages=0 while preserving the eligible total", async () => {
		writeRecords([message("zero-window-first"), message("zero-window-second", 1)]);
		const window = await readSessionWindow({ sessionFile, maxMessages: 0 });
		assert.match(window, /Showing messages 1–0 of 2/);
		assert.ok(!window.includes("zero-window-first"));
		assert.ok(!window.includes("zero-window-second"));
	});

	it("rejects contextMessages and maxMessages that are not non-negative safe integers", async () => {
		writeRecords([message("validation")]);
		for (const value of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
			await assert.rejects(() => readSessionWindow({ sessionFile, contextMessages: value }), /contextMessages/);
			await assert.rejects(() => readSessionWindow({ sessionFile, maxMessages: value }), /maxMessages/);
		}
	});

	it("includes incomplete-coverage command warnings with and without hits", async () => {
		writeRecords(["x".repeat(MAX_RECORD_BYTES + 1), message("command-warning-needle")]);
		const matched = formatHitsForCommand(await searchSessions({ query: "command-warning-needle" }));
		assert.match(matched, /1 hit/);
		assert.match(matched, /command-warning-needle/);
		assert.match(matched, /Incomplete coverage: skipped 1 oversized records?\b/);
		const unmatched = formatHitsForCommand(await searchSessions({ query: "absent-needle" }));
		assert.match(unmatched, /No matches/);
		assert.match(unmatched, /Incomplete coverage: skipped 1 oversized records?\b/);
	});

	it("projects coverage through registered tool content/details and forwards read cancellation", async () => {
		type CapturedTool = {
			name: string;
			execute: (
				id: string, params: Record<string, unknown>, signal: AbortSignal | undefined,
				onUpdate: undefined, ctx: unknown,
			) => Promise<{
				content: Array<{ type: string; text?: string }>;
				details: Record<string, unknown>;
				isError?: boolean;
			}>;
		};
		const tools = new Map<string, CapturedTool>();
		// This mock implements only the registration surface used by the extension.
		const api = {
			registerTool(tool: CapturedTool) { tools.set(tool.name, tool); },
			registerCommand() {},
		} as unknown as ExtensionAPI;
		registerExtension(api);
		const search = tools.get("search_sessions");
		const read = tools.get("read_session");
		assert.ok(search);
		assert.ok(read);
		writeRecords(["x".repeat(MAX_RECORD_BYTES + 1), message("projection-needle")]);
		const ctx = { sessionManager: { getHeader: () => ({ id: "other-session" }) } };
		const result = await search.execute("search-id", { query: "projection-needle" }, undefined, undefined, ctx);
		assert.notEqual(result.isError, true);
		assert.equal(result.content[0].type, "text");
		const payload = JSON.parse(result.content[0].text ?? "") as {
			count: number; skippedRecords: number; incompleteCoverage: boolean; hits: unknown[];
		};
		assert.equal(payload.count, 1);
		assert.equal(payload.hits.length, 1);
		assert.equal(payload.skippedRecords, 1);
		assert.equal(payload.incompleteCoverage, true);
		assert.equal(result.details.skippedRecords, 1);
		assert.equal(result.details.incompleteCoverage, true);
		const window = await read.execute("read-id", { sessionFile }, undefined, undefined, ctx);
		assert.notEqual(window.isError, true);
		assert.match(window.content[0].text ?? "", /Incomplete coverage: skipped 1 oversized records?\b/);
		const controller = new AbortController();
		controller.abort();
		const abortedRead = await read.execute("abort-read-id", { sessionFile }, controller.signal, undefined, ctx);
		assert.equal(abortedRead.isError, true);
		assert.match(abortedRead.content[0].text ?? "", /read_session failed:/);
		const abortedSearch = await search.execute("abort-search-id", { query: "projection-needle" }, controller.signal, undefined, ctx);
		assert.notEqual(abortedSearch.isError, true);
		assert.equal(abortedSearch.details.incompleteCoverage, true);
		assert.equal(abortedSearch.details.count, 0);
	});

	it("keeps earlier search hits when aborted during record processing", async () => {
		writeRecords([message("partial-hit-first"), message("abort-processing-marker", 1), message("partial-hit-unvisited", 2)]);
		const controller = new AbortController();
		const originalParse = JSON.parse;
		JSON.parse = function (text: string, reviver?: Parameters<typeof JSON.parse>[1]) {
			const parsed: unknown = originalParse(text, reviver);
			if (text.includes("abort-processing-marker")) controller.abort();
			return parsed;
		};
		try {
			const result = await searchSessions({ query: "partial-hit", signal: controller.signal });
			assert.equal(controller.signal.aborted, true);
			assert.equal(result.hits.length, 1);
			assert.match(result.hits[0].snippet, /partial-hit-first/);
			assert.equal(result.skippedRecords, 0);
			assert.equal(result.incompleteCoverage, true);
		} finally {
			JSON.parse = originalParse;
		}
	});

	it("rejects a read aborted during its counting pass", async () => {
		writeRecords([message("abort-window-count-marker"), message("not-returned", 1)]);
		const controller = new AbortController();
		const originalParse = JSON.parse;
		JSON.parse = function (text: string, reviver?: Parameters<typeof JSON.parse>[1]) {
			const parsed: unknown = originalParse(text, reviver);
			if (text.includes("abort-window-count-marker")) controller.abort();
			return parsed;
		};
		try {
			await assert.rejects(() => readSessionWindow({ sessionFile, signal: controller.signal }));
			assert.equal(controller.signal.aborted, true);
		} finally {
			JSON.parse = originalParse;
		}
	});

	it("returns incomplete search results and rejects a read for an already aborted signal", async () => {
		writeRecords([message("aborted-needle")]);
		const controller = new AbortController();
		controller.abort();
		const result = await searchSessions({ query: "aborted-needle", signal: controller.signal });
		assert.equal(result.hits.length, 0);
		assert.equal(result.skippedRecords, 0);
		assert.equal(result.incompleteCoverage, true);
		await assert.rejects(() => readSessionWindow({ sessionFile, signal: controller.signal }));
	});
});
