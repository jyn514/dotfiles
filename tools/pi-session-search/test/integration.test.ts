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
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
	formatHitsForCommand,
	readSessionWindow,
	searchSessions,
} from "../index.ts";

/**
 * Set up a temporary sessions root with a couple of fake JSONL session files
 * in it. Returns the root path so the caller can clean it up.
 */
function buildFixtureSessions(): { root: string; sessionFile: string; sessionId: string } {
	const root = mkdtempSync(join(tmpdir(), "pi-session-search-"));
	// Mimic pi's encoded-cwd directory naming scheme.
	const cwdDir = "--home-tester-project--";
	mkdirSync(join(root, cwdDir));
	const filename = "2026-04-23T06-48-02-781Z_session-1.jsonl";
	const sessionFile = join(root, cwdDir, filename);
	const sessionId = "session-1-id";
	const lines = [
		JSON.stringify({
			type: "session",
			id: sessionId,
			cwd: "/home/tester/project",
			timestamp: "2026-04-23T06:48:02.781Z",
		}),
		JSON.stringify({
			type: "message",
			timestamp: "2026-04-23T06:48:10.000Z",
			message: { role: "user", content: "Have we ever discussed vault-overseer?" },
		}),
		JSON.stringify({
			type: "message",
			timestamp: "2026-04-23T06:48:15.000Z",
			message: {
				role: "assistant",
				content: [{ type: "text", text: "Yes, the ExternalSecret error came up last week." }],
			},
		}),
		JSON.stringify({
			type: "message",
			timestamp: "2026-04-23T06:48:30.000Z",
			message: {
				role: "assistant",
				content: [
					{ type: "toolCall", name: "list_pods", arguments: { ns: "default" } },
				],
			},
		}),
	];
	writeFileSync(sessionFile, lines.join("\n") + "\n", "utf-8");
	return { root, sessionFile, sessionId };
}

