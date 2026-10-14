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
import { appendFileSync, mkdirSync, mkdtempSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, it } from "node:test";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";
import { readSession, searchSessions, type Hit, type ReadSessionResult } from "../index.ts";

const timestamp = "2026-10-14T09:00:00.000Z";
const thread = "11111111-1111-4111-8111-111111111111";
const otherThread = "22222222-2222-4222-8222-222222222222";
const thirdThread = "33333333-3333-4333-8333-333333333333";
const rolloutA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const rolloutB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const rolloutC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

type RecordValue = Record<string, unknown>;
interface HistoryBase {
	thread_id: string;
	end_ordinal_exclusive: number;
	end_byte_offset: number;
}

function meta(id = thread, historyBase?: HistoryBase, cwd = "/fixture/codex", time = timestamp): RecordValue {
	return {
		type: "session_meta", timestamp: time, ordinal: historyBase?.end_ordinal_exclusive ?? 0,
		payload: { id, timestamp: time, cwd, history_mode: "paginated", ...(historyBase ? { history_base: historyBase } : {}) },
	};
}
function message(id: string, text: string, ordinal: number, role = "user", time = timestamp): RecordValue {
	return {
		type: "response_item", timestamp: time, ordinal,
		payload: { type: "message", id, role, content: [{ type: role === "assistant" ? "output_text" : "input_text", text }] },
	};
}
function jsonl(records: RecordValue[]): string {
	return records.map(record => JSON.stringify(record) + "\n").join("");
}
function prefixBytes(records: RecordValue[]): number {
	return Buffer.byteLength(jsonl(records), "utf8");
}
function base(id: string, records: RecordValue[], endOrdinal: number): HistoryBase {
	return { thread_id: id, end_ordinal_exclusive: endOrdinal, end_byte_offset: prefixBytes(records) };
}

