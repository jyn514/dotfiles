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
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdtemp, readdir, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";
import { readSession, type ReadSessionResult, type SearchResult } from "../index.ts";

async function recordingFiles(root: string): Promise<string[]> {
	const files: string[] = [];
	for (const entry of await readdir(root, { withFileTypes: true })) {
		const file = path.join(root, entry.name);
		if (entry.isDirectory()) files.push(...await recordingFiles(file));
		else if (entry.isFile() && entry.name.endsWith(".jsonl")) files.push(file);
	}
	return files.sort();
}

async function checksum(file: string): Promise<string> {
	const hash = createHash("sha256");
	for await (const bytes of createReadStream(file)) hash.update(bytes);
	return hash.digest("hex");
}

const corpus = process.env.PI_SESSION_SEARCH_TEST_CODEX_ROOT;

// Opt-in, read-only integration against user-supplied recordings. The synthetic
// suite owns decoding expectations; this checks real-data round trips and paging,
// not that every possible Codex item type projects into conversation text.
it("round-trips real Codex recordings through Pi's loader without changing them", { skip: !corpus }, async (t) => {
	const root = await realpath(corpus!);
	const files = await recordingFiles(root);
	assert.ok(files.length > 0, "the supplied corpus must contain JSONL recordings");
	const before = await Promise.all(files.map(file => checksum(file)));
	const sandbox = await mkdtemp(path.join(tmpdir(), "codex-recordings-"));
	const saved = [process.env.PI_SESSION_SEARCH_ROOT, process.env.PI_SESSION_SEARCH_CODEX_ROOT];
	process.env.PI_SESSION_SEARCH_ROOT = path.join(sandbox, "no-pi-history");
	process.env.PI_SESSION_SEARCH_CODEX_ROOT = root;
	try {
		const loaded = await discoverAndLoadExtensions([fileURLToPath(new URL("../", import.meta.url))], sandbox, path.join(sandbox, "agent"));
		assert.deepEqual(loaded.errors, []);
		assert.deepEqual(loaded.warnings, []);
		const search = loaded.extensions[0].tools.get("search_sessions")!.definition;
		const read = loaded.extensions[0].tools.get("read_session")!.definition;
		const ctx = {} as Parameters<typeof read.execute>[4];
		const searchResult = await search.execute("recording-search", {
			query: "/[\\s\\S]/", includeToolCalls: true, maxResults: 1000,
		}, undefined, undefined, ctx);
		assert.notEqual(searchResult.isError, true);
		assert.equal(searchResult.content[0].type, "text");
		const found = JSON.parse(searchResult.content[0].type === "text" ? searchResult.content[0].text : "") as SearchResult;
		assert.equal(found.incompleteCoverage, false);
		assert.ok(found.hits.length > 0, "recordings must contain searchable conversation items");
		for (const hit of found.hits) {
			const result = await read.execute("recording-exact", {
				sessionFile: hit.sessionFile, aroundEntryId: hit.entryId, maxMessages: 1,
			}, undefined, undefined, ctx);
			assert.notEqual(result.isError, true);
			const details = result.details as Omit<ReadSessionResult, "text">;
			assert.deepEqual(details.messages.map(m => m.entryId), [hit.entryId]);
		}
		for (const file of files) {
			const sweeps: Array<Array<string | undefined>> = [];
			for (const pageSize of [7, 30]) {
				const ids: Array<string | undefined> = [];
				let after: string | undefined;
				while (true) {
					const page = await readSession({ sessionFile: file, maxMessages: pageSize, after });
					assert.ok(page.nextCursor);
					assert.equal(page.skippedRecords, 0);
					for (const message of page.messages) {
						assert.equal(message.index, ids.length + 1);
						ids.push(message.entryId);
					}
					assert.ok(!page.hasMore || page.messages.length > 0, "paging must make progress");
					after = page.nextCursor;
					if (!page.hasMore) break;
				}
				assert.deepEqual((await readSession({ sessionFile: file, after })).messages, []);
				sweeps.push(ids);
			}
			assert.deepEqual(sweeps[0], sweeps[1]);
			const tail = await readSession({ sessionFile: file, tail: true, maxMessages: 3 });
			assert.deepEqual(tail.messages.map(m => m.entryId), sweeps[0].slice(-3));
		}
		for (const id of new Set(found.hits.map(hit => hit.sessionId))) {
			const result = await read.execute("recording-id", { sessionId: id }, undefined, undefined, ctx);
			assert.notEqual(result.isError, true);
			const details = result.details as Omit<ReadSessionResult, "text">;
			if (!details.versions) continue;
			assert.deepEqual(details.messages, []);
			assert.equal(details.nextCursor, undefined);
			for (const [index, version] of details.versions.entries()) {
				assert.equal(version.index, index + 1);
				const selected = await read.execute("recording-choice", { sessionFile: version.sessionFile, maxMessages: 1 }, undefined, undefined, ctx);
				assert.notEqual(selected.isError, true);
			}
		}
		assert.deepEqual(await Promise.all(files.map(file => checksum(file))), before, "recordings must remain byte-identical");
		t.diagnostic(`${files.length} recordings; ${found.hits.length} retained hits checked through the real loader${found.truncated ? " (search limit reached)" : ""}`);
	} finally {
		for (const [i, key] of ["PI_SESSION_SEARCH_ROOT", "PI_SESSION_SEARCH_CODEX_ROOT"].entries()) {
			if (saved[i] === undefined) delete process.env[key];
			else process.env[key] = saved[i];
		}
		await rm(sandbox, { recursive: true, force: true });
	}
});
