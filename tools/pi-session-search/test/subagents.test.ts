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
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";
import { readSession, searchSessions } from "../index.ts";

const time = "2026-10-27T11:30:47.502Z";
const keys = ["PI_CODING_AGENT_DIR", "PI_SESSION_SEARCH_ROOT", "PI_SESSION_SEARCH_CODEX_ROOT", "PI_SESSION_SEARCH_SUBAGENT_ROOT"];

describe("subagent transcript discovery", () => {
	let sandbox: string;
	let runs: string;
	let saved: Map<string, string | undefined>;
	beforeEach(() => {
		saved = new Map(keys.map(key => [key, process.env[key]]));
		sandbox = mkdtempSync(join(tmpdir(), "pi-subagent-search-"));
		process.env.PI_CODING_AGENT_DIR = join(sandbox, "agent");
		process.env.PI_SESSION_SEARCH_ROOT = join(sandbox, "sessions");
		process.env.PI_SESSION_SEARCH_CODEX_ROOT = join(sandbox, "no-codex");
		delete process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT;
		runs = join(sandbox, "agent", "pi-codex-subagents", "runs");
	});
	afterEach(() => {
		for (const [key, value] of saved) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
		rmSync(sandbox, { recursive: true, force: true });
	});
	function transcript(root: string, directory: string, id: string): string {
		const dir = join(root, directory);
		mkdirSync(dir, { recursive: true });
		// Native child filenames and parent keys contain no cwd or timestamp.
		const file = join(dir, "worker-record.jsonl");
		writeFileSync(file, [
			{ type: "session", id, timestamp: time, cwd: "/workspace/cocoa" },
			{ type: "message", id: `${id}-a`, timestamp: time, message: { role: "user", content: "subagent discovery needle" } },
			{ type: "message", id: `${id}-b`, timestamp: time, message: { role: "assistant", content: "child reply" } },
		].map(record => JSON.stringify(record)).join("\n") + "\n");
		return realpathSync(file);
	}

	for (const custom of [false, true]) {
		it(`searches ${custom ? "an overridden" : "the native default"} store and reads hits by path and header ID`, async () => {
			if (custom) {
				runs = join(sandbox, "custom-storage");
				process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT = runs;
			}
			const file = transcript(runs, "f6f093d98ba6452f39566f35", "child-id");
			const found = await searchSessions({ query: "subagent discovery needle", cwd: "cocoa", since: "2026-10-27", until: "2026-10-28" });
			assert.equal(found.hits.length, 1);
			assert.equal(found.hits[0].sessionFile, file);
			assert.equal(found.hits[0].sessionCwd, "/workspace/cocoa");
			assert.equal(found.hits[0].sessionId, "child-id");
			const first = await readSession({ sessionFile: found.hits[0].sessionFile, maxMessages: 1 });
			const next = await readSession({ sessionId: "child-id", after: first.nextCursor });
			assert.deepEqual(next.messages.map(m => m.entryId), ["child-id-b"]);
			assert.match(next.text, /child reply/);
			assert.equal((await searchSessions({ query: "subagent discovery needle", cwd: "not-cocoa" })).hits.length, 0);
			assert.equal((await searchSessions({ query: "subagent discovery needle", since: "2026-10-28" })).hits.length, 0);
			assert.equal((await searchSessions({ query: "subagent discovery needle", until: "2026-10-26" })).hits.length, 0);
			assert.equal((await searchSessions({ query: "subagent discovery needle", excludeSessionId: "child-id" })).hits.length, 0);
		});
	}

	it("searches normal and subagent stores together with round-trippable paths", async () => {
		transcript(process.env.PI_SESSION_SEARCH_ROOT!, "--workspace-cocoa--", "parent-id");
		const child = transcript(runs, "parent-key", "child-id");
		const found = await searchSessions({ query: "subagent discovery needle" });
		assert.deepEqual(new Set(found.hits.map(hit => hit.sessionId)), new Set(["parent-id", "child-id"]));
		assert.equal(found.hits.find(hit => hit.sessionId === "child-id")?.sessionFile, child);
		for (const hit of found.hits) {
			assert.match((await readSession({ sessionFile: hit.sessionFile })).text, /child reply/);
		}
	});

	it("keeps normal sessions searchable when the optional subagent store is missing", async () => {
		transcript(process.env.PI_SESSION_SEARCH_ROOT!, "--workspace-cocoa--", "parent-id");
		const found = await searchSessions({ query: "subagent discovery needle" });
		assert.equal(found.hits.length, 1);
		assert.equal(found.hits[0].sessionId, "parent-id");
		assert.equal(found.incompleteCoverage, false);
	});
});