describe("searchSessions (integration)", () => {
	const original = process.env.PI_SESSION_SEARCH_ROOT;

	let fixture: ReturnType<typeof buildFixtureSessions>;

	beforeEach(() => {
		fixture = buildFixtureSessions();
		process.env.PI_SESSION_SEARCH_ROOT = fixture.root;
	});

	afterEach(() => {
		if (original === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = original;
	});

	it("finds substring matches in user messages", async () => {
		const r = await searchSessions({ query: "vault-overseer" });
		assert.ok(r.hits.length >= 1);
		const hit = r.hits[0];
		assert.equal(hit.role, "user");
		assert.match(hit.snippet, /vault-overseer/);
		assert.equal(hit.sessionId, fixture.sessionId);
		// sessionFile should be relative to the root, not absolute
		assert.ok(!hit.sessionFile.startsWith("/"));
	});

	it("filters by role", async () => {
		const userOnly = await searchSessions({ query: "vault-overseer", role: "user" });
		assert.ok(userOnly.hits.length >= 1);
		assert.ok(userOnly.hits.every((h) => h.role === "user"));

		const assistantOnly = await searchSessions({ query: "vault-overseer", role: "assistant" });
		assert.equal(assistantOnly.hits.length, 0);
	});

	it("respects --cwd substring filter", async () => {
		const matched = await searchSessions({ query: "vault-overseer", cwd: "tester" });
		assert.ok(matched.hits.length >= 1);

		const missed = await searchSessions({ query: "vault-overseer", cwd: "nonexistent" });
		assert.equal(missed.hits.length, 0);
	});

	it("respects since/until filtering using the filename timestamp", async () => {
		const before = await searchSessions({
			query: "vault-overseer",
			until: "2026-04-22T00:00:00Z",
		});
		assert.equal(before.hits.length, 0, "session is from 2026-04-23, should be filtered out");

		const after = await searchSessions({
			query: "vault-overseer",
			since: "2026-04-23T00:00:00Z",
		});
		assert.ok(after.hits.length >= 1);
	});

	it("optionally searches tool-call names/args", async () => {
		const without = await searchSessions({ query: "list_pods" });
		assert.equal(without.hits.length, 0, "tool calls hidden by default");

		const withTool = await searchSessions({ query: "list_pods", includeToolCalls: true });
		assert.ok(withTool.hits.length >= 1);
		assert.equal(withTool.hits[0].role, "toolCall");
	});

	it("excludes the current session when excludeSessionId matches the header id", async () => {
		const excluded = await searchSessions({
			query: "vault-overseer",
			excludeSessionId: fixture.sessionId,
		});
		assert.equal(excluded.hits.length, 0);
	});

	it("rejects an explicit maxResults=0 (silent coercion was a footgun)", async () => {
		await assert.rejects(
			() => searchSessions({ query: "vault-overseer", maxResults: 0 }),
			/must be an integer in \[1, 1000\]/,
		);
	});

	it("accepts maxResults=undefined (uses default)", async () => {
		const r = await searchSessions({ query: "vault-overseer" });
		assert.ok(r.hits.length >= 1);
	});

	it("skips a symlinked subdirectory that escapes the sessions root", async () => {
		// readdir({withFileTypes: true}).isDirectory() returns false for symlinks,
		// so symlinked subdirs are filtered before our realpath check even runs.
		// We still verify end-to-end: a symlinked subdir's content must not appear.
		const escaped = mkdtempSync(join(tmpdir(), "pi-session-escape-"));
		const escapedFile = join(escaped, "2026-04-23T07-00-00-000Z_evil.jsonl");
		writeFileSync(
			escapedFile,
			[
				JSON.stringify({ type: "session", id: "evil", cwd: "/elsewhere" }),
				JSON.stringify({
					type: "message",
					timestamp: "2026-04-23T07:00:01Z",
					message: { role: "user", content: "vault-overseer outside" },
				}),
			].join("\n"),
			"utf-8",
		);
		const symlinkPath = join(fixture.root, "--evil-symlink--");
		symlinkSync(escaped, symlinkPath, "dir");

		const r = await searchSessions({ query: "vault-overseer" });
		assert.equal(r.hits.length, 1, "symlink-escaped sessions must not appear in results");
		assert.equal(r.hits[0].sessionId, fixture.sessionId);
	});

	it("skips a symlinked .jsonl FILE that escapes the sessions root", async () => {
		// This is the more interesting attack vector: a regular subdir that
		// happens to contain a .jsonl symlinked outside the root. The original
		// implementation would have followed the symlink with readFile.
		const escaped = mkdtempSync(join(tmpdir(), "pi-session-file-escape-"));
		const escapedFile = join(escaped, "secret.jsonl");
		writeFileSync(
			escapedFile,
			[
				JSON.stringify({ type: "session", id: "smuggled", cwd: "/elsewhere" }),
				JSON.stringify({
					type: "message",
					timestamp: "2026-04-23T07:00:01Z",
					message: { role: "user", content: "smuggled vault-overseer content" },
				}),
			].join("\n"),
			"utf-8",
		);
		// Place a symlink to the escaped file inside the legitimate subdir.
		const symlinkInside = join(
			fixture.root,
			"--home-tester-project--",
			"2026-04-24T07-00-00-000Z_symlinked.jsonl",
		);
		symlinkSync(escapedFile, symlinkInside);

		const r = await searchSessions({ query: "smuggled" });
		assert.equal(r.hits.length, 0, "a .jsonl symlinked outside the root must not be read");
		assert.ok(r.skippedFiles >= 1, "skip count should reflect the rejected symlinked file");
	});
});

describe("readSessionWindow (integration)", () => {
	const original = process.env.PI_SESSION_SEARCH_ROOT;

	let fixture: ReturnType<typeof buildFixtureSessions>;

	beforeEach(() => {
		fixture = buildFixtureSessions();
		process.env.PI_SESSION_SEARCH_ROOT = fixture.root;
	});

	afterEach(() => {
		if (original === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = original;
	});

	it("returns a markdown-formatted window for an in-root path", async () => {
		const out = await readSessionWindow({ sessionFile: fixture.sessionFile });
		assert.match(out, /Session session-1-id/);
		assert.match(out, /vault-overseer/);
		assert.match(out, /ExternalSecret error/);
	});

	it("accepts a relative path from search_sessions", async () => {
		const rel = "--home-tester-project--/2026-04-23T06-48-02-781Z_session-1.jsonl";
		const out = await readSessionWindow({ sessionFile: rel });
		assert.match(out, /vault-overseer/);
	});

	it("centers the window around aroundTimestamp when provided", async () => {
		const out = await readSessionWindow({
			sessionFile: fixture.sessionFile,
			aroundTimestamp: "2026-04-23T06:48:15.000Z",
			contextMessages: 0,
			maxMessages: 1,
		});
		// With ctx=0 and max=1, only the assistant message should appear
		assert.match(out, /ExternalSecret error/);
		assert.ok(!out.includes("Have we ever discussed"));
	});

	it("refuses paths that escape the sessions root", async () => {
		await assert.rejects(
			() => readSessionWindow({ sessionFile: "/etc/passwd" }),
			/Refusing to read outside/,
		);
		await assert.rejects(
			() => readSessionWindow({ sessionFile: "../../../etc/passwd" }),
			/Refusing to read outside/,
		);
	});


	it("refuses a symlinked file that escapes the root, even by relative path", async () => {
		const escaped = mkdtempSync(join(tmpdir(), "pi-session-escape-"));
		const escapedFile = join(escaped, "secret.jsonl");
		writeFileSync(escapedFile, "{}", "utf-8");
		const symlinkPath = join(fixture.root, "--evil--", "leak.jsonl");
		mkdirSync(join(fixture.root, "--evil--"));
		symlinkSync(escapedFile, symlinkPath);

		await assert.rejects(
			() => readSessionWindow({ sessionFile: symlinkPath }),
			/Refusing to read outside/,
		);
	});
});


describe("automatic search filtering", () => {
	let fixture: ReturnType<typeof buildFixtureSessions>;
	let original: string | undefined;
	const timestamp = "2026-04-23T06:48:10.000Z";
	const envelope = '<pi_goal_continuation goal_id="goal-1">\nneedle update_goal\n</pi_goal_continuation>';
	const record = (content: unknown, id: string | undefined = "record-1", role = "user") => ({
		type: "message", id, timestamp, message: { role, content },
	});
	function writeSession(records: unknown[], name = "session-1", day = "23", dir = "--home-tester-project--"): string {
		mkdirSync(join(fixture.root, dir), { recursive: true });
		const file = join(fixture.root, dir, `2026-04-${day}T06-48-02-781Z_${name}.jsonl`);
		writeFileSync(file, [
			{ type: "session", id: name, cwd: "/home/tester/project" }, ...records,
		].map((r) => JSON.stringify(r)).join("\n") + "\n");
		return file;
	}
	beforeEach(() => {
		original = process.env.PI_SESSION_SEARCH_ROOT;
		fixture = buildFixtureSessions();
		process.env.PI_SESSION_SEARCH_ROOT = fixture.root;
	});
	afterEach(() => {
		if (original === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = original;
		rmSync(fixture.root, { recursive: true, force: true });
	});

	it("excludes whole text-only user envelopes, not mentions, quotations or mixed content", async () => {
		const retained = [
			"needle: use /goal and update_goal", `needle before ${envelope}`, `${envelope} needle after`,
			`\`\`\`xml\n${envelope}\n\`\`\``, `> ${envelope}`,
			envelope.replace('</pi_goal_continuation>', ''), envelope.replace('goal_id="goal-1"', 'goal_id=""'),
			[{ type: "text", text: envelope }, { type: "image", data: "image" }],
			[{ type: "text", text: envelope }, { type: "thinking", thinking: "extra content" }],
			`${envelope}\nneedle discussion between envelopes\n${envelope}`,
			[{ type: "text", text: envelope }, { type: "text", text: "needle discussion" }, { type: "text", text: envelope }],
		];
		writeSession([
			record(envelope), record([{ type: "text", text: envelope }], "record-2"),
			...retained.map((content, i) => record(content, `retained-${i}`)),
			record(envelope, "assistant-envelope", "assistant"),
		]);
		const result = await searchSessions({ query: "needle" });
		assert.equal(result.hits.length, retained.length + 1);
		assert.equal(result.excludedGoalContinuations, 2);
		assert.equal(result.duplicateHitsSuppressed, 0);
		assert.equal(result.skippedRecords, 0);
		assert.equal(result.incompleteCoverage, false);
		assert.equal(result.hits.filter((hit) => hit.role === "assistant").length, 1);
		// Reading still shows the actual transcript, not the search-filtered view.
		const window = await readSessionWindow({ sessionFile: fixture.sessionFile });
		assert.match(window, /Showing messages 1–14 of 14/);
		assert.ok(window.includes(envelope));
	});

	it("filters before matching and maxResults, with counters even when nothing matches", async () => {
		writeSession([record(envelope), record("ordinary needle", "ordinary")]);
		const result = await searchSessions({ query: "needle", maxResults: 1 });
		assert.equal(result.hits.length, 1);
		assert.equal(result.hits[0].snippet, "ordinary needle");
		assert.equal(result.excludedGoalContinuations, 1);
		assert.equal(result.incompleteCoverage, false);
		assert.match(formatHitsForCommand(result), /Excluded 1 goal continuations; suppressed 0 copied hits in scanned records/);
		const unmatched = await searchSessions({ query: "absent" });
		assert.equal(unmatched.excludedGoalContinuations, 1);
		assert.match(formatHitsForCommand(unmatched), /No matches/);
		assert.match(formatHitsForCommand(unmatched), /Excluded 1 goal continuations/);
		assert.doesNotMatch(formatHitsForCommand(unmatched), /Incomplete coverage/);
	});

	it("collapses cross-file copies while preserving independent or incomplete identities", async () => {
		const copied = record("copied needle");
		const variants = [
			record("copied needle", "different-id"),
			{ ...copied, timestamp: "2026-04-23T06:48:11.000Z" },
			{ ...copied, message: { ...copied.message, metadata: "different" } },
			record("changed needle"),
			{ ...record("idless needle"), id: undefined },
			record("empty-id needle", ""),
			{ ...record("no-timestamp needle"), timestamp: undefined },
		];
		writeSession([copied, ...variants]);
		writeSession([copied, ...variants.slice(4)], "session-2", "24");
		const result = await searchSessions({ query: "needle" });
		assert.equal(result.hits.length, 11);
		assert.equal(result.duplicateHitsSuppressed, 1);
		assert.equal(result.incompleteCoverage, false);
		assert.equal(result.hits.filter((hit) => hit.snippet === "copied needle").length, 4);
		const hit = result.hits.find((hit) => hit.snippet === "changed needle");
		assert.ok(hit);
		assert.match(await readSessionWindow({ sessionFile: hit.sessionFile, aroundTimestamp: hit.timestamp }), /changed needle/);
	});

	it("does not collapse overflowing numeric values into null", async () => {
		const ordinary = { ...record("numeric needle"), message: { role: "user", content: "numeric needle", metadata: null } };
		const source = writeSession([ordinary]);
		writeSession([ordinary], "session-2", "24");
		// Write the numeric literal directly: JSON.stringify(Infinity) would
		// already replace it with null before the reader sees it.
		writeFileSync(source, JSON.stringify({ type: "session", id: "session-1" }) + "\n" +
			JSON.stringify(ordinary).replace('"metadata":null', '"metadata":1e400') + "\n");
		const result = await searchSessions({ query: "numeric needle" });
		assert.equal(result.hits.length, 2);
		assert.equal(result.duplicateHitsSuppressed, 0);
		assert.equal(result.incompleteCoverage, false);
	});

	it("compares complete JSON values regardless of object-key order and keeps hit kinds separate", async () => {
		const content = [
			{ type: "text", text: "needle explanation" },
			{ type: "toolCall", name: "needle_tool", arguments: { first: 1, second: 2 } },
		];
		writeSession([record(content, "assistant-record", "assistant")]);
		writeSession([{
			type: "message", timestamp, id: "assistant-record", message: {
				content: [content[0], { arguments: { second: 2, first: 1 }, name: "needle_tool", type: "toolCall" }],
				role: "assistant",
			},
		}], "session-2", "24");
		writeSession([record([...content].reverse(), "assistant-record", "assistant")], "session-3", "25");
		const result = await searchSessions({ query: "needle", includeToolCalls: true });
		assert.deepEqual(result.hits.map((hit) => hit.role).sort(), ["assistant", "assistant", "toolCall", "toolCall"]);
		assert.equal(result.duplicateHitsSuppressed, 2);
	});

	it("does not collapse repeated records within one file or consume the limit for copied hits", async () => {
		const copied = record("copied needle");
		writeSession([copied]);
		writeSession([copied, copied, record("later needle", "later")], "session-2", "24");
		const result = await searchSessions({ query: "needle", maxResults: 2 });
		assert.equal(result.hits.length, 2);
		assert.deepEqual(result.hits.map((hit) => hit.snippet), ["copied needle", "later needle"]);
		assert.equal(result.duplicateHitsSuppressed, 2);
		writeSession([copied, copied]);
		const sameFile = await searchSessions({ query: "needle", until: "2026-04-23T23:59:59Z" });
		assert.equal(sameFile.hits.length, 2);
		assert.equal(sameFile.duplicateHitsSuppressed, 0);
	});

	it("applies cwd, session-date and current-session scope before deduplication", async () => {
		const copied = record("scoped needle");
		writeSession([copied]);
		writeSession([copied], "session-2", "24", "--other-project--");
		for (const scope of [
			{ cwd: "other" }, { since: "2026-04-24T00:00:00Z" }, { excludeSessionId: "session-1" },
			{ until: "2026-04-23T23:59:59Z" },
		]) {
			const result = await searchSessions({ query: "needle", ...scope });
			assert.equal(result.hits.length, 1);
			assert.equal(result.duplicateHitsSuppressed, 0);
		}
		const assistantOnly = await searchSessions({ query: "needle", role: "assistant" });
		assert.equal(assistantOnly.hits.length, 0);
		assert.equal(assistantOnly.duplicateHitsSuppressed, 0);
	});
});
