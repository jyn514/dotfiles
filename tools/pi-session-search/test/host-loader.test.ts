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
import { mkdtempSync, rmSync } from "node:fs";
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
			assert.match(await readSessionWindow({ sessionFile: hit.sessionFile, aroundTimestamp: hit.timestamp }), /native-copy-needle/);
		}
	} finally {
		if (original === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = original;
		rmSync(root, { recursive: true, force: true });
	}
});
