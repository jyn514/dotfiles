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
import {
	createAgentSession,
	createCodemodeExtension,
	DefaultResourceLoader,
	ModelRuntime,
	SessionManager,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";

function toolCallMessage(id: string, name: string, args: Record<string, string>): Parameters<SessionManager["appendMessage"]>[0] {
	return {
		role: "assistant",
		content: [{ type: "toolCall", id, name, arguments: args }],
		api: "openai-responses",
		provider: "openai",
		model: "fixture-model",
		usage: {
			input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "toolUse",
		timestamp: 2,
	};
}

it("Pi codemode shortlists earlier edit candidates and follows native source references", async () => {
	const sandbox = mkdtempSync(join(tmpdir(), "pi-edit-candidates-codemode-"));
	const originalRoot = process.env.PI_SESSION_SEARCH_ROOT;
	const originalCodexRoot = process.env.PI_SESSION_SEARCH_CODEX_ROOT;
	process.env.PI_SESSION_SEARCH_ROOT = join(sandbox, "sessions");
	process.env.PI_SESSION_SEARCH_CODEX_ROOT = join(sandbox, "no-codex-sessions");
	let dispose: (() => void) | undefined;
	try {
		const source = SessionManager.create(sandbox, join(sandbox, "sessions", "--source--"));
		source.appendMessage({ role: "user", content: "Improve the autonomous-work skill.", timestamp: 1 });
		const directPath = "skills/autonomous-work/SKILL.md";
		const nestedPath = "skills/autonomous-work/references/verification.md";
		const checkpointPath = "skills/autonomous-work/references/checkpoint-only.md";
		const cleanupPath = "prompts/cleanup.md";
		const directId = source.appendMessage(toolCallMessage("earlier-edit", "edit", {
			path: directPath, oldText: "direct edit evidence", newText: "updated",
		}));
		// Persist the producer's native message.nestedCalls form, not codemode's UI details.calls.
		const nestedId = source.appendMessage({
			role: "toolResult",
			toolCallId: "earlier-codemode",
			toolName: "codemode",
			content: [{ type: "text", text: "nested edit evidence" }],
			nestedCalls: {
				calls: [{
					id: "earlier-codemode/1", name: "write",
					arguments: { path: nestedPath, content: "updated verification instructions" }, status: "ok",
				}],
				complete: true,
			},
			isError: false,
			timestamp: 3,
		});
		const checkpointId = source.appendCompaction("checkpoint edit evidence", directId, 100, {
			modifiedFiles: [checkpointPath],
		}, true);
		source.appendMessage({ role: "user", content: "Switch assignment: clean up prompts instead.", timestamp: 4 });
		source.appendMessage(toolCallMessage("later-cleanup", "edit", {
			path: cleanupPath, oldText: "unrelated prompt cleanup evidence", newText: "updated",
		}));
		const sourceFile = source.getSessionFile();
		assert.ok(sourceFile);

		// Both extensions load through Pi's public resource loader. The public SDK supplies the
		// actual nested-tool pipeline; no fake executeTool or codemode result adapter is involved.
		const agentDir = join(sandbox, "agent");
		const settingsManager = SettingsManager.inMemory({ cacheWarming: "off" });
		const resourceLoader = new DefaultResourceLoader({
			cwd: sandbox,
			agentDir,
			settingsManager,
			additionalExtensionPaths: [fileURLToPath(new URL("../", import.meta.url))],
			extensionFactories: [createCodemodeExtension({ models: false })],
			noExtensions: true,
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
		});
		await resourceLoader.reload();
		const modelRuntime = await ModelRuntime.create({
			authPath: join(agentDir, "auth.json"),
			modelsPath: null,
			modelsStorePath: join(agentDir, "models-cache.json"),
			allowModelNetwork: false,
			refreshOnCreate: false,
		});
		const model = modelRuntime.getModels()[0];
		assert.ok(model, "the installed Pi peer supplies its static model catalog; no provider call is needed");
		const { session, extensionsResult } = await createAgentSession({
			cwd: sandbox,
			agentDir,
			modelRuntime,
			model,
			settingsManager,
			resourceLoader,
			sessionManager: SessionManager.inMemory(sandbox),
			tools: ["read_session", "codemode"],
		});
		dispose = () => session.dispose();
		assert.deepEqual(extensionsResult.errors, []);
		assert.deepEqual(extensionsResult.warnings, []);
		const codemode = session.state.tools.find((tool) => tool.name === "codemode");
		assert.ok(codemode, "the public createCodemodeExtension registers the real native consumer");
		const expected = [
			{ entryId: directId, path: directPath, kind: "tool_call", marker: "direct edit evidence" },
			{ entryId: nestedId, path: nestedPath, kind: "nested_call", marker: "nested edit evidence" },
			{ entryId: checkpointId, path: checkpointPath, kind: "checkpoint", marker: "checkpoint edit evidence" },
		];
		// The script only consumes candidate objects and spreads their source references into normal
		// reads. It never parses JSON or transcript prose to discover paths or source record formats.
		const code = `
const expected = ${JSON.stringify(expected)};
const sessionId = ${JSON.stringify(source.getSessionId())};
const expectedFile = ${JSON.stringify(realpathSync(sourceFile))};
const all = [];
let after;
let finished = false;
for (let n = 0; n < 20; n++) {
  const page = await tools.read_session({ sessionId, view: "edit_candidates", maxMessages: 1, ...(after ? { after } : {}) });
  if (typeof page !== "object" || page === null || page.view !== "edit_candidates" || !Array.isArray(page.candidates)) {
    throw new Error("candidate view did not reach codemode as structured data");
  }
  if (page.incomplete !== false || page.skippedRecords !== 0) throw new Error("complete fixture reported incomplete");
  all.push(...page.candidates);
  if (!page.hasMore) { finished = true; break; }
  if (!page.nextCursor || page.nextCursor === after) throw new Error("candidate continuation did not advance");
  after = page.nextCursor;
}
if (!finished) throw new Error("candidate pagination did not finish");
if (!all.some(candidate => candidate.targets.some(target => target.path === ${JSON.stringify(cleanupPath)}))) {
  throw new Error("fixture did not expose the later unrelated assignment");
}
const selected = all.filter(candidate => candidate.targets.some(target => target.path.includes("skills/autonomous-work/")));
if (selected.length !== expected.length) throw new Error("expected three earlier source records, got " + selected.length);
for (const wanted of expected) {
  const candidate = selected.find(candidate => candidate.source.aroundEntryId === wanted.entryId);
  if (!candidate || candidate.source.sessionFile !== expectedFile || typeof candidate.timestamp !== "string") {
    throw new Error("missing usable source reference for " + wanted.kind);
  }
  if (!candidate.targets.some(target => target.kind === wanted.kind && target.path === wanted.path)) {
    throw new Error("missing recorded path or source kind: " + wanted.kind);
  }
  const inspection = await tools.read_session({ ...candidate.source, maxMessages: 1, contextMessages: 0 });
  if (typeof inspection !== "string" || !inspection.includes(wanted.marker)) {
    throw new Error("source inspection failed for " + wanted.kind);
  }
}
for (const args of [{ sessionId, maxMessages: 1 }, { sessionId, view: "transcript", maxMessages: 1 }]) {
  const transcript = await tools.read_session(args);
  if (typeof transcript !== "string" || !transcript.includes("Improve the autonomous-work skill.")) {
    throw new Error("ordinary codemode reads must remain transcript strings");
  }
}
return "selected and inspected direct, nested, and checkpoint candidates; ordinary reads remain strings";
`;
		// The nested-tool API requires an issuing assistant message. Seed that native state without
		// contacting a model, then invoke the registered codemode tool with its real session context.
		session.sessionManager.appendMessage(toolCallMessage("candidate-shortlist", "codemode", { code }));
		session.refreshContext();
		const result = await codemode.execute("candidate-shortlist", { code }, new AbortController().signal);
		const text = result.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
		assert.notEqual(result.isError, true, text);
		assert.match(text, /Script completed/);
		assert.match(text, /selected and inspected direct, nested, and checkpoint candidates; ordinary reads remain strings/);
		const read = session.getToolDefinition("read_session");
		assert.ok(read?.outputSchema, "the registered tool must declare its structured output to Pi");
		const ordinary = await read.execute("ordinary-native-read", { sessionFile: sourceFile, maxMessages: 1 },
			undefined, undefined, session.extensionRunner.createToolContext("ordinary-native-read", undefined));
		assert.equal(typeof ordinary.structuredContent, "string", "ordinary reads keep string structuredContent");
	} finally {
		dispose?.();
		if (originalRoot === undefined) delete process.env.PI_SESSION_SEARCH_ROOT;
		else process.env.PI_SESSION_SEARCH_ROOT = originalRoot;
		if (originalCodexRoot === undefined) delete process.env.PI_SESSION_SEARCH_CODEX_ROOT;
		else process.env.PI_SESSION_SEARCH_CODEX_ROOT = originalCodexRoot;
		rmSync(sandbox, { recursive: true, force: true });
	}
});
