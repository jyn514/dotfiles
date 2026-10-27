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

import "./isolate-subagents.ts";
import { strict as assert } from "node:assert";
import { appendFileSync, mkdirSync, mkdtempSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";
import { readSession } from "../index.ts";

const time = "2026-10-14T09:00:00.000Z";
const header = { type: "session", id: "edit-candidates-session", cwd: "/fixture", timestamp: time };
const candidateOptions = { view: "edit_candidates" as const };
function message(id: string | undefined, content: unknown, role = "assistant", timestamp = time): unknown {
	return { type: "message", id, timestamp, message: { role, content } };
}
function call(name: string, path: string, id = "call-1"): unknown {
	return { type: "toolCall", name, arguments: { path }, id };
}
function direct(id: string | undefined, path: string, name = "edit", timestamp = time): unknown {
	return message(id, [call(name, path, `call-${id}`)], "assistant", timestamp);
}
function nested(id: string, calls: unknown[], complete = true, timestamp = time): unknown {
	return { type: "message", id, timestamp, message: { role: "toolResult", toolName: "codemode", toolCallId: "outer-call",
		content: [{ type: "text", text: `nested evidence ${id}` }], nestedCalls: { calls, complete } } };
}
function checkpoint(id: string, paths: string[], timestamp = time): unknown {
	return { type: "compaction", id, timestamp, summary: `checkpoint evidence ${id}`, details: { modifiedFiles: paths } };
}
function recordedCall(name: string, path: string, id: string, status = "completed"): unknown {
	return { name, id, arguments: { path }, status };
}

describe("Pi edit candidate projection", () => {
	let root: string;
	let sessionFile: string;
	let originalRoot: string | undefined;
	let originalCodexRoot: string | undefined;
	let originalMax: string | undefined;
	beforeEach(() => {
		root = mkdtempSync(join(tmpdir(), "pi-edit-candidates-"));
		mkdirSync(join(root, "--fixture--"));
		sessionFile = join(root, "--fixture--", "candidates.jsonl");
		originalRoot = process.env.PI_SESSION_SEARCH_ROOT;
		originalCodexRoot = process.env.PI_SESSION_SEARCH_CODEX_ROOT;
		originalMax = process.env.PI_SESSION_SEARCH_MAX_BYTES;
		process.env.PI_SESSION_SEARCH_ROOT = root;
		process.env.PI_SESSION_SEARCH_CODEX_ROOT = join(root, "no-codex");
		delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
	});
	afterEach(() => {
		if (originalRoot === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = originalRoot;
		if (originalCodexRoot === undefined) delete process.env.PI_SESSION_SEARCH_CODEX_ROOT;
		else process.env.PI_SESSION_SEARCH_CODEX_ROOT = originalCodexRoot;
		if (originalMax === undefined) delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
		else process.env.PI_SESSION_SEARCH_MAX_BYTES = originalMax;
		rmSync(root, { recursive: true, force: true });
	});
	function write(records: unknown[]): void {
		writeFileSync(sessionFile, [header, ...records].map(record => JSON.stringify(record)).join("\n") + "\n");
	}
	async function read(options: Omit<Parameters<typeof readSession>[0], "sessionFile" | "view"> = {}) {
		const result = await readSession({ sessionFile, ...candidateOptions, ...options });
		assert.ok(Array.isArray(result.candidates), "candidate view always returns a candidate list, including empty reads");
		return result as typeof result & { candidates: NonNullable<typeof result.candidates> };
	}

	it("returns direct, nested and checkpoint evidence without normalizing, deduplicating or reconciling paths", async () => {
		const earlier = "../skills/autonomous-work/SKILL.md";
		write([
			message("assignment", "work on autonomous behavior", "user"),
			message("direct", [call("edit", earlier, "edit-1"), call("write", "./notes/../draft.md", "write-1"),
				call("edit", earlier, "edit-2")]),
			message("changed-assignment", "now clean up prompts instead", "user"),
			nested("nested", [recordedCall("edit", "~/.agents/skills/SKILL.md", "nested-1", "error"),
				recordedCall("write", "relative/../same.md", "nested-2", "running")]),
			checkpoint("checkpoint", [earlier, "/absolute/checkpoint-only.md", earlier]),
		]);
		const result = await read();
		assert.equal(result.sessionFile, realpathSync(sessionFile));
		assert.deepEqual(result.candidates, [
			{ source: { sessionFile: realpathSync(sessionFile), aroundEntryId: "direct" }, timestamp: time,
				targets: [{ kind: "tool_call", path: earlier, toolName: "edit", toolCallId: "edit-1" },
					{ kind: "tool_call", path: "./notes/../draft.md", toolName: "write", toolCallId: "write-1" },
					{ kind: "tool_call", path: earlier, toolName: "edit", toolCallId: "edit-2" }] },
			{ source: { sessionFile: realpathSync(sessionFile), aroundEntryId: "nested" }, timestamp: time,
				targets: [{ kind: "nested_call", path: "~/.agents/skills/SKILL.md", toolName: "edit", toolCallId: "nested-1" },
					{ kind: "nested_call", path: "relative/../same.md", toolName: "write", toolCallId: "nested-2" }] },
			{ source: { sessionFile: realpathSync(sessionFile), aroundEntryId: "checkpoint" }, timestamp: time,
				targets: [{ kind: "checkpoint", path: earlier }, { kind: "checkpoint", path: "/absolute/checkpoint-only.md" },
					{ kind: "checkpoint", path: earlier }] },
		]);
		assert.notEqual(result.incomplete, true);
		assert.equal(result.skippedRecords, 0);
		assert.equal(result.hasMore, false);
	});

	it("does not infer edits from prose, shell commands, aliases, read calls or nested metadata in the wrong location", async () => {
		write([
			message("prose", "I edited skills/autonomous-work/SKILL.md with edit({path: 'guessed.md'})"),
			message("other-tools", [call("read", "read-only.md"), call("functions.edit", "aliased.md"),
				{ type: "toolCall", name: "bash", arguments: { command: "echo changed > shell-only.md" } }]),
			message("user-data", [call("edit", "user-data.md")], "user"),
			nested("non-edit-nested", [recordedCall("read", "nested-read.md", "read-1")]),
			{ type: "message", id: "wrong-location", timestamp: time,
				message: { role: "toolResult", content: "ordinary result", details: { nestedCalls: {
					calls: [recordedCall("edit", "details-only.md", "wrong")], complete: true } } } },
			{ type: "custom", id: "custom-state", timestamp: time, details: { modifiedFiles: ["not-a-checkpoint.md"] } },
			direct("real", "real.md"),
		]);
		const result = await read();
		assert.deepEqual(result.candidates.map(c => c.source.aroundEntryId), ["real"]);
		assert.notEqual(result.incomplete, true, "irrelevant calls are not missing edit evidence");
	});

	it("marks missing relevant arguments and incomplete nested recordings even when no target can be returned", async () => {
		write([
			message("missing-direct", [{ type: "toolCall", name: "edit", id: "missing" }]),
			message("missing-path", [{ type: "toolCall", name: "write", id: "no-path", arguments: { content: "text" } }]),
			nested("missing-nested", [{ name: "edit", id: "bytes-only", argumentsBytes: 123, status: "completed" },
				{ name: "write", id: "missing-nested-path", arguments: {}, status: "error" }]),
			nested("incomplete-empty", [], false),
			nested("incomplete-with-target", [recordedCall("edit", "available.md", "available")], false),
		]);
		const result = await read();
		assert.deepEqual(result.candidates.map(c => [c.source.aroundEntryId, c.targets.map(t => t.path), c.incomplete]), [
			["missing-direct", [], true], ["missing-path", [], true], ["missing-nested", [], true],
			["incomplete-empty", [], true], ["incomplete-with-target", ["available.md"], true],
		]);
		assert.equal(result.incomplete, true);
	});

	it("omits candidate records without an inspectable entry ID and reports incompleteness", async () => {
		write([direct(undefined, "legacy-uninspectable.md"), direct("inspectable", "inspectable.md")]);
		const result = await read();
		assert.deepEqual(result.candidates.map(c => c.source.aroundEntryId), ["inspectable"]);
		assert.equal(result.incomplete, true);
		assert.ok(!JSON.stringify(result.candidates).includes("legacy-uninspectable.md"));
	});

	it("keeps more than thirty nested targets in one candidate and counts source records for maxMessages", async () => {
		const paths = Array.from({ length: 45 }, (_, i) => `nested-${i}.md`);
		write([nested("many-nested", paths.map((path, i) => recordedCall("edit", path, `n-${i}`))), direct("next", "next.md")]);
		const first = await read({ maxMessages: 1 });
		assert.deepEqual(first.candidates.map(c => c.source.aroundEntryId), ["many-nested"]);
		assert.deepEqual(first.candidates[0].targets.map(t => t.path), paths);
		assert.equal(first.hasMore, true);
		const next = await read({ after: first.nextCursor, maxMessages: 1 });
		assert.deepEqual(next.candidates.map(c => c.source.aroundEntryId), ["next"]);
		assert.equal(next.hasMore, false);
	});

	it("defaults to thirty candidate records and pages mixed evidence without replay or loss", async () => {
		const ids = Array.from({ length: 33 }, (_, i) => `candidate-${i}`);
		write(ids.flatMap((id, i) => [message(`context-${i}`, "not a candidate", "user"),
			i % 3 === 0 ? direct(id, `${id}.md`)
				: i % 3 === 1 ? nested(id, [recordedCall("write", `${id}.md`, `call-${i}`)])
					: checkpoint(id, [`${id}.md`])]));
		const first = await read();
		assert.deepEqual(first.candidates.map(c => c.source.aroundEntryId), ids.slice(0, 30));
		assert.equal(first.hasMore, true);
		const second = await read({ after: first.nextCursor });
		assert.deepEqual(second.candidates.map(c => c.source.aroundEntryId), ids.slice(30));
		assert.equal(second.hasMore, false);
	});

	it("makes every source reference inspectable and its ordinary cursor resumes without a stale message count", async () => {
		write([
			message("before", "ordinary before", "user"), direct("direct", "direct-target.md"),
			message("middle", "ordinary middle", "user"), nested("nested", [recordedCall("edit", "nested-target.md", "nested-call")]),
			checkpoint("checkpoint", ["checkpoint-target.md"]), message("after", "ordinary after", "user"),
		]);
		const result = await read();
		for (const candidate of result.candidates) {
			const inspected = await readSession({ ...candidate.source, maxMessages: 1 });
			assert.ok(inspected.messages.some(m => m.entryId === candidate.source.aroundEntryId), "exact source anchor is retained");
			for (const target of candidate.targets) assert.ok(inspected.text.includes(target.path), target.path);
			const continued = await readSession({ sessionFile, after: inspected.nextCursor });
			const expected = candidate.source.aroundEntryId === "direct" ? ["middle", "after"] : ["after"];
			assert.deepEqual(continued.messages.map(m => m.entryId), expected, candidate.source.aroundEntryId);
		}
		const ordinary = await readSession({ sessionFile });
		assert.deepEqual(ordinary.messages.map(m => m.entryId), ["before", "direct", "middle", "after"]);
		assert.ok(!ordinary.text.includes("nested-target.md"));
		assert.ok(!ordinary.text.includes("checkpoint-target.md"));
	});

	it("inspects the first repeated source ID without counting later copies as ordinary messages", async () => {
		for (const source of [nested("repeated", [recordedCall("edit", "repeated.md", "call")]),
			checkpoint("repeated", ["repeated.md"])]) {
			write([message("before", "ordinary before", "user"), source, source,
				message("after", "ordinary after", "user")]);
			const page = await read();
			assert.equal(page.candidates.length, 2, "separate recorded copies remain candidates");
			for (const maxMessages of [1, 3]) {
				const inspected = await readSession({ ...page.candidates[0].source, maxMessages });
				assert.equal(inspected.messages.filter(m => m.entryId === "repeated").length, 1);
				const continued = await readSession({ sessionFile, after: inspected.nextCursor });
				assert.deepEqual(continued.messages.map(m => m.entryId), maxMessages === 1 ? ["after"] : []);
			}
		}
	});

	it("rejects cursor use across transcript and candidate views in both directions", async () => {
		write([direct("one", "one.md"), direct("two", "two.md")]);
		const candidates = await read({ maxMessages: 1 });
		const transcript = await readSession({ sessionFile, maxMessages: 1 });
		await assert.rejects(readSession({ sessionFile, after: candidates.nextCursor }), /cursor|view|stale/i);
		await assert.rejects(read({ after: transcript.nextCursor }), /cursor|view|stale/i);
	});

	it("pages at whole-record boundaries when a second intact candidate would exceed the 64 KiB page budget", async () => {
		const paths = ["first-" + "x".repeat(40_000), "second-" + "y".repeat(40_000)];
		write([direct("large-first", paths[0]), direct("large-second", paths[1]), direct("small-last", "last.md")]);
		const first = await read();
		assert.deepEqual(first.candidates.map(c => c.source.aroundEntryId), ["large-first"]);
		assert.equal(first.candidates[0].targets[0].path, paths[0]);
		assert.ok(Buffer.byteLength(JSON.stringify(first.candidates), "utf8") <= 64 * 1024);
		assert.equal(first.hasMore, true);
		assert.equal(first.skippedRecords, 0, "a record that fits its own page is not omitted");
		assert.notEqual(first.incomplete, true);
		const second = await read({ after: first.nextCursor });
		assert.deepEqual(second.candidates.map(c => c.source.aroundEntryId), ["large-second", "small-last"]);
		assert.equal(second.candidates[0].targets[0].path, paths[1]);
		assert.ok(Buffer.byteLength(JSON.stringify(second.candidates), "utf8") <= 64 * 1024);
		assert.equal(second.hasMore, false);
	});

	it("includes the serialized candidate-list overhead in the exact 64 KiB boundary", async () => {
		const expected = { source: { sessionFile, aroundEntryId: "boundary" }, timestamp: time,
			targets: [{ kind: "tool_call", path: "", toolName: "edit", toolCallId: "call-boundary" }] };
		const path = "x".repeat(64 * 1024 - Buffer.byteLength(JSON.stringify([expected]), "utf8"));
		expected.targets[0].path = path;
		assert.equal(Buffer.byteLength(JSON.stringify([expected]), "utf8"), 64 * 1024);
		write([direct("boundary", path)]);
		const exact = await read();
		assert.deepEqual(exact.candidates, [expected]);
		assert.equal(exact.skippedRecords, 0);
		write([direct("boundary", path + "x"), direct("survivor", "survivor.md")]);
		const oversized = await read();
		assert.deepEqual(oversized.candidates.map(c => c.source.aroundEntryId), ["survivor"]);
		assert.equal(oversized.skippedRecords, 1);
		assert.equal(oversized.incomplete, true);
	});

	it("preserves the most recent tail and the centered anchor when size limits shrink the requested window", async () => {
		const ids = ["a", "b", "c"];
		write(ids.map(id => direct(id, id + "x".repeat(40_000))));
		const tail = await read({ tail: true, maxMessages: 3 });
		assert.deepEqual(tail.candidates.map(c => c.source.aroundEntryId), ["c"]);
		assert.equal(tail.hasMore, false);
		assert.ok(Buffer.byteLength(JSON.stringify(tail.candidates), "utf8") <= 64 * 1024);
		const centered = await read({ aroundEntryId: "b", contextMessages: 1, maxMessages: 3 });
		assert.deepEqual(centered.candidates.map(c => c.source.aroundEntryId), ["b"]);
		assert.ok(Buffer.byteLength(JSON.stringify(centered.candidates), "utf8") <= 64 * 1024);
		assert.deepEqual((await read({ after: centered.nextCursor })).candidates.map(c => c.source.aroundEntryId), ["c"]);
	});

	it("omits one oversized candidate intact in UTF-8 bytes, counts the omission once and reaches later evidence", async () => {
		const path = "界".repeat(23_000);
		assert.ok(path.length < 64 * 1024);
		assert.ok(Buffer.byteLength(path, "utf8") > 64 * 1024);
		write([nested("oversized", [recordedCall("edit", "must-not-leak-a-partial-target.md", "first"),
			recordedCall("write", path, "large")]), direct("survivor", "survivor.md")]);
		const result = await read();
		assert.deepEqual(result.candidates.map(c => c.source.aroundEntryId), ["survivor"]);
		assert.equal(result.skippedRecords, 1);
		assert.equal(result.incomplete, true);
		assert.equal(result.hasMore, false);
		const next = await read({ after: result.nextCursor });
		assert.deepEqual(next.candidates, []);
		assert.equal(next.hasMore, false);
	});

	it("applies the raw-record cap before candidate extraction and continues past skipped records", async () => {
		process.env.PI_SESSION_SEARCH_MAX_BYTES = "1024";
		write([message("raw-too-large", [call("edit", "not-returned.md"), { type: "text", text: "x".repeat(2048) }]),
			direct("small", "small.md")]);
		const result = await read();
		assert.deepEqual(result.candidates.map(c => c.source.aroundEntryId), ["small"]);
		assert.equal(result.skippedRecords, 1);
		assert.equal(result.incomplete, true);
	});

	it("resumes appends, including completion of an unterminated trailing candidate", async () => {
		write([direct("first", "first.md")]);
		const initial = await read();
		const pending = JSON.stringify(nested("appended", [recordedCall("write", "appended.md", "appended-call")]));
		const split = Math.floor(pending.length / 2);
		appendFileSync(sessionFile, pending.slice(0, split));
		const waiting = await read({ after: initial.nextCursor });
		assert.deepEqual(waiting.candidates, []);
		appendFileSync(sessionFile, pending.slice(split) + "\n");
		const appended = await read({ after: waiting.nextCursor });
		assert.deepEqual(appended.candidates.map(c => c.source.aroundEntryId), ["appended"]);
		assert.equal(appended.hasMore, false);
	});

	it("continues after a complete candidate at EOF later acquires its newline", async () => {
		writeFileSync(sessionFile, JSON.stringify(header) + "\n" + JSON.stringify(direct("first", "first.md")));
		const first = await read();
		assert.deepEqual(first.candidates.map(c => c.source.aroundEntryId), ["first"]);
		appendFileSync(sessionFile, "\n" + JSON.stringify(direct("second", "second.md")) + "\n");
		assert.deepEqual((await read({ after: first.nextCursor })).candidates.map(c => c.source.aroundEntryId), ["second"]);
	});

	it("supports polling empty candidate histories without mistaking ordinary messages for candidates", async () => {
		write([message("ordinary", "ordinary message", "user")]);
		const parked = await read({ tail: true, maxMessages: 0 });
		assert.deepEqual(parked.candidates, []);
		assert.equal(parked.hasMore, false);
		appendFileSync(sessionFile, JSON.stringify(message("more-context", "still no candidate", "user")) + "\n");
		const empty = await read({ after: parked.nextCursor });
		assert.deepEqual(empty.candidates, []);
		appendFileSync(sessionFile, JSON.stringify(checkpoint("later", ["later.md"])) + "\n");
		const later = await read({ after: empty.nextCursor });
		assert.deepEqual(later.candidates.map(c => c.source.aroundEntryId), ["later"]);
	});

	it("uses zero limits without advancing except at the explicit zero-candidate tail", async () => {
		write([direct("a", "a.md"), direct("b", "b.md"), direct("c", "c.md")]);
		const zero = await read({ maxMessages: 0 });
		assert.deepEqual(zero.candidates, []);
		assert.equal(zero.hasMore, true);
		const first = await read({ after: zero.nextCursor, maxMessages: 1 });
		assert.deepEqual(first.candidates.map(c => c.source.aroundEntryId), ["a"]);
		const paused = await read({ after: first.nextCursor, maxMessages: 0 });
		const rest = await read({ after: paused.nextCursor });
		assert.deepEqual(rest.candidates.map(c => c.source.aroundEntryId), ["b", "c"]);
		const tail = await read({ tail: true, maxMessages: 2 });
		assert.deepEqual(tail.candidates.map(c => c.source.aroundEntryId), ["b", "c"]);
		const parked = await read({ tail: true, maxMessages: 0 });
		assert.deepEqual(parked.candidates, []);
		assert.equal(parked.hasMore, false);
		appendFileSync(sessionFile, JSON.stringify(direct("d", "d.md")) + "\n");
		assert.deepEqual((await read({ after: parked.nextCursor })).candidates.map(c => c.source.aroundEntryId), ["d"]);
	});

	it("centers on candidate entry IDs or nearest timestamps in file order and retains the anchor", async () => {
		write([direct("a", "a.md", "edit", "2026-10-14T09:00:12Z"), message("noise", "not a candidate", "user"),
			checkpoint("b", ["b.md"], "2026-10-14T09:00:08Z"), direct("c", "c.md", "edit", "2026-10-14T09:01:00Z")]);
		const exact = await read({ aroundEntryId: "b", contextMessages: 1, maxMessages: 1 });
		assert.deepEqual(exact.candidates.map(c => c.source.aroundEntryId), ["b"]);
		const next = await read({ after: exact.nextCursor });
		assert.deepEqual(next.candidates.map(c => c.source.aroundEntryId), ["c"]);
		const tied = await read({ aroundTimestamp: "2026-10-14T09:00:10Z", contextMessages: 0, maxMessages: 1 });
		assert.deepEqual(tied.candidates.map(c => c.source.aroundEntryId), ["a"]);
		await assert.rejects(read({ aroundEntryId: "noise" }), /entry|candidate|eligible|found/i);
	});

	it("rejects candidate cursors after truncation, prefix rewrites, file replacement or record-limit changes", async () => {
		for (const change of ["truncate", "rewrite", "replace", "cap"]) {
			delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
			write([direct("a", "a.md"), direct("b", "b.md")]);
			const first = await read({ maxMessages: 1 });
			if (change === "truncate") write([]);
			if (change === "rewrite") write([direct("a", "z.md"), direct("b", "b.md")]);
			if (change === "replace") {
				renameSync(sessionFile, sessionFile + ".old");
				write([direct("a", "a.md"), direct("b", "b.md")]);
			}
			if (change === "cap") process.env.PI_SESSION_SEARCH_MAX_BYTES = "1024";
			await assert.rejects(read({ after: first.nextCursor }), /stale|changed|replac|truncat|limit|cap/i, change);
		}
	});

	it("allows changing an unread suffix without invalidating the candidate prefix receipt", async () => {
		write([direct("a", "a.md"), direct("b", "b.md")]);
		const first = await read({ maxMessages: 1 });
		write([direct("a", "a.md"), checkpoint("changed", ["changed.md"])]);
		assert.deepEqual((await read({ after: first.nextCursor })).candidates.map(c => c.source.aroundEntryId), ["changed"]);
	});

	it("rejects already-aborted and mid-record candidate reads", async () => {
		write([direct("abort-candidate-marker", "a.md"), direct("b", "b.md")]);
		const already = new AbortController();
		already.abort();
		await assert.rejects(read({ signal: already.signal }));
		const controller = new AbortController();
		const originalParse = JSON.parse;
		JSON.parse = function (text: string, reviver?: Parameters<typeof JSON.parse>[1]) {
			const parsed: unknown = originalParse(text, reviver);
			if (text.includes("abort-candidate-marker")) controller.abort();
			return parsed;
		};
		try {
			await assert.rejects(read({ signal: controller.signal }));
			assert.equal(controller.signal.aborted, true);
		} finally {
			JSON.parse = originalParse;
		}
	});

	it("explicitly rejects unsupported Codex candidate reads rather than returning an empty shortlist", async () => {
		writeFileSync(sessionFile, [
			{ type: "session_meta", timestamp: time, payload: { id: "codex-candidate-session", cwd: "/fixture", timestamp: time } },
			{ type: "response_item", timestamp: time, payload: { type: "function_call", name: "edit", call_id: "call",
				arguments: JSON.stringify({ path: "codex-only.md" }) } },
		].map(record => JSON.stringify(record)).join("\n") + "\n");
		await assert.rejects(read(), /unsupported|not supported|only.*Pi|Pi.*only/i);
	});
});
