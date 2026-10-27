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
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, it } from "node:test";
import { spawnSync } from "node:child_process";

import { runCli } from "../cli.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cli = join(root, "cli.ts");

interface Fixture {
	root: string;
	codexRoot: string;
	file: string;
	id: string;
	codexId: string;
}

function buildFixture(): Fixture {
	const sessions = mkdtempSync(join(tmpdir(), "pi-session-cli-"));
	const directory = join(sessions, "--home-tester-project--");
	mkdirSync(directory);
	const file = join(directory, "2026-04-23T06-48-02-781Z_cli.jsonl");
	const id = "cli-session-id";
	writeFileSync(file, [
		JSON.stringify({
			type: "session",
			id,
			cwd: "/home/tester/project",
			timestamp: "2026-04-23T06:48:02.781Z",
		}),
		JSON.stringify({
			type: "message",
			id: "user-entry",
			timestamp: "2026-04-23T06:48:10.000Z",
			message: { role: "user", content: "The CLI parity needle is here." },
		}),
		JSON.stringify({
			type: "message",
			id: "assistant-entry",
			timestamp: "2026-04-23T06:48:15.000Z",
			message: {
				role: "assistant",
				content: [{ type: "text", text: "The assistant needle is here." }],
			},
		}),
		JSON.stringify({
			type: "message",
			id: "tool-entry",
			timestamp: "2026-04-23T06:48:20.000Z",
			message: {
				role: "assistant",
				content: [{ type: "toolCall", name: "distinctive_tool", arguments: { value: "tool needle" } }],
			},
		}),
	].join("\n") + "\n");
	const codexRoot = join(sessions, "codex");
	const codexDirectory = join(codexRoot, "2026", "04", "24");
	mkdirSync(codexDirectory, { recursive: true });
	const codexId = "11111111-1111-4111-8111-111111111111";
	for (const [rollout, text] of [["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "first"], ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "second"]]) {
		writeFileSync(join(codexDirectory, `rollout-2026-04-24T06-48-02-${rollout}.jsonl`), [
			JSON.stringify({
				type: "session_meta", timestamp: "2026-04-24T06:48:02.781Z", ordinal: 0,
				payload: { id: codexId, timestamp: "2026-04-24T06:48:02.781Z", cwd: "/home/tester/codex", history_mode: "paginated" },
			}),
			JSON.stringify({
				type: "response_item", timestamp: "2026-04-24T06:48:10.000Z", ordinal: 1,
				payload: { type: "message", id: `${text}-codex-entry`, role: "user", content: [{ type: "input_text", text: `${text} Codex CLI needle` }] },
			}),
		].join("\n") + "\n");
	}
	return { root: sessions, codexRoot, file, id, codexId };
}

function invoke(fixture: Fixture, args: string[]) {
	return spawnSync(process.execPath, [cli, ...args], {
		cwd: root,
		encoding: "utf8",
		env: {
			...process.env,
			PI_SESSION_SEARCH_ROOT: fixture.root,
			PI_SESSION_SEARCH_CODEX_ROOT: fixture.codexRoot,
		},
	});
}

describe("pi-session-search CLI", () => {
	let fixture: Fixture;

	beforeEach(() => {
		fixture = buildFixture();
	});

	afterEach(() => {
		rmSync(fixture.root, { recursive: true, force: true });
	});

	it("shows top-level and subcommand help without diagnostics", () => {
		for (const args of [[], ["--help"], ["search", "--help"], ["read", "--help"]]) {
			const result = invoke(fixture, args);
			assert.equal(result.status, 0, result.stderr);
			assert.match(result.stdout, /Usage:/);
			assert.equal(result.stderr, "");
		}
	});

	it("reads the authoritative package version", () => {
		const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as { version: string };
		const result = invoke(fixture, ["--version"]);
		assert.equal(result.status, 0, result.stderr);
		assert.equal(result.stdout, manifest.version + "\n");
		assert.equal(result.stderr, "");
	});

	it("serializes the complete SearchResult returned by the API", () => {
		const result = invoke(fixture, [
			"search", "--cwd", "tester/project", "--since", "2026-04-01",
			"--until", "2026-04-30", "--role", "user", "--max-results", "5",
			"--max-results-per-session", "2", "CLI parity needle",
		]);
		assert.equal(result.status, 0, result.stderr);
		assert.deepEqual(JSON.parse(result.stdout), {
			hits: [{
				sessionFile: "--home-tester-project--/2026-04-23T06-48-02-781Z_cli.jsonl",
				sessionId: fixture.id,
				sessionCwd: "/home/tester/project",
				timestamp: "2026-04-23T06:48:10.000Z",
				entryId: "user-entry",
				role: "user",
				snippet: "The CLI parity needle is here.",
			}],
			scannedFiles: 1,
			truncated: false,
			sessionsAtLimit: 0,
			skippedFiles: 0,
			skippedRecords: 0,
			excludedGoalContinuations: 0,
			duplicateHitsSuppressed: 0,
			incompleteCoverage: false,
		});
		assert.equal(result.stderr, "");
	});

	it("maps tool-call and exclusion search options", () => {
		const tool = invoke(fixture, ["search", "--include-tool-calls", "distinctive_tool"]);
		assert.equal(tool.status, 0, tool.stderr);
		assert.equal(JSON.parse(tool.stdout).hits[0].role, "toolCall");

		const excluded = invoke(fixture, ["search", "--exclude-session-id", fixture.id, "assistant needle"]);
		assert.equal(excluded.status, 0, excluded.stderr);
		assert.deepEqual(JSON.parse(excluded.stdout).hits, []);
	});

	it("searches, reads, and reports ambiguous Codex versions", () => {
		const search = invoke(fixture, ["search", "--cwd", "tester/codex", "Codex CLI needle"]);
		assert.equal(search.status, 0, search.stderr);
		const hits = JSON.parse(search.stdout).hits;
		assert.equal(hits.length, 2);
		assert.ok(hits.every((hit: { source?: string }) => hit.source === "codex"));

		const read = invoke(fixture, ["read", "--file", hits[0].sessionFile, "--max-messages", "1"]);
		assert.equal(read.status, 0, read.stderr);
		assert.equal(JSON.parse(read.stdout).messages.length, 1);

		const ambiguous = invoke(fixture, ["read", "--id", fixture.codexId]);
		assert.equal(ambiguous.status, 0, ambiguous.stderr);
		assert.equal(JSON.parse(ambiguous.stdout).versions.length, 2);
	});

	it("serializes the complete ReadSessionResult and preserves zero", () => {
		const result = invoke(fixture, ["read", "--id", fixture.id, "--max-messages", "0"]);
		assert.equal(result.status, 0, result.stderr);
		const parsed = JSON.parse(result.stdout);
		assert.equal(typeof parsed.nextCursor, "string");
		assert.deepEqual(parsed, {
			sessionFile: fixture.file,
			messages: [],
			text: "# Session cli-session-id — cwd: /home/tester/project — started: 2026-04-23T06:48:02.781Z\n"
				+ "# Showing messages 1–0 of 3\n\n"
				+ `# Navigation ${JSON.stringify({ nextCursor: parsed.nextCursor, hasMore: true, skippedRecords: 0 })}`,
			hasMore: true,
			nextCursor: parsed.nextCursor,
			skippedRecords: 0,
		});
		assert.equal(result.stderr, "");
	});

	it("passes centered and tail read selectors through", () => {
		const centered = invoke(fixture, [
			"read", "--file", fixture.file, "--around-entry-id", "assistant-entry",
			"--context-messages", "0", "--max-messages", "1",
		]);
		assert.equal(centered.status, 0, centered.stderr);
		assert.equal(JSON.parse(centered.stdout).messages[0].entryId, "assistant-entry");

		const tail = invoke(fixture, ["read", "--id", fixture.id, "--tail", "--max-messages", "1"]);
		assert.equal(tail.status, 0, tail.stderr);
		assert.equal(JSON.parse(tail.stdout).messages.length, 1);

		const timestamp = invoke(fixture, [
			"read", "--id", fixture.id, "--around-timestamp", "2026-04-23T06:48:15.000Z",
			"--context-messages", "0", "--max-messages", "1",
		]);
		assert.equal(timestamp.status, 0, timestamp.stderr);
		assert.equal(JSON.parse(timestamp.stdout).messages[0].entryId, "assistant-entry");
	});

	it("continues a read from an opaque cursor", () => {
		const first = invoke(fixture, ["read", "--id", fixture.id, "--max-messages", "1"]);
		assert.equal(first.status, 0, first.stderr);
		const cursor = JSON.parse(first.stdout).nextCursor as string;
		assert.ok(cursor);

		const second = invoke(fixture, [
			"read", "--id", fixture.id, "--after", cursor, "--max-messages", "1",
		]);
		assert.equal(second.status, 0, second.stderr);
		assert.equal(JSON.parse(second.stdout).messages[0].entryId, "assistant-entry");
	});

	it("separates usage errors from API errors and leaves stdout empty", () => {
		const usage = invoke(fixture, ["read", "--id", fixture.id, "--file", fixture.file]);
		assert.equal(usage.status, 2);
		assert.equal(usage.stdout, "");
		assert.match(usage.stderr, /requires exactly one/);

		const invalidInteger = invoke(fixture, ["read", "--id", fixture.id, "--max-messages", "1.5"]);
		assert.equal(invalidInteger.status, 2);
		assert.equal(invalidInteger.stdout, "");
		assert.match(invalidInteger.stderr, /non-negative integer/);

		const conflictingSelectors = invoke(fixture, [
			"read", "--id", fixture.id, "--tail", "--around-entry-id", "assistant-entry",
		]);
		assert.equal(conflictingSelectors.status, 1);
		assert.equal(conflictingSelectors.stdout, "");

		const unknown = invoke(fixture, ["search", "--unknown", "needle"]);
		assert.equal(unknown.status, 2);
		assert.equal(unknown.stdout, "");
		assert.match(unknown.stderr, /unknown option/);

		const api = invoke(fixture, ["search", "--max-results", "1001", "needle"]);
		assert.equal(api.status, 1);
		assert.equal(api.stdout, "");
		assert.match(api.stderr, /must be an integer in \[1, 1000\]/);
	});

	it("reports cancellation without a partial success object", async () => {
		const stdout: string[] = [];
		const stderr: string[] = [];
		const controller = new AbortController();
		controller.abort();
		const status = await runCli(
			["search", "needle"],
			{ write: value => stdout.push(value) },
			{ write: value => stderr.push(value) },
			controller.signal,
		);
		assert.equal(status, 130);
		assert.deepEqual(stdout, []);
		assert.deepEqual(stderr, ["pi-session-search: cancelled\n"]);
	});

	it("is directly executable from an unpacked npm artifact", () => {
		const packed = mkdtempSync(join(tmpdir(), "pi-session-search-pack-"));
		try {
			const pack = spawnSync("npm", ["pack", "--json", "--pack-destination", packed], {
				cwd: root, encoding: "utf8",
			});
			assert.equal(pack.status, 0, pack.stderr);
			const [{ filename }] = JSON.parse(pack.stdout) as [{ filename: string }];
			const extract = spawnSync("tar", ["-xzf", join(packed, filename), "-C", packed], {
				encoding: "utf8",
			});
			assert.equal(extract.status, 0, extract.stderr);
			const packageRoot = join(packed, "package");
			symlinkSync(join(root, "node_modules"), join(packageRoot, "node_modules"), "dir");
			const result = spawnSync(join(packageRoot, "cli.ts"), ["--version"], {
				cwd: packageRoot, encoding: "utf8",
			});
			assert.equal(result.status, 0, result.stderr);
			const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as { version: string };
			assert.equal(result.stdout, manifest.version + "\n");
		} finally {
			rmSync(packed, { recursive: true, force: true });
		}
	});
});
