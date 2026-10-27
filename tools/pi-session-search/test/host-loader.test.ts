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
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import { discoverAndLoadExtensions, SessionManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readSessionWindow, searchSessions } from "../index.ts";

function parameterDescription(parameter: object): string {
	assert.ok("description" in parameter);
	assert.equal(typeof parameter.description, "string");
	return String(parameter.description);
}

it("loads the package through Pi's real TypeScript extension loader", async () => {
	const sandbox = mkdtempSync(join(tmpdir(), "pi-session-host-loader-"));
	try {
		// Isolate discovery from the user's agent settings and project extensions.
		const packageDir = fileURLToPath(new URL("../", import.meta.url));
		const result = await discoverAndLoadExtensions([packageDir], sandbox, join(sandbox, "agent"));
		assert.deepEqual(result.errors, []);
		assert.deepEqual(result.warnings, []);
		assert.equal(result.extensions.length, 1);
		const extension = result.extensions[0];
		assert.deepEqual([...extension.tools.keys()].sort(), ["read_session", "search_sessions"]);
		assert.deepEqual([...extension.commands.keys()], ["find-sessions"]);

		const search = extension.tools.get("search_sessions")?.definition;
		const read = extension.tools.get("read_session")?.definition;
		assert.ok(search);
		assert.ok(read);
		const searchGuidance = (search.promptGuidelines ?? []).join("\n");
		const readGuidance = (read.promptGuidelines ?? []).join("\n");
		assert.match(search.description, /prior discussions or decisions/);
		assert.match(searchGuidance, /focused query.*cwd/);
		assert.match(searchGuidance, /candidates, not complete evidence/);
		assert.match(searchGuidance, /read promising hits with read_session/);
		assert.match(searchGuidance, /deduplicate.*same session or task/);
		assert.match(readGuidance, /sessionFile unchanged.*modest maxMessages/);
		assert.ok(Type.IsObject(search.parameters));
		assert.ok(Type.IsObject(read.parameters));
		const perSessionLimit = search.parameters.properties.maxResultsPerSession;
		assert.ok(Type.IsInteger(perSessionLimit));
		assert.ok("minimum" in perSessionLimit && "maximum" in perSessionLimit);
		assert.equal(perSessionLimit.minimum, 1);
		assert.equal(perSessionLimit.maximum, 1000);
		assert.match(parameterDescription(perSessionLimit), /Omit for no per-session limit/);
		assert.match(parameterDescription(perSessionLimit), /first-encountered matches/);
		assert.match(parameterDescription(read.parameters.properties.sessionId), /Exact session header ID/);
		const originalRoot = process.env.PI_SESSION_SEARCH_ROOT;
		process.env.PI_SESSION_SEARCH_ROOT = join(sandbox, "sessions");
		try {
			const source = SessionManager.create(sandbox, join(sandbox, "sessions", "--native--"));
			source.appendMessage({ role: "user", content: "native ID reader needle", timestamp: 1 });
			// The reader does not consume ctx; exercise the real loaded handler.
			const result = await read.execute("native-read-id", { sessionId: source.getSessionId() },
				undefined, undefined, {} as Parameters<typeof read.execute>[4]);
			assert.notEqual(result.isError, true, JSON.stringify(result.content));
			assert.match(JSON.stringify(result.content), /native ID reader needle/);
			assert.ok(result.details && typeof result.details === "object" && "sessionFile" in result.details);
			assert.equal(result.details.sessionFile, realpathSync(source.getSessionFile()!));
			const resolvedRead = await read.execute("native-read-resolved-path", { sessionFile: result.details.sessionFile as string },
				undefined, undefined, {} as Parameters<typeof read.execute>[4]);
			assert.notEqual(resolvedRead.isError, true, JSON.stringify(resolvedRead.content));
			assert.match(JSON.stringify(resolvedRead.content), /native ID reader needle/);
			source.appendMessage({ role: "user", content: "native ID reader needle again", timestamp: 2 });
			const other = SessionManager.create(sandbox, join(sandbox, "sessions", "--native--"));
			other.appendMessage({ role: "user", content: "native ID reader needle elsewhere", timestamp: 3 });
			const capped = await search.execute("native-capped-search", {
				query: "native ID reader needle", maxResultsPerSession: 1,
			}, undefined, undefined, {} as Parameters<typeof search.execute>[4]);
			assert.notEqual(capped.isError, true, JSON.stringify(capped.content));
			const payload = JSON.parse(capped.content[0].type === "text" ? capped.content[0].text : "") as {
				count: number; sessionsAtLimit: number; truncated: boolean; incompleteCoverage: boolean;
				hits: Array<{ sessionFile: string; timestamp: string }>;
			};
			assert.equal(payload.count, 2, "the loaded tool forwards the cap and still searches the next session");
			assert.equal(payload.sessionsAtLimit, 2);
			assert.equal(payload.truncated, false);
			assert.equal(payload.incompleteCoverage, false);
			assert.equal(new Set(payload.hits.map((hit) => hit.sessionFile)).size, 2);
			assert.ok(capped.details && typeof capped.details === "object" && "sessionsAtLimit" in capped.details);
			assert.equal(capped.details.sessionsAtLimit, payload.sessionsAtLimit);
			for (const hit of payload.hits) {
				const window = await read.execute("native-capped-read", { sessionFile: hit.sessionFile, aroundTimestamp: hit.timestamp },
					undefined, undefined, {} as Parameters<typeof read.execute>[4]);
				assert.match(JSON.stringify(window.content), /native ID reader needle/);
			}
		} finally {
			if (originalRoot === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
			else process.env.PI_SESSION_SEARCH_ROOT = originalRoot;
		}
		assert.match(parameterDescription(search.parameters.properties.query), /substring.*\/regex\/flags/);
		assert.match(parameterDescription(search.parameters.properties.includeToolCalls), /exact tool name or distinctive argument/);
		assert.match(parameterDescription(read.parameters.properties.aroundTimestamp), /search hit's timestamp.*ISO/);
		// Guidelines are rendered without tool-name prefixes. Keep each rule
		// identifiable, and leave parameter syntax in the schema rather than
		// restoring the former 790-character standing guidance.
		const guidelines = [...(search.promptGuidelines ?? []), ...(read.promptGuidelines ?? [])];
		assert.ok(guidelines.every((rule) => /search_sessions|read_session/.test(rule)));
		assert.ok(guidelines.join("\n").length <= 400, "Keep standing guidance compact; document syntax in parameters");
	} finally {
		rmSync(sandbox, { recursive: true, force: true });
	}
});

it("collapses native fork history but keeps a later independent repetition", async () => {
	const root = mkdtempSync(join(tmpdir(), "pi-session-native-fork-"));
	const original = process.env.PI_SESSION_SEARCH_ROOT;
	process.env.PI_SESSION_SEARCH_ROOT = root;
	try {
		const dir = join(root, "--native-project--");
		const source = SessionManager.create("/native/project", dir);
		const message = { role: "user" as const, content: "native-copy-needle", timestamp: 1 };
		source.appendMessage(message);
		const file = source.getSessionFile();
		assert.ok(file);
		const fork = SessionManager.forkFrom(file, "/native/project", dir);
		fork.appendMessage(message);
		const result = await searchSessions({ query: "native-copy-needle" });
		assert.equal(result.hits.length, 2, "the forked copy collapses; the newly recorded occurrence stays");
		assert.equal(result.duplicateHitsSuppressed, 1);
		assert.equal(result.incompleteCoverage, false);
		for (const hit of result.hits) {
			const byFile = await readSessionWindow({ sessionFile: hit.sessionFile, aroundTimestamp: hit.timestamp });
			assert.match(byFile, /native-copy-needle/);
			assert.equal(await readSessionWindow({ sessionId: hit.sessionId, aroundTimestamp: hit.timestamp }), byFile);
		}
	} finally {
		if (original === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = original;
		rmSync(root, { recursive: true, force: true });
	}
});