// These are public-contract tests: fixtures deliberately vary thread identity,
// rollout identity, physical byte prefixes, and logical ordinal prefixes separately.
// A parser refactor or different cursor encoding must leave the assertions intact.
describe("Codex sessions through searchSessions and readSession", () => {
	let root: string;
	let piRoot: string;
	let codexRoot: string;
	let savedEnvironment: Map<string, string | undefined>;
	const environmentKeys = ["PI_SESSION_SEARCH_ROOT", "PI_SESSION_SEARCH_CODEX_ROOT", "PI_SESSION_SEARCH_MAX_BYTES", "CODEX_HOME", "HOME"];

	beforeEach(() => {
		root = mkdtempSync(join(tmpdir(), "pi-search-codex-"));
		piRoot = join(root, "pi");
		codexRoot = join(root, "codex", "sessions");
		mkdirSync(piRoot, { recursive: true });
		mkdirSync(codexRoot, { recursive: true });
		savedEnvironment = new Map(environmentKeys.map(key => [key, process.env[key]]));
		process.env.PI_SESSION_SEARCH_ROOT = piRoot;
		process.env.PI_SESSION_SEARCH_CODEX_ROOT = codexRoot;
		process.env.CODEX_HOME = join(root, "unused-codex-home");
		delete process.env.PI_SESSION_SEARCH_MAX_BYTES;
	});
	afterEach(() => {
		for (const [key, value] of savedEnvironment) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
		rmSync(root, { recursive: true, force: true });
	});

	function writeCodex(records: RecordValue[], id = thread, rollout?: string, day = "2026-10-14"): string {
		const file = join(codexRoot, ...day.split("-"), `rollout-${day}T09-00-00-${id}${rollout ? `_${rollout}` : ""}.jsonl`);
		mkdirSync(dirname(file), { recursive: true });
		writeFileSync(file, jsonl(records));
		return file;
	}
	function writePi(id: string, text: string, name = id): string {
		const file = join(piRoot, "--fixture--", `2026-10-14T09-00-00-000Z_${name}.jsonl`);
		mkdirSync(dirname(file), { recursive: true });
		writeFileSync(file, jsonl([
			{ type: "session", id, cwd: "/fixture/pi", timestamp },
			{ type: "message", id: `pi-${name}`, timestamp, message: { role: "user", content: text } },
		]));
		return file;
	}

	it("searches both roots and reads a Codex hit by its exact absolute file and entry ID", async () => {
		writePi("pi-session", "mixed-source needle");
		const file = writeCodex([meta(), message("codex-target", "mixed-source needle", 1), message("not-target", "later context", 2)]);
		const found = await searchSessions({ query: "mixed-source needle" });
		assert.equal(found.hits.length, 2);
		assert.deepEqual(new Set(found.hits.map(hit => hit.sessionId)), new Set(["pi-session", thread]));
		assert.equal(isAbsolute(found.hits.find(hit => hit.sessionId === "pi-session")!.sessionFile), false, "Pi hit paths retain their relative-path contract");
		const hit = found.hits.find(hit => hit.sessionId === thread)!;
		assert.equal(hit.source, "codex");
		assert.equal(hit.sessionFile, file);
		assert.equal(isAbsolute(hit.sessionFile), true);
		assert.equal(hit.entryId, "codex-target");
		assert.equal(hit.sessionCwd, "/fixture/codex");
		const read = await readSession({ sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 });
		assert.deepEqual(read.messages.map(item => item.entryId), ["codex-target"]);
		assert.match(read.text, /mixed-source needle/);
		assert.doesNotMatch(read.text, /later context/);
		const pi = await readSession({ sessionId: "pi-session" });
		assert.deepEqual(pi.messages.map(item => item.entryId), ["pi-pi-session"]);
	});

	for (const layout of ["parent", "equal"] as const) {
		it(`discriminates authoritative headers when the Pi root is ${layout === "parent" ? "a parent of" : "equal to"} the Codex root`, async () => {
			piRoot = layout === "parent" ? root : codexRoot;
			process.env.PI_SESSION_SEARCH_ROOT = piRoot;
			const original = writeCodex([meta(), message("overlap-codex", "overlapping Codex needle", 1), message("overlap-context", "unrequested Codex context", 2)]);
			// Keep the native basename but use one directory level: in the equal-root
			// case Pi's walker sees this same file before Codex's recursive walker.
			const codexFile = join(codexRoot, "--overlap--", `rollout-2026-10-14T09-00-00-${thread}.jsonl`);
			mkdirSync(dirname(codexFile), { recursive: true });
			renameSync(original, codexFile);
			const piFile = writePi("overlapping-pi", "overlapping Pi needle");
			const found = await searchSessions({ query: "overlapping Codex needle" });
			assert.equal(found.hits.length, 1);
			const hit = found.hits[0];
			assert.equal(hit.source, "codex");
			assert.equal(hit.sessionId, thread);
			assert.equal(hit.sessionFile, codexFile);
			assert.equal(hit.entryId, "overlap-codex");
			const exact = await readSession({ sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 });
			assert.deepEqual(exact.messages.map(item => item.entryId), ["overlap-codex"]);
			assert.match(exact.text, /overlapping Codex needle/);
			assert.doesNotMatch(exact.text, /unrequested Codex context/);
			const byId = await readSession({ sessionId: thread, aroundEntryId: hit.entryId, maxMessages: 1 });
			assert.deepEqual(byId.messages, exact.messages, "a failed Pi-header interpretation must not mark this file as already resolved");
			assert.match(byId.text, /overlapping Codex needle/);

			const piHit = (await searchSessions({ query: "overlapping Pi needle" })).hits;
			assert.equal(piHit.length, 1);
			assert.equal(piHit[0].sessionId, "overlapping-pi");
			assert.equal(isAbsolute(piHit[0].sessionFile), false);
			for (const selector of [{ sessionFile: piFile }, { sessionFile: piHit[0].sessionFile }, { sessionId: "overlapping-pi" }]) {
				const piRead = await readSession(selector);
				assert.deepEqual(piRead.messages.map(item => item.entryId), ["pi-overlapping-pi"]);
				assert.match(piRead.text, /overlapping Pi needle/);
			}
		});
	}

	it("exposes Codex exact reads, version choices, and /find-sessions through Pi's real loader", async () => {
		const firstFile = writeCodex([
			meta(), message("loaded-target", "loader Codex needle", 1), message("first-sentinel", "first full transcript sentinel", 2),
		], thread, rolloutA);
		const secondFile = writeCodex([
			meta(thread, undefined, "/second/loader", "2026-10-15T09:00:00.000Z"),
			message("loaded-other", "second loader version preview", 1), message("second-sentinel", "second full transcript sentinel", 2),
		], thread, rolloutB, "2026-10-15");
		const packageDir = fileURLToPath(new URL("../", import.meta.url));
		const loaded = await discoverAndLoadExtensions([packageDir], root, join(root, "isolated-agent"));
		assert.deepEqual(loaded.errors, []);
		assert.deepEqual(loaded.warnings, []);
		assert.equal(loaded.extensions.length, 1);
		const extension = loaded.extensions[0];
		const search = extension.tools.get("search_sessions")?.definition;
		const read = extension.tools.get("read_session")?.definition;
		const command = extension.commands.get("find-sessions");
		assert.ok(search);
		assert.ok(read);
		assert.ok(command);
		const ctx = { sessionManager: { getHeader: () => ({ id: "current-pi-session" }) } } as Parameters<typeof search.execute>[4];
		const found = await search.execute("loaded-codex-search", { query: "loader Codex needle" }, undefined, undefined, ctx);
		assert.notEqual(found.isError, true, JSON.stringify(found.content));
		assert.equal(found.content[0].type, "text");
		const payload = JSON.parse(found.content[0].type === "text" ? found.content[0].text : "") as { count: number; hits: Hit[] };
		assert.equal(payload.count, 1);
		assert.equal(payload.hits.length, 1);
		const hit = payload.hits[0];
		assert.equal(hit.source, "codex");
		assert.equal(hit.sessionFile, firstFile);
		assert.equal(hit.entryId, "loaded-target");
		const exact = await read.execute("loaded-codex-exact", { sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1 }, undefined, undefined, ctx);
		assert.notEqual(exact.isError, true, JSON.stringify(exact.content));
		assert.match(JSON.stringify(exact.content), /loader Codex needle/);
		assert.doesNotMatch(JSON.stringify(exact.content), /full transcript sentinel/);
		assert.ok(exact.details && typeof exact.details === "object" && "messages" in exact.details);
		assert.deepEqual(exact.details.messages, [{ index: 1, entryId: "loaded-target", role: "user", timestamp }]);

		const chooser = await read.execute("loaded-codex-versions", { sessionId: thread }, undefined, undefined, ctx);
		assert.notEqual(chooser.isError, true, JSON.stringify(chooser.content));
		const details = chooser.details as Omit<ReadSessionResult, "text">;
		assert.deepEqual(details.messages, []);
		assert.equal(details.hasMore, false);
		assert.equal(details.nextCursor, undefined);
		assert.equal(details.versions?.length, 2);
		assert.deepEqual(details.versions?.map(version => version.index), [1, 2]);
		assert.deepEqual(new Set(details.versions?.map(version => version.sessionFile)), new Set([firstFile, secondFile]));
		const chooserText = chooser.content.filter(block => block.type === "text").map(block => block.text).join("\n");
		assert.match(chooserText, /loader Codex needle/);
		assert.match(chooserText, /second loader version preview/);
		assert.doesNotMatch(chooserText, /full transcript sentinel/);
		for (const version of details.versions ?? []) {
			assert.equal(version.sessionId, thread);
			assert.ok(isAbsolute(version.sessionFile));
			assert.ok(version.preview && chooserText.includes(version.preview));
			assert.match(chooserText, new RegExp(`(?:^|\\n)\\s*${version.index}[.)\\]:]`));
		}
		const chosen = details.versions!.find(version => version.sessionFile === secondFile)!;
		const selected = await read.execute("loaded-codex-selected", { sessionFile: chosen.sessionFile }, undefined, undefined, ctx);
		assert.notEqual(selected.isError, true, JSON.stringify(selected.content));
		assert.match(JSON.stringify(selected.content), /second full transcript sentinel/);
		assert.doesNotMatch(JSON.stringify(selected.content), /first full transcript sentinel|loader Codex needle/);

		// Keep the loader's registered handler and its pi.sendMessage closure.
		// Only the public host delivery action and UI notifications are captured.
		const delivered: Array<{
			message: Parameters<typeof loaded.runtime.sendMessage>[0];
			options: Parameters<typeof loaded.runtime.sendMessage>[1];
		}> = [];
		loaded.runtime.sendMessage = (message, options) => { delivered.push({ message, options }); };
		const notifications: string[] = [];
		const commandCtx = {
			sessionManager: { getHeader: () => ({ id: "current-pi-session" }) },
			ui: { notify: (text: string) => { notifications.push(text); } },
		} as unknown as Parameters<typeof command.handler>[1];
		await command.handler("--cwd=/fixture/codex loader Codex needle", commandCtx);
		assert.equal(delivered.length, 1);
		assert.equal(delivered[0].message.customType, "session-search");
		assert.equal(delivered[0].message.display, true);
		assert.deepEqual(delivered[0].options, { triggerTurn: false });
		assert.match(String(delivered[0].message.content), /loader Codex needle/);
		assert.ok(String(delivered[0].message.content).includes(firstFile));
		assert.doesNotMatch(String(delivered[0].message.content), /full transcript sentinel|second loader version preview/);
		assert.ok(notifications.some(text => text.includes("loader Codex needle")));
	});

	it("deduplicates complete Codex payloads without collapsing metadata differences or independent Pi records", async () => {
		const text = "complete-payload needle";
		const plain = message("shared-occurrence", text, 1);
		const classified = message("shared-occurrence", text, 1);
		classified.payload = {
			type: "message", id: "shared-occurrence", role: "user", content: [{ type: "input_text", text }],
			internal_chat_message_metadata_passthrough: { content_item_kinds: ["user.text"] },
		};
		const outside = writeCodex([meta(thread, undefined, "/scope/outside"), plain], thread, rolloutA);
		const inside = writeCodex([meta(thread, undefined, "/scope/inside"), classified], thread, rolloutB, "2026-10-15");
		const copied = writeCodex([meta(thread, undefined, "/scope/inside"), plain], thread, rolloutC, "2026-10-16");
		const piFile = writePi("independent-pi", text);
		writeFileSync(piFile, jsonl([
			{ type: "session", id: "independent-pi", cwd: "/scope/pi", timestamp },
			{ type: "message", id: "shared-occurrence", timestamp, message: { role: "user", content: [{ type: "text", text }] } },
		]));
		const all = await searchSessions({ query: text });
		assert.equal(all.hits.length, 3, "one exact Codex copy collapses, but distinct raw metadata and the independent Pi message survive");
		assert.equal(all.duplicateHitsSuppressed, 1);
		assert.equal(all.hits.filter(hit => hit.source === "codex").length, 2);
		assert.equal(all.hits.filter(hit => hit.sessionId === "independent-pi").length, 1);
		assert.ok(all.hits.some(hit => hit.sessionFile === inside), "the metadata-different Codex payload is retained");
		assert.equal(all.hits.filter(hit => hit.sessionFile === outside || hit.sessionFile === copied).length, 1);
		const scoped = await searchSessions({ query: text, cwd: "/scope/inside" });
		assert.deepEqual(new Set(scoped.hits.map(hit => hit.sessionFile)), new Set([inside, copied]));
		assert.equal(scoped.duplicateHitsSuppressed, 0, "an out-of-scope copy cannot suppress an in-scope occurrence");
		const excluded = await searchSessions({ query: text, excludeSessionId: thread });
		assert.deepEqual(excluded.hits.map(hit => hit.sessionId), ["independent-pi"]);
	});

	it("defaults to CODEX_HOME/sessions without changing the Pi override", async () => {
		delete process.env.PI_SESSION_SEARCH_CODEX_ROOT;
		process.env.CODEX_HOME = join(root, "codex");
		const file = writeCodex([meta(), message("default-home", "home-root needle", 1)]);
		writePi("pi-home", "home-root needle");
		const found = await searchSessions({ query: "home-root needle" });
		assert.equal(found.hits.length, 2);
		assert.equal(found.hits.find(hit => hit.source === "codex")?.sessionFile, file);
	});

	it("defaults to ~/.codex/sessions when neither Codex override is set", { skip: process.platform === "win32" }, async () => {
		delete process.env.PI_SESSION_SEARCH_CODEX_ROOT;
		delete process.env.CODEX_HOME;
		process.env.HOME = root;
		codexRoot = join(root, ".codex", "sessions");
		const file = writeCodex([meta(), message("default-user-home", "user-home needle", 1)]);
		const found = await searchSessions({ query: "user-home needle" });
		assert.deepEqual(found.hits.map(hit => hit.sessionFile), [file]);
	});

	it("treats a missing Codex directory as an empty source, not a failed Pi search", async () => {
		process.env.PI_SESSION_SEARCH_CODEX_ROOT = join(root, "missing");
		writePi("only-pi", "Pi remains searchable");
		const found = await searchSessions({ query: "Pi remains searchable" });
		assert.deepEqual(found.hits.map(hit => hit.sessionId), ["only-pi"]);
	});

	it("uses header thread identity, cwd, and timestamp rather than the filename", async () => {
		const actualTime = "2026-10-16T12:00:00.000Z";
		writeCodex([meta(otherThread, undefined, "/actual/project", actualTime), message("dated", "metadata needle", 1, "user", actualTime)], thread, undefined, "2020-01-01");
		const found = await searchSessions({ query: "metadata needle", cwd: "/actual/project", since: "2026-10-15", until: "2026-10-17" });
		assert.deepEqual(found.hits.map(hit => [hit.sessionId, hit.sessionCwd]), [[otherThread, "/actual/project"]]);
		assert.equal((await searchSessions({ query: "metadata needle", until: "2026-10-15" })).hits.length, 0);
		assert.equal((await searchSessions({ query: "metadata needle", cwd: "2020" })).hits.length, 0);
		assert.equal((await searchSessions({ query: "metadata needle", excludeSessionId: otherThread })).hits.length, 0);
		const read = await readSession({ sessionId: otherThread });
		assert.deepEqual(read.messages.map(item => item.entryId), ["dated"]);
	});

	it("omits event duplicates, developer instructions, reasoning, tool results, and injected user blocks", async () => {
		const filtered = message("mixed", "human text", 2);
		filtered.payload = {
			type: "message", id: "mixed", role: "user",
			content: [{ type: "input_text", text: "human text" }, { type: "input_text", text: "hidden injected marker" }],
			internal_chat_message_metadata_passthrough: { content_item_kinds: ["user.text", "harness.injected"] },
		};
		const file = writeCodex([
			meta(), message("legacy-user", "plain user text", 1), filtered,
			{ type: "event_msg", timestamp, ordinal: 3, payload: { type: "user_message", message: "hidden event marker" } },
			message("developer", "hidden developer marker", 4, "developer"),
			{ type: "response_item", timestamp, ordinal: 5, payload: { type: "reasoning", summary: [{ type: "summary_text", text: "hidden reasoning marker" }] } },
			{ type: "response_item", timestamp, ordinal: 6, payload: { type: "function_call_output", call_id: "call", output: "hidden result marker" } },
			message("answer", "assistant answer", 7, "assistant"),
		]);
		assert.equal((await searchSessions({ query: "hidden", includeToolCalls: true })).hits.length, 0);
		assert.equal((await searchSessions({ query: "human text", role: "assistant" })).hits.length, 0);
		assert.deepEqual((await searchSessions({ query: "text", role: "user" })).hits.map(hit => hit.entryId).sort(), ["legacy-user", "mixed"]);
		const read = await readSession({ sessionFile: file });
		assert.deepEqual(read.messages.map(item => item.entryId), ["legacy-user", "mixed", "answer"]);
		assert.match(read.text, /human text/);
		assert.doesNotMatch(read.text, /hidden/);
	});

	it("preserves user text when classifications are absent, malformed, incomplete, empty, or unknown", async () => {
		const cases: { label: string; kinds?: unknown }[] = [
			{ label: "absent" },
			{ label: "empty list", kinds: [] },
			{ label: "not an array", kinds: "user.text" },
			{ label: "short list", kinds: ["user.text"] },
			{ label: "long list", kinds: ["user.text", "user.text", "user.text"] },
			{ label: "nonstring member", kinds: ["user.text", null] },
			{ label: "empty classifications", kinds: ["", ""] },
			{ label: "future user kinds", kinds: ["user.future_text", "user.other_text"] },
			{ label: "unknown classifications", kinds: ["unknown", "unknown"] },
		];
		for (const { label, kinds } of cases) {
			const item: RecordValue = {
				type: "response_item", timestamp, ordinal: 1,
				payload: { type: "message", id: "classified", role: "user",
					content: [{ type: "input_text", text: "first fallback marker" }, { type: "input_text", text: "second fallback marker" }],
					...(kinds === undefined ? {} : { internal_chat_message_metadata_passthrough: { content_item_kinds: kinds } }),
				},
			};
			const file = writeCodex([meta(), item]);
			for (const query of ["first fallback marker", "second fallback marker"]) {
				assert.deepEqual((await searchSessions({ query })).hits.map(hit => hit.entryId), ["classified"], `${label}: ${query}`);
			}
			const read = await readSession({ sessionFile: file });
			assert.deepEqual(read.messages.map(item => item.entryId), ["classified"], label);
			assert.match(read.text, /first fallback marker/, label);
			assert.match(read.text, /second fallback marker/, label);
		}
	});

	it("reads function and custom tool calls but searches them only when requested", async () => {
		const file = writeCodex([
			meta(),
			{ type: "response_item", timestamp, ordinal: 1, payload: { type: "function_call", id: "function-call", name: "exec_command", arguments: '{"cmd":"tool-needle status"}' } },
			{ type: "response_item", timestamp, ordinal: 2, payload: { type: "custom_tool_call", id: "custom-call", name: "apply_patch", input: "tool-needle patch" } },
		]);
		assert.equal((await searchSessions({ query: "tool-needle" })).hits.length, 0);
		const found = await searchSessions({ query: "tool-needle", includeToolCalls: true });
		assert.deepEqual(found.hits.map(hit => [hit.entryId, hit.role]).sort(), [["custom-call", "toolCall"], ["function-call", "toolCall"]]);
		const read = await readSession({ sessionFile: file });
		assert.deepEqual(read.messages.map(item => item.entryId), ["function-call", "custom-call"]);
		for (const text of ["exec_command", "tool-needle status", "apply_patch", "tool-needle patch"]) assert.ok(read.text.includes(text), text);
	});

	it("returns a numbered version chooser for an ambiguous Codex ID, then reads only the selected file", async () => {
		const firstFile = writeCodex([meta(), message("first-version", "first version preview", 1), message("first-private", "full transcript first sentinel", 2)], thread, rolloutA);
		const secondTime = "2026-10-15T09:00:00.000Z";
		const secondFile = writeCodex([meta(thread, undefined, "/second/cwd", secondTime), message("second-version", "second version preview", 1), message("second-private", "full transcript second sentinel", 2)], thread, rolloutB, "2026-10-15");
		const chooser = await readSession({ sessionId: thread });
		assert.deepEqual(chooser.messages, []);
		assert.equal(chooser.hasMore, false);
		assert.equal(chooser.nextCursor, undefined);
		assert.equal(chooser.skippedRecords, 0);
		assert.doesNotMatch(chooser.text, /full transcript (?:first|second) sentinel/);
		assert.equal(chooser.versions?.length, 2);
		assert.deepEqual(new Set(chooser.versions?.map(version => version.sessionFile)), new Set([firstFile, secondFile]));
		assert.deepEqual(chooser.versions?.map(version => version.index), [1, 2]);
		const expectedVersions = new Map([
			[firstFile, { timestamp, cwd: "/fixture/codex", preview: "first version preview" }],
			[secondFile, { timestamp: secondTime, cwd: "/second/cwd", preview: "second version preview" }],
		]);
		for (const version of chooser.versions ?? []) {
			const expected = expectedVersions.get(version.sessionFile)!;
			assert.equal(version.sessionId, thread);
			assert.equal(isAbsolute(version.sessionFile), true);
			assert.equal(version.timestamp, expected.timestamp);
			assert.equal(version.sessionCwd, expected.cwd);
			assert.ok(version.preview.includes(expected.preview));
			assert.ok(chooser.text.includes(version.preview));
			assert.match(chooser.text, new RegExp(`(?:^|\\n)\\s*${version.index}[.)\\]:]`));
		}
		const first = await readSession({ sessionFile: firstFile });
		const second = await readSession({ sessionFile: secondFile });
		assert.deepEqual(first.messages.map(item => item.entryId), ["first-version", "first-private"]);
		assert.deepEqual(second.messages.map(item => item.entryId), ["second-version", "second-private"]);
		assert.doesNotMatch(first.text, /second version preview/);
		assert.doesNotMatch(second.text, /first version preview/);
	});

	it("keeps duplicate Pi IDs as errors rather than turning them into Codex versions", async () => {
		writePi("duplicate-pi", "first", "one");
		writePi("duplicate-pi", "second", "two");
		await assert.rejects(readSession({ sessionId: "duplicate-pi" }), /ambig|multiple|sessionFile/i);
	});

	it("reconstructs paginated ancestry by rollout identity and pages across physical files", async () => {
		const parentRecords = [meta(), message("parent-1", "ancestor café 🦀", 1), message("parent-2", "second ancestor", 2)];
		writeCodex([...parentRecords, message("parent-unretained", "discarded parent suffix", 3)], thread, rolloutA);
		const childFile = writeCodex([
			meta(thread, base(rolloutA, parentRecords, 3)),
			message("child-3", "child continuation", 4), message("child-4", "last child", 5),
		], thread, rolloutB, "2026-10-15");
		const first = await readSession({ sessionFile: childFile, maxMessages: 1 });
		assert.deepEqual(first.messages.map(item => [item.index, item.entryId]), [[1, "parent-1"]]);
		assert.equal(first.hasMore, true);
		const second = await readSession({ sessionFile: childFile, after: first.nextCursor, maxMessages: 2 });
		assert.deepEqual(second.messages.map(item => [item.index, item.entryId]), [[2, "parent-2"], [3, "child-3"]]);
		const third = await readSession({ sessionFile: childFile, after: second.nextCursor, maxMessages: 2 });
		assert.deepEqual(third.messages.map(item => [item.index, item.entryId]), [[4, "child-4"]]);
		assert.equal(third.hasMore, false);
		assert.doesNotMatch(first.text + second.text + third.text, /discarded parent suffix/);
		const around = await readSession({ sessionFile: childFile, aroundEntryId: "parent-2", maxMessages: 3 });
		assert.deepEqual(around.messages.map(item => item.entryId), ["parent-1", "parent-2", "child-3"]);
	});

	it("resolves a legacy canonical basename as rollout identity without mistaking it for the header thread ID", async () => {
		const parent = [meta(otherThread), message("legacy-parent", "legacy retained", 1)];
		writeCodex(parent, thread);
		const child = writeCodex([meta(thirdThread, base(thread, parent, 2)), message("legacy-child", "legacy child", 3)], thirdThread, rolloutB);
		assert.deepEqual((await readSession({ sessionFile: child })).messages.map(item => item.entryId), ["legacy-parent", "legacy-child"]);
		const found = await searchSessions({ query: "legacy retained" });
		assert.ok(found.hits.length > 0);
		assert.ok(found.hits.every(hit => hit.sessionId !== thread), "basename identity is not header thread identity");
	});

	it("intersects byte and ordinal bounds instead of treating either as an approximate hint", async () => {
		const header = meta();
		const first = message("retained", "UTF-8 prefix: é漢字", 1);
		const second = message("excluded", "must not inherit", 2);
		writeCodex([header, first, second], thread, rolloutA);
		const byteBound = writeCodex([meta(otherThread, base(rolloutA, [header, first], 3)), message("byte-child", "byte-bound child", 4)], otherThread, rolloutB);
		const ordinalBound = writeCodex([meta(thirdThread, base(rolloutA, [header, first, second], 2)), message("ordinal-child", "ordinal-bound child", 3)], thirdThread, rolloutC);
		assert.deepEqual((await readSession({ sessionFile: byteBound })).messages.map(item => item.entryId), ["retained", "byte-child"]);
		assert.deepEqual((await readSession({ sessionFile: ordinalBound })).messages.map(item => item.entryId), ["retained", "ordinal-child"]);
	});

	it("keeps a fork's retained history through a multi-level chain without concatenating sibling versions", async () => {
		const ancestor = [meta(), message("origin", "original retained", 1)];
		writeCodex([...ancestor, message("abandoned", "abandoned ancestor", 2)], thread, rolloutA);
		const middle = [meta(otherThread, base(rolloutA, ancestor, 2)), message("middle", "middle retained", 3)];
		writeCodex([...middle, message("middle-abandoned", "abandoned middle", 4)], otherThread, rolloutB);
		const leaf = writeCodex([meta(thirdThread, base(rolloutB, middle, 4)), message("leaf", "fork leaf", 5)], thirdThread, rolloutC);
		writeCodex([meta(thirdThread), message("unrelated-version", "same thread unrelated history", 1)], thirdThread, "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "2026-10-16");
		const read = await readSession({ sessionFile: leaf });
		assert.deepEqual(read.messages.map(item => [item.index, item.entryId]), [[1, "origin"], [2, "middle"], [3, "leaf"]]);
		assert.doesNotMatch(read.text, /abandoned|unrelated/);
		const tail = await readSession({ sessionFile: leaf, tail: true, maxMessages: 2 });
		assert.deepEqual(tail.messages.map(item => item.entryId), ["middle", "leaf"]);
	});

	it("walks a header-only intermediate version instead of losing its inherited history", async () => {
		const parent = [meta(), message("origin", "retained through empty segment", 1)];
		writeCodex(parent, thread, rolloutA);
		const middle = [meta(otherThread, base(rolloutA, parent, 2))];
		writeCodex(middle, otherThread, rolloutB);
		const leaf = writeCodex([meta(thirdThread, base(rolloutB, middle, 3)), message("leaf", "after empty segment", 4)], thirdThread, rolloutC);
		const first = await readSession({ sessionFile: leaf, maxMessages: 1 });
		assert.deepEqual(first.messages.map(item => item.entryId), ["origin"]);
		const next = await readSession({ sessionFile: leaf, after: first.nextCursor });
		assert.deepEqual(next.messages.map(item => [item.index, item.entryId]), [[2, "leaf"]]);
	});

	it("follows leaf appends while parent growth outside the inherited bound stays invisible", async () => {
		const parent = [meta(), message("parent", "retained parent", 1)];
		const parentFile = writeCodex(parent, thread, rolloutA);
		const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("child", "first child", 3)], otherThread, rolloutB);
		const initial = await readSession({ sessionFile: leaf });
		appendFileSync(parentFile, jsonl([message("parent-growth", "not inherited later", 2)]));
		const empty = await readSession({ sessionFile: leaf, after: initial.nextCursor });
		assert.deepEqual(empty.messages, []);
		appendFileSync(leaf, jsonl([message("leaf-growth", "later leaf append", 4)]));
		const next = await readSession({ sessionFile: leaf, after: empty.nextCursor });
		assert.deepEqual(next.messages.map(item => [item.index, item.entryId]), [[3, "leaf-growth"]]);
		assert.equal(next.hasMore, false);
	});

	it("rejects a cursor when consumed ancestor bytes or ancestor file identity change", async () => {
		for (const change of ["prefix", "replacement"] as const) {
			const parent = [meta(), message("parent", "alpha", 1)];
			const parentFile = writeCodex(parent, thread, rolloutA);
			const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("child", "child", 3)], otherThread, rolloutB);
			const initial = await readSession({ sessionFile: leaf, maxMessages: 1 });
			assert.deepEqual(initial.messages.map(item => item.entryId), ["parent"]);
			if (change === "prefix") writeFileSync(parentFile, jsonl([meta(), message("parent", "omega", 1)]));
			else {
				renameSync(parentFile, parentFile + ".old");
				writeFileSync(parentFile, jsonl(parent));
			}
			await assert.rejects(readSession({ sessionFile: leaf, after: initial.nextCursor }), /stale|changed|replac|cursor/i, change);
		}
	});

	it("allows edits to an ancestor suffix beyond the inherited byte bound", async () => {
		const parent = [meta(), message("parent", "retained parent", 1)];
		const parentFile = writeCodex([...parent, message("unread", "before suffix", 2)], thread, rolloutA);
		const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("child", "leaf continuation", 3)], otherThread, rolloutB);
		const initial = await readSession({ sessionFile: leaf, maxMessages: 1 });
		writeFileSync(parentFile, jsonl([...parent, message("changed", "different unread suffix length", 2)]));
		const next = await readSession({ sessionFile: leaf, after: initial.nextCursor });
		assert.deepEqual(next.messages.map(item => item.entryId), ["child"]);
	});

	it("binds a history cursor to the selected version and rejects a changed lineage reference", async () => {
		const parent = [meta(), message("parent", "same inherited text", 1)];
		writeCodex(parent, thread, rolloutA);
		writeCodex(parent, thread, rolloutC);
		const childRecords = [meta(otherThread, base(rolloutA, parent, 2)), message("child", "child text", 3)];
		const leaf = writeCodex(childRecords, otherThread, rolloutB);
		const sibling = writeCodex(childRecords, otherThread, "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "2026-10-15");
		const first = await readSession({ sessionFile: leaf, maxMessages: 1 });
		await assert.rejects(readSession({ sessionFile: sibling, after: first.nextCursor }), /cursor|file|session|version/i);
		writeFileSync(leaf, jsonl([meta(otherThread, base(rolloutC, parent, 2)), childRecords[1]]));
		await assert.rejects(readSession({ sessionFile: leaf, after: first.nextCursor }), /stale|changed|cursor|history/i);
	});

	it("preserves a zero-message cursor and supports tail-follow across inherited history", async () => {
		const parent = [meta(), message("parent", "parent", 1)];
		writeCodex(parent, thread, rolloutA);
		const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("child", "child", 3)], otherThread, rolloutB);
		const zero = await readSession({ sessionFile: leaf, maxMessages: 0 });
		assert.deepEqual(zero.messages, []);
		assert.equal(zero.hasMore, true);
		assert.deepEqual((await readSession({ sessionFile: leaf, after: zero.nextCursor, maxMessages: 1 })).messages.map(item => item.entryId), ["parent"]);
		const tail = await readSession({ sessionFile: leaf, tail: true, maxMessages: 0 });
		assert.deepEqual(tail.messages, []);
		assert.equal(tail.hasMore, false);
		appendFileSync(leaf, jsonl([message("appended", "future message", 4)]));
		assert.deepEqual((await readSession({ sessionFile: leaf, after: tail.nextCursor })).messages.map(item => [item.index, item.entryId]), [[3, "appended"]]);
	});

	it("does not commit an incomplete trailing leaf record and resumes it when completed", async () => {
		const file = writeCodex([meta(), message("first", "first", 1)]);
		const pending = jsonl([message("pending", "completed later", 2)]);
		const split = Math.floor(pending.length / 2);
		appendFileSync(file, pending.slice(0, split));
		const first = await readSession({ sessionFile: file });
		const waiting = await readSession({ sessionFile: file, after: first.nextCursor });
		assert.deepEqual(waiting.messages, []);
		appendFileSync(file, pending.slice(split));
		assert.deepEqual((await readSession({ sessionFile: file, after: waiting.nextCursor })).messages.map(item => item.entryId), ["pending"]);
	});

	it("fails explicitly for missing history references rather than returning only the child", async () => {
		const file = writeCodex([meta(thread, { thread_id: rolloutA, end_ordinal_exclusive: 2, end_byte_offset: 100 }), message("child", "must not return partial history", 3)], thread, rolloutB);
		await assert.rejects(readSession({ sessionFile: file }), /history|ancestor|reference|missing|found/i);
	});

	it("rejects referenced ancestors that do not declare paginated history", async () => {
		for (const mode of [undefined, "full"]) {
			const parentHeader = meta();
			parentHeader.payload = { id: thread, timestamp, cwd: "/fixture/codex", ...(mode ? { history_mode: mode } : {}) };
			const parent = [parentHeader, message("parent", "unusable history format", 1)];
			writeCodex(parent, thread, rolloutA);
			const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("child", "not a partial success", 3)], otherThread, rolloutB);
			await assert.rejects(readSession({ sessionFile: leaf }), /history|paginated|ancestor|mode/i, String(mode));
		}
	});

	it("detects a history cycle even when the files have different thread IDs", async () => {
		// Solve header byte lengths independently; both references end at a real
		// record boundary, so a bounds error cannot stand in for cycle detection.
		const refA: HistoryBase = { thread_id: rolloutA, end_ordinal_exclusive: 1, end_byte_offset: 0 };
		const refB: HistoryBase = { thread_id: rolloutB, end_ordinal_exclusive: 1, end_byte_offset: 0 };
		for (let i = 0; i < 5; i += 1) {
			refA.end_byte_offset = prefixBytes([meta(thread, refB)]);
			refB.end_byte_offset = prefixBytes([meta(otherThread, refA)]);
		}
		assert.equal(refA.end_byte_offset, prefixBytes([meta(thread, refB)]));
		assert.equal(refB.end_byte_offset, prefixBytes([meta(otherThread, refA)]));
		const fileA = writeCodex([meta(thread, refB)], thread, rolloutA);
		writeCodex([meta(otherThread, refA)], otherThread, rolloutB);
		await assert.rejects(readSession({ sessionFile: fileA }), /cycle|cyclic/i);
	});

	it("enforces the raw-record cap for Codex while preserving later eligible messages", async () => {
		process.env.PI_SESSION_SEARCH_MAX_BYTES = "768";
		const file = writeCodex([meta(), message("oversized", "large needle " + "x".repeat(2048), 1), message("small", "small needle", 2)]);
		const found = await searchSessions({ query: "needle" });
		assert.deepEqual(found.hits.map(hit => hit.entryId), ["small"]);
		assert.equal(found.skippedRecords, 1);
		assert.equal(found.incompleteCoverage, true);
		const read = await readSession({ sessionFile: file });
		assert.deepEqual(read.messages.map(item => [item.index, item.entryId]), [[1, "small"]]);
		assert.equal(read.skippedRecords, 1);
		assert.match(read.text, /incomplete coverage/i);
	});

	it("skips an oversized inherited record without dropping the rest of the history chain", async () => {
		process.env.PI_SESSION_SEARCH_MAX_BYTES = "768";
		const parent = [meta(), message("before-large", "before oversized ancestor", 1), message("large", "x".repeat(2048), 2), message("after-large", "after oversized ancestor", 3)];
		writeCodex(parent, thread, rolloutA);
		const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 4)), message("leaf", "after ancestor segment", 5)], otherThread, rolloutB);
		const read = await readSession({ sessionFile: leaf });
		assert.deepEqual(read.messages.map(item => [item.index, item.entryId]), [[1, "before-large"], [2, "after-large"], [3, "leaf"]]);
		assert.equal(read.skippedRecords, 1);
		assert.match(read.text, /incomplete coverage/i);
	});

	it("contains both direct files and ancestor lookup within the configured roots", { skip: process.platform === "win32" }, async () => {
		const outside = join(root, "outside.jsonl");
		const parent = [meta(), message("secret", "outside-secret needle", 1)];
		writeFileSync(outside, jsonl(parent));
		const alias = join(codexRoot, "2026", "10", "14", `rollout-2026-10-14T09-00-00-${thread}_${rolloutA}.jsonl`);
		mkdirSync(dirname(alias), { recursive: true });
		symlinkSync(outside, alias);
		const found = await searchSessions({ query: "outside-secret" });
		assert.equal(found.hits.length, 0);
		assert.ok(found.skippedFiles >= 1);
		await assert.rejects(readSession({ sessionFile: outside }), /outside|root|contain|within/i);
		await assert.rejects(readSession({ sessionFile: alias }), /outside|root|contain|within/i);
		const leaf = writeCodex([meta(otherThread, base(rolloutA, parent, 2)), message("leaf", "local leaf", 3)], otherThread, rolloutB);
		await assert.rejects(readSession({ sessionFile: leaf }), /history|ancestor|reference|missing|found|outside|root/i);
	});

	it("skips directory symlinks that leave the Codex root", { skip: process.platform === "win32" }, async () => {
		const outsideDir = join(root, "outside-directory");
		mkdirSync(outsideDir);
		writeFileSync(join(outsideDir, `rollout-2026-10-14T09-00-00-${thread}.jsonl`), jsonl([meta(), message("secret", "directory-secret needle", 1)]));
		symlinkSync(outsideDir, join(codexRoot, "escaped"));
		const found = await searchSessions({ query: "directory-secret" });
		assert.deepEqual(found.hits, []);
		await assert.rejects(readSession({ sessionId: thread }), /found|missing|outside|root/i);
	});

	it("honors cancellation without searching Codex after an already-aborted request", async () => {
		const file = writeCodex([meta(), message("cancelled", "cancel needle", 1)]);
		const signal = AbortSignal.abort();
		const found = await searchSessions({ query: "cancel needle", signal });
		assert.deepEqual(found.hits, []);
		assert.equal(found.incompleteCoverage, true);
		await assert.rejects(readSession({ sessionFile: file, signal }), /abort|cancel/i);
	});
});
