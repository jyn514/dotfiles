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
import { spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, mkdtempSync, realpathSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, it } from "node:test";
import { discoverAndLoadExtensions, SessionManager } from "@earendil-works/pi-coding-agent";
import { readSession, readSessionWindow, searchSessions } from "../index.ts";

const time = "2026-10-14T09:00:00.000Z";
const header = JSON.stringify({ type: "session", id: "navigation-session", cwd: "/fixture", timestamp: time });
function message(id: string | undefined, text: string, role = "user", timestamp = time): string {
	return JSON.stringify({ type: "message", id, timestamp, message: { role, content: text } });
}

describe("session navigation", () => {
	let root: string;
	let sessionFile: string;
	let originalRoot: string | undefined;
	let originalMax: string | undefined;
	beforeEach(() => {
		root = mkdtempSync(join(tmpdir(), "pi-session-navigation-"));
		mkdirSync(join(root, "--fixture--"));
		sessionFile = join(root, "--fixture--", "2026-10-14T09-00-00-000Z_navigation.jsonl");
		originalRoot = process.env.PI_SESSION_SEARCH_ROOT;
		originalMax = process.env.PI_SESSION_SEARCH_MAX_BYTES;
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
	function write(records: string[]): void {
		writeFileSync(sessionFile, [header, ...records].join("\n") + "\n");
	}

	it("reads the tail in file order rather than timestamp order", async () => {
		write([
			message("first", "older file entry", "user", "2026-10-14T12:00:00Z"),
			message("result", "excluded tool result", "toolResult"),
			message("middle", "middle file entry"),
			message("last", "last file entry", "assistant", "2026-10-13T00:00:00Z"),
		]);
		const result = await readSession({ sessionFile, tail: true, maxMessages: 2 });
		assert.deepEqual(result.messages.map(m => [m.index, m.entryId]), [[2, "middle"], [3, "last"]]);
		assert.equal(result.hasMore, false);
		assert.ok(typeof result.nextCursor === "string");
		assert.ok(result.nextCursor.length > 0);
		assert.ok(!result.text.includes("excluded tool result"));
		const initial = await readSession({ sessionFile, maxMessages: 1 });
		assert.equal(initial.messages[0].entryId, "first", "the default remains a read from the start");
	});

	it("returns the resolved transcript path for either selector and every read position", async () => {
		write([message("a", "first"), message("b", "second")]);
		const expected = realpathSync(sessionFile);
		for (const selector of [{ sessionId: "navigation-session" }, { sessionFile }, { sessionFile: relative(root, sessionFile) }]) {
			for (const position of [{}, { tail: true }, { aroundEntryId: "a" }, { aroundTimestamp: time }, { maxMessages: 0 }]) {
				const result = await readSession({ ...selector, ...position, maxMessages: position.maxMessages ?? 1 });
				assert.equal(result.sessionFile, expected);
				const continued = await readSession({ ...selector, after: result.nextCursor, maxMessages: 1 });
				assert.equal(continued.sessionFile, expected);
			}
		}
		write([]);
		assert.equal((await readSession({ sessionId: "navigation-session" })).sessionFile, expected,
			"empty transcripts still identify the resolved file");
	});

	it("returns the canonical target rather than echoing a symlink selector", { skip: process.platform === "win32" }, async () => {
		write([message("a", "first")]);
		const alias = join(root, "--fixture--", "alias.jsonl");
		symlinkSync(sessionFile, alias);
		const result = await readSession({ sessionFile: relative(root, alias) });
		assert.equal(result.sessionFile, realpathSync(sessionFile));
		assert.notEqual(result.sessionFile, alias);
	});

	it("round-trips search entry IDs even when multiple entries share a timestamp", async () => {
		write([message("earlier", "not the target"), message("target", "exact needle", "assistant")]);
		const search = await searchSessions({ query: "exact needle" });
		assert.equal(search.hits.length, 1);
		const hit = search.hits[0];
		assert.equal(hit.entryId, "target");
		const result = await readSession({ sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 });
		assert.deepEqual(result.messages.map(m => m.entryId), ["target"]);
		assert.ok(result.text.includes("exact needle"));
		assert.ok(!result.text.includes("not the target"));
		await assert.rejects(readSession({ sessionFile, aroundEntryId: "missing" }), /entry|found/i);
	});

	it("preserves legacy records without inventing an entry ID", async () => {
		write([message(undefined, "legacy needle")]);
		const hit = (await searchSessions({ query: "legacy needle" })).hits[0];
		assert.equal(hit.entryId, undefined);
		const result = await readSession({ sessionId: "navigation-session", aroundTimestamp: hit.timestamp });
		assert.equal(result.messages.length, 1);
		assert.equal(result.messages[0].entryId, undefined);
		assert.ok(result.text.includes("legacy needle"));
	});

	it("pages without missing or repeating entries, then follows appends", async () => {
		write([message("a", "alpha"), message("b", "beta"), message("c", "gamma")]);
		const first = await readSession({ sessionFile, maxMessages: 1 });
		assert.equal(first.hasMore, true);
		const second = await readSession({ sessionFile, after: first.nextCursor, maxMessages: 1 });
		assert.equal(second.hasMore, true);
		const third = await readSession({ sessionFile, after: second.nextCursor, maxMessages: 1 });
		assert.deepEqual([...first.messages, ...second.messages, ...third.messages].map(m => m.entryId), ["a", "b", "c"]);
		assert.equal(third.hasMore, false);
		const empty = await readSession({ sessionFile, after: third.nextCursor });
		assert.deepEqual(empty.messages, []);
		assert.equal(empty.hasMore, false);
		assert.ok(empty.nextCursor);
		appendFileSync(sessionFile, message("tool", "not visible", "toolResult") + "\n" + message("d", "delta") + "\n");
		const appended = await readSession({ sessionFile, after: empty.nextCursor });
		assert.deepEqual(appended.messages.map(m => [m.index, m.entryId]), [[4, "d"]]);
	});

	it("returns a usable polling cursor for an empty session", async () => {
		write([]);
		const empty = await readSession({ sessionFile, tail: true });
		assert.deepEqual(empty.messages, []);
		appendFileSync(sessionFile, message("new", "new message") + "\n");
		const result = await readSession({ sessionFile, after: empty.nextCursor });
		assert.deepEqual(result.messages.map(m => m.entryId), ["new"]);
	});

	it("does not advance a partial trailing record out of reach", async () => {
		write([message("a", "alpha")]);
		const partial = message("b", "completed later");
		const split = Math.floor(partial.length / 2);
		appendFileSync(sessionFile, partial.slice(0, split));
		const before = await readSession({ sessionFile, tail: true });
		const waiting = await readSession({ sessionFile, after: before.nextCursor });
		assert.deepEqual(waiting.messages, []);
		appendFileSync(sessionFile, partial.slice(split) + "\n");
		const after = await readSession({ sessionFile, after: waiting.nextCursor });
		assert.deepEqual(after.messages.map(m => m.entryId), ["b"]);
	});

	it("continues after a complete final record without a newline", async () => {
		writeFileSync(sessionFile, header + "\n" + message("a", "alpha"));
		const first = await readSession({ sessionFile });
		assert.deepEqual(first.messages.map(m => m.entryId), ["a"]);
		appendFileSync(sessionFile, "\n" + message("b", "beta") + "\n");
		const next = await readSession({ sessionFile, after: first.nextCursor });
		assert.deepEqual(next.messages.map(m => m.entryId), ["b"]);
	});

	it("rejects cursors after truncation, prefix edits, or file replacement", async () => {
		for (const change of ["truncate", "rewrite", "replace"]) {
			write([message("a", "alpha"), message("b", "beta")]);
			const read = await readSession({ sessionFile, tail: true });
			if (change === "truncate") write([]);
			if (change === "rewrite") write([message("a", "omega"), message("b", "beta"), message("c", "new")]);
			if (change === "replace") {
				renameSync(sessionFile, sessionFile + ".old");
				write([message("a", "alpha"), message("b", "beta")]);
			}
			await assert.rejects(readSession({ sessionFile, after: read.nextCursor }), /stale|changed|replac|truncat/i, change);
		}
	});

	it("rejects nonregular session paths without hanging on FIFO open", { skip: process.platform === "win32" }, () => {
		const fifo = spawnSync("mkfifo", [sessionFile], { encoding: "utf8" });
		assert.equal(fifo.status, 0, fifo.error?.message ?? fifo.stderr);
		const script = join(root, "read-fifo.mts");
		writeFileSync(script, `
import { readSession } from ${JSON.stringify(new URL("../index.ts", import.meta.url).href)};
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 50);
try {
  await readSession({ sessionFile: process.argv[2], signal: controller.signal });
  process.exitCode = 2;
} catch (error) {
  console.log((error as Error).message);
} finally {
  clearTimeout(timer);
}
`);
		const child = spawnSync(process.execPath, ["--experimental-strip-types", script, sessionFile], {
			encoding: "utf8", timeout: 3000,
		});
		assert.equal(child.error, undefined, `reader must finish without a writer: ${child.error?.message}`);
		assert.equal(child.status, 0, child.stderr);
		assert.match(child.stdout, /regular file/i);
	});

	it("binds cursors to the selected file and rejects malformed cursors", async () => {
		write([message("a", "alpha")]);
		const first = await readSession({ sessionFile });
		const other = join(root, "--fixture--", "other.jsonl");
		writeFileSync(other, header + "\n" + message("a", "alpha") + "\n");
		await assert.rejects(readSession({ sessionFile: other, after: first.nextCursor }), /cursor|session|file/i);
		for (const after of ["", "not-a-cursor", "x".repeat(100_000)]) {
			await assert.rejects(readSession({ sessionFile, after }), /cursor/i);
		}
	});

	it("allows edits after the committed prefix but rejects a changed record-byte limit", async () => {
		write([message("a", "alpha"), message("b", "beta")]);
		const first = await readSession({ sessionFile, maxMessages: 1 });
		write([message("a", "alpha"), message("c", "changed unread suffix")]);
		const next = await readSession({ sessionFile, after: first.nextCursor });
		assert.deepEqual(next.messages.map(m => m.entryId), ["c"]);
		process.env.PI_SESSION_SEARCH_MAX_BYTES = "1024";
		await assert.rejects(readSession({ sessionFile, after: next.nextCursor }), /stale|cap|limit|changed/i);
	});

	it("uses zero limits without advancing, except for an explicit zero-message tail", async () => {
		write([message("a", "alpha"), message("b", "beta")]);
		const zero = await readSession({ sessionFile, maxMessages: 0 });
		assert.deepEqual(zero.messages, []);
		assert.equal(zero.hasMore, true);
		const first = await readSession({ sessionFile, after: zero.nextCursor, maxMessages: 1 });
		assert.deepEqual(first.messages.map(m => m.entryId), ["a"]);
		const paused = await readSession({ sessionFile, after: first.nextCursor, maxMessages: 0 });
		const second = await readSession({ sessionFile, after: paused.nextCursor });
		assert.deepEqual(second.messages.map(m => m.entryId), ["b"]);
		const tail = await readSession({ sessionFile, tail: true, maxMessages: 0 });
		assert.deepEqual(tail.messages, []);
		assert.equal(tail.hasMore, false);
		appendFileSync(sessionFile, message("c", "gamma") + "\n");
		const appended = await readSession({ sessionFile, after: tail.nextCursor });
		assert.deepEqual(appended.messages.map(m => m.entryId), ["c"]);
	});

	it("reports oversized records while still paging to later messages", async () => {
		process.env.PI_SESSION_SEARCH_MAX_BYTES = "512";
		write([message("a", "alpha"), message("large", "x".repeat(1024)), message("b", "beta")]);
		const first = await readSession({ sessionFile, maxMessages: 1 });
		assert.equal(first.skippedRecords, 1);
		assert.match(first.text, /Incomplete coverage/);
		const next = await readSession({ sessionFile, after: first.nextCursor });
		assert.deepEqual(next.messages.map(m => m.entryId), ["b"]);
	});

	it("rejects conflicting selectors and invalid timestamps instead of reading the start", async () => {
		write([message("a", "alpha")]);
		for (const options of [
			{ tail: true, aroundTimestamp: time },
			{ tail: true, aroundEntryId: "a" },
			{ tail: true, after: "cursor" },
			{ aroundEntryId: "a", aroundTimestamp: time },
			{ aroundEntryId: "a", after: "cursor" },
			{ aroundTimestamp: time, after: "cursor" },
		]) await assert.rejects(readSession({ sessionFile, ...options }), /exclusive|only one|at most one|combine/i);
		for (const aroundTimestamp of ["", "not-a-date"]) {
			await assert.rejects(readSessionWindow({ sessionFile, aroundTimestamp }), /timestamp|date/i);
		}
	});

	it("keeps centered reads within the requested radius and retains every positive-limit anchor", async () => {
		let cases = 0;
		for (const count of [1, 2, 7]) {
			write(Array.from({ length: count }, (_, i) => message(`entry-${i}`, `message-${i}`)));
			for (let target = 0; target < count; target++) {
				for (const contextMessages of [0, 1, 6]) {
					for (const maxMessages of [0, 1, 2, 3, 30]) {
						const result = await readSession({ sessionFile, aroundEntryId: `entry-${target}`, contextMessages, maxMessages });
						const label = JSON.stringify({ count, target, contextMessages, maxMessages });
						assert.ok(result.messages.length <= maxMessages, label);
						assert.ok(result.messages.length <= 2 * contextMessages + 1, label);
						if (maxMessages > 0) assert.ok(result.messages.some(m => m.entryId === `entry-${target}`), label);
						for (let i = 0; i < result.messages.length; i++) {
							const actual = result.messages[i];
							assert.ok(Math.abs(actual.index - (target + 1)) <= contextMessages, label);
							if (i > 0) assert.equal(actual.index, result.messages[i - 1].index + 1, label);
						}
						cases++;
					}
				}
			}
		}
		assert.equal(cases, 150, "all boundary/radius/limit combinations execute without filtering");
	});

	it("returns native Pi entry IDs that round-trip through exact reads", async () => {
		const source = SessionManager.create(root, join(root, "--native--"));
		source.appendMessage({ role: "user", content: "native preceding context", timestamp: 1 });
		const targetId = source.appendMessage({ role: "user", content: "native exact search needle", timestamp: 1 });
		const hit = (await searchSessions({ query: "native exact search needle" })).hits[0];
		assert.equal(hit.entryId, targetId);
		const result = await readSession({ sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 });
		assert.deepEqual(result.messages.map(m => m.entryId), [targetId]);
		assert.ok(result.text.includes("native exact search needle"));
		assert.ok(!result.text.includes("native preceding context"));
	});

	it("exposes exact-hit, tail, cursor, and message metadata through Pi's real loader", async () => {
		write([message("a", "first needle"), message("b", "second needle", "assistant")]);
		const packageDir = fileURLToPath(new URL("../", import.meta.url));
		const loaded = await discoverAndLoadExtensions([packageDir], root, join(root, "agent"));
		assert.deepEqual(loaded.errors, []);
		const read = loaded.extensions[0].tools.get("read_session")?.definition;
		const search = loaded.extensions[0].tools.get("search_sessions")?.definition;
		assert.ok(read);
		assert.ok(search);
		const ctx = { sessionManager: { getHeader: () => ({ id: "current" }) } } as Parameters<typeof search.execute>[4];
		const found = await search.execute("find", { query: "second needle" }, undefined, undefined, ctx);
		assert.notEqual(found.isError, true);
		const searchPayload = JSON.parse(found.content[0].type === "text" ? found.content[0].text : "");
		const hit = searchPayload.hits[0];
		assert.equal(hit.entryId, "b");
		const exact = await read.execute("exact", { sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 }, undefined, undefined, ctx);
		assert.notEqual(exact.isError, true);
		assert.match(JSON.stringify(exact.content), /second needle/);
		assert.ok(!JSON.stringify(exact.content).includes("first needle"));
		const tail = await read.execute("tail", { sessionFile, tail: true, maxMessages: 1 }, undefined, undefined, ctx);
		assert.notEqual(tail.isError, true);
		assert.ok(tail.details && typeof tail.details === "object" && "nextCursor" in tail.details);
		const cursor = tail.details.nextCursor;
		assert.equal(typeof cursor, "string");
		assert.ok(JSON.stringify(tail.content).includes(String(cursor)), "the model sees the cursor, not only the UI");
		assert.ok("messages" in tail.details);
		assert.deepEqual(tail.details.messages, [{ index: 2, entryId: "b", role: "assistant", timestamp: time }]);
		assert.ok("hasMore" in tail.details && tail.details.hasMore === false);
		assert.match(JSON.stringify(tail.content), /message 2/);
		assert.ok("sessionFile" in tail.details);
		assert.equal(tail.details.sessionFile, realpathSync(sessionFile));
		for (const key of ["sessionId", "maxMessages", "contextMessages", "tail", "text"]) {
			assert.ok(!(key in tail.details), `metadata must not echo ${key}`);
		}
		appendFileSync(sessionFile, message("c", "third needle") + "\n");
		const next = await read.execute("next", { sessionFile, after: cursor }, undefined, undefined, ctx);
		assert.notEqual(next.isError, true);
		assert.match(JSON.stringify(next.content), /third needle/);
		assert.ok(!JSON.stringify(next.content).includes("second needle"));
	});
});
