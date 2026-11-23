// Use the installed SDK: locked unit-test dependencies predate transcript projections.
import assert from "node:assert/strict";
import { chmod, copyFile, mkdtemp, mkdir, readFile, readdir, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const pkg = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const sdk = await import(pathToFileURL(join(pkg, "dist/index.js")));
const ai = await import(pathToFileURL(join(pkg, "../ai/dist/index.js")));
const extensionDir = resolve("config/pi-agent/pi-extensions");
const endpoint = "https://parent-compaction-offline.invalid/v1";
const model = { id: "fixture-parent", name: "Offline parent", provider: "openai", api: "openai-responses", baseUrl: endpoint,
  reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 2048 };
const checkpoint = "## Objective and authority\nPresent the approved plan and wait for permission.\n## Current work\nKeep the open work.\n## Recovery\nRead the retained transcript.";
const usage = { input: 100, output: 40, cacheRead: 0, cacheWrite: 0, totalTokens: 140, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };

function streamResponse(text, { truncated = false, toolCall = false } = {}) {
  const item = { id: "msg_offline", type: "message", role: "assistant", status: "completed", content: [{ type: "output_text", text, annotations: [] }] };
  const events = [
    ["response.created", { response: { id: "resp_offline", status: "in_progress", model: model.id, output: [] } }],
    ["response.output_item.added", { output_index: 0, item: { ...item, status: "in_progress", content: [] } }],
    ["response.content_part.added", { output_index: 0, content_index: 0, item_id: item.id, part: { type: "output_text", text: "", annotations: [] } }],
    ["response.output_text.delta", { output_index: 0, content_index: 0, item_id: item.id, delta: text }],
    ["response.output_text.done", { output_index: 0, content_index: 0, item_id: item.id, text }],
    ["response.output_item.done", { output_index: 0, item }],
  ];
  const output = [item];
  if (toolCall) {
    const tool = { id: "fc_offline", type: "function_call", call_id: "call_offline", name: "offline_probe", arguments: "{}", status: "completed" };
    events.push(["response.output_item.added", { output_index: 1, item: { ...tool, status: "in_progress", arguments: "" } }],
      ["response.function_call_arguments.done", { output_index: 1, item_id: tool.id, arguments: "{}" }],
      ["response.output_item.done", { output_index: 1, item: tool }]);
    output.push(tool);
  }
  events.push([truncated ? "response.incomplete" : "response.completed", { response: {
    id: "resp_offline", status: truncated ? "incomplete" : "completed", model: model.id, output,
    ...(truncated ? { incomplete_details: { reason: "max_output_tokens" } } : {}),
    usage: { input_tokens: 100, output_tokens: 40, input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 0 } },
  } }]);
  return new Response(events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`).join(""), {
    status: 200, headers: { "content-type": "text/event-stream" },
  });
}

async function fixture(t, { blockImages = false, actualContext = false, attached = false, codemodeMode, agentsInstructions, rootInstructions, includes = {} } = {}) {
  const root = await mkdtemp(join(tmpdir(), "native-parent-compaction-"));
  const cwd = join(root, "project"), agentDir = join(root, "agent"), bin = join(root, "bin");
  await Promise.all([mkdir(cwd), mkdir(agentDir), mkdir(bin)]);
  const guestCwd = join(root, "guest-project"), guestSessions = join(root, "guest-sessions"), guestAgent = join(root, "guest-agent");
  const guestEnv = { CODEX_SANDBOX_TOOL_CONTAINER: "fixture", CODEX_SANDBOX_GUEST_CWD: guestCwd,
    CODEX_SANDBOX_GUEST_REPO: guestCwd, CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({
      [cwd]: guestCwd, [join(root, "sessions")]: guestSessions, [agentDir]: guestAgent,
    }) };
  const savedGuest = Object.fromEntries([...Object.keys(guestEnv), "CODEX_SANDBOX_TOOL_READY_HOST"].map(key => [key, process.env[key]]));
  if (attached) {
    Object.assign(process.env, guestEnv);
    delete process.env.CODEX_SANDBOX_TOOL_READY_HOST;
    await symlink(cwd, guestCwd);
    await symlink(agentDir, guestAgent);
    await symlink(join(root, "sessions"), guestSessions);
    await mkdir(join(cwd, ".agents/sandbox"), { recursive: true });
    await writeFile(join(cwd, ".agents/sandbox/AGENTS.md"), "CURRENT_SANDBOX_AUTHORITY_V1");
  }
  t.after(() => { for (const [key, value] of Object.entries(savedGuest)) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  } });
  const oldAgentDir = process.env.PI_CODING_AGENT_DIR, oldSubagent = process.env.PI_SUBAGENT_ID;
  process.env.PI_CODING_AGENT_DIR = agentDir;
  if (actualContext) delete process.env.PI_SUBAGENT_ID;
  t.after(() => {
    if (oldAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR = oldAgentDir;
    if (oldSubagent === undefined) delete process.env.PI_SUBAGENT_ID; else process.env.PI_SUBAGENT_ID = oldSubagent;
  });
  if (agentsInstructions !== undefined) await writeFile(join(cwd, "AGENTS.md"), agentsInstructions);
  if (rootInstructions !== undefined) await writeFile(join(agentDir, "ROOT.md"), rootInstructions);
  for (const [file, content] of Object.entries(includes)) await writeFile(join(cwd, file), content);
  const installed = join(agentDir, "pi-extensions");
  await mkdir(installed);
  for (const name of await readdir(extensionDir)) {
    if (/\.(ts|md)$/.test(name)) await symlink(join(extensionDir, name), join(installed, name));
  }
  await copyFile(resolve("tests/pi/fixtures/jj-status.sh"), join(bin, "jj"));
  await chmod(join(bin, "jj"), 0o755);
  await Promise.all([writeFile(join(cwd, "jj-status.stdout"), "Working copy changes:\nM pending.py\n"),
    writeFile(join(cwd, "jj-status.stderr"), ""), writeFile(join(cwd, "jj-status.code"), "0")]);
  const requests = [], errors = [], notifications = [];
  let session, text = checkpoint, respond, toolsExecuted = 0;
  const oldFetch = globalThis.fetch, oldPath = process.env.PATH;
  process.env.PATH = `${bin}:${oldPath}`;
  globalThis.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    assert.equal(url, `${endpoint}/responses`, "never access a real service");
    requests.push(JSON.parse(init?.body ?? await input.clone().text()));
    return respond ? respond(input, init) : streamResponse(text);
  };
  t.after(async () => { session?.dispose(); globalThis.fetch = oldFetch; process.env.PATH = oldPath; await rm(root, { recursive: true, force: true }); });
  const settingsManager = sdk.SettingsManager.inMemory({ ...(codemodeMode ? { defaultTools: ["offline_probe", "codemode"] } : {}),
    compaction: { enabled: false, keepRecentTokens: 1 },
    retry: { enabled: false }, providerRetry: { maxRetries: 0 }, transport: "sse", images: { blockImages } });
  const runtime = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
  const manager = sdk.SessionManager.create(cwd, join(root, "sessions"));
  const first = manager.appendMessage({ role: "user", content: "OLD_AUTHORITY: present the plan and wait.", timestamp: 1 });
  manager.appendMessage({ role: "assistant", content: [{ type: "text", text: "Historical plan." }], api: model.api,
    provider: model.provider, model: model.id, usage, stopReason: "stop", timestamp: 2 });
  manager.appendMessage({ role: "user", content: "Keep this recent message verbatim.", timestamp: 3 });
  const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager, noExtensions: true, noSkills: true,
    noPromptTemplates: true, noThemes: true, noContextFiles: !actualContext,
    ...(!actualContext ? { systemPrompt: "BASE_PARENT_PROMPT" } : {}),
    additionalExtensionPaths: [...(attached ? ["guest-tools"] : []), "luna-compaction", "detailed-reasoning", "pi-web-search", "openrouter-output-cap",
      ...(actualContext ? ["pi-instruction-includes", "current-date"] : [])].map(name => join(installed, `${name}.ts`)),
    extensionFactories: [...(codemodeMode ? [sdk.createCodemodeExtension({ mode: codemodeMode, models: false })] : []), pi => {
      pi.registerProvider("openai", { baseUrl: endpoint, api: model.api, apiKey: "sk-offline-dummy", models: [model, { ...model, id: "other-parent" }] });
      pi.registerTool({ name: "offline_probe", label: "Offline", description: "Never execute", parameters: { type: "object", properties: {} },
        execute: async () => { toolsExecuted++; throw Error("No tools"); } });
      if (codemodeMode) for (const exposure of ["codemode", "deferred"]) {
        pi.registerTool({ name: `${exposure}_probe`, exposure, label: exposure, description: `Schema for ${exposure} calls`,
          parameters: { type: "object", properties: { input: { type: "string" } }, required: ["input"] },
          execute: async () => { toolsExecuted++; throw Error("No tools"); } });
      }
      if (!actualContext) pi.on("before_agent_start", () => ({ systemPrompt: "FORCED_PARENT_PROMPT" }));
    }],
  });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  ({ session } = await sdk.createAgentSession({ cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime: runtime,
    sessionManager: manager, model, thinkingLevel: "medium", ...(codemodeMode ? {} : { tools: ["offline_probe"] }) }));
  await session.bindExtensions({ onError: error => errors.push(error), uiContext: { notify: (...args) => notifications.push(args) } });
  return { root, cwd, agentDir, guestCwd, guestSessions, session, manager, requests, errors, notifications, settingsManager, first,
    response: value => { text = value; }, respond: value => { respond = value; }, toolsExecuted: () => toolsExecuted };
}

function textOf(payload) { return JSON.stringify(payload); }
function withoutInput({ input, ...rest }) { return rest; }
function assertCheckpoint(f, result, mode) {
  assert.equal(result.details.requestMode, mode);
  assert.equal(result.details.model.id, f.session.model.id);
  assert.equal(result.details.checkpointLength, checkpoint.length);
  assert.ok(result.summary.startsWith(checkpoint));
  assert.equal(result.summary.match(/## Captured context/g).length, 1);
  assert.equal(result.details.repositoryState.state, "observed");
  assert.equal(result.details.repositoryState.stdout, "Working copy changes:\nM pending.py\n");
  const entry = f.manager.getEntries().findLast(entry => entry.type === "compaction");
  assert.equal(entry.summary, result.summary);
  assert.ok(f.manager.buildSessionProjection().messages.some(message => message.role === "compactionSummary" && message.summary === result.summary));
  const restored = sdk.SessionManager.open(f.manager.getSessionFile());
  const saved = restored.getEntries().findLast(entry => entry.type === "compaction");
  assert.equal(saved.details.captureId, result.details.captureId);
  assert.equal(saved.details.repositoryState.stdout, result.details.repositoryState.stdout);
  const visible = JSON.parse(result.summary.slice(result.summary.lastIndexOf("\n\n{") + 2));
  assert.deepEqual(visible.recovery, { captureId: saved.details.captureId, sessionId: restored.getSessionId(), sessionFile: restored.getSessionFile() });
  assert.equal(f.toolsExecuted(), 0);
  assert.deepEqual(f.errors, []);
}

test("live parent prefix, normal payload hooks and edited finalized suffix reach an accepted checkpoint", async t => {
  const f = await fixture(t);
  await f.session.prompt("Present the plan; do not implement it.");
  const last = f.manager.getBranch().findLast(entry => entry.type === "message" && entry.message.role === "assistant");
  f.manager.appendContextEdit(last.id, { content: "EDITED_FINAL_RESULT: permission is still required." });
  const before = f.manager.getEntries().length;
  const result = await f.session.compact("Preserve the permission limit.");
  assertCheckpoint(f, result, "reused");
  assert.equal(f.requests.length, 2);
  const [normal, summary] = f.requests;
  assert.deepEqual(summary.input.slice(0, normal.input.length), normal.input);
  assert.deepEqual(withoutInput(summary), withoutInput(normal));
  assert.ok(textOf(summary).includes("FORCED_PARENT_PROMPT"));
  assert.ok(textOf(summary).includes("EDITED_FINAL_RESULT"));
  assert.ok(textOf(summary).includes("summarizeThroughConversationMessage"));
  assert.ok(textOf(summary).includes("Preserve the permission limit."));
  assert.equal(summary.reasoning.summary, "detailed");
  assert.ok(summary.tools.some(tool => tool.type === "web_search"));
  assert.equal(f.manager.getEntries().length, before + 1, "only the actual compaction is persisted");
});

test("unchanged real instruction inputs retain the exact warm prefix and run sections", async t => {
  const f = await fixture(t, { actualContext: true, agentsInstructions: "CURRENT_AGENT_RULE\n@rules.md", rootInstructions: "CURRENT_ROOT_RULE",
    includes: { "rules.md": "CURRENT_INCLUDED_RULE" } });
  await f.session.prompt("Present the plan.");
  assertCheckpoint(f, await f.session.compact(), "reused");
  assert.deepEqual(f.requests[1].input.slice(0, f.requests[0].input.length), f.requests[0].input);
  assert.ok(textOf(f.requests[1]).includes("<current_date>"));
  assert.ok(!textOf(f.requests[1]).includes("<current_parent_instructions>"));
});

test("thinking-only rebuild keeps exact input prefix without a redundant authority update", async t => {
  const f = await fixture(t, { actualContext: true, agentsInstructions: "CURRENT_AGENT_RULE", rootInstructions: "CURRENT_ROOT_RULE" });
  await f.session.prompt("Present the plan.");
  f.session.setThinkingLevel("high");
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  assert.deepEqual(f.requests[1].input.slice(0, f.requests[0].input.length), f.requests[0].input);
  assert.ok(!textOf(f.requests[1]).includes("<current_parent_instructions>"));
  assert.equal(f.requests[1].reasoning.effort, "high");
});

test("AGENTS reload introducing a new include reaches the checkpoint and subsequent normal consumer", async t => {
  const f = await fixture(t, { actualContext: true, agentsInstructions: "AGENT_AUTHORITY_V1", rootInstructions: "ROOT_AUTHORITY",
    includes: { "new-file.md": "NEW_INCLUDED_AUTHORITY" } });
  await f.session.prompt("Present the plan.");
  await writeFile(join(f.cwd, "AGENTS.md"), "AGENT_AUTHORITY_V2\n@new-file.md");
  await f.session.reload();
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  const wire = textOf(f.requests[1]);
  const update = wire.slice(wire.lastIndexOf("<current_parent_instructions>"));
  assert.ok(update.includes("AGENT_AUTHORITY_V2"));
  assert.ok(update.includes("NEW_INCLUDED_AUTHORITY"));
  assert.ok(update.includes("ROOT_AUTHORITY"));
  assert.ok(wire.indexOf("AGENT_AUTHORITY_V2") > wire.indexOf("AGENT_AUTHORITY_V1"));
  assert.ok(wire.includes("<current_date>"), "retain the actual run-only section");
  await f.session.prompt("Continue under the current instructions.");
  const continued = textOf(f.requests[2]);
  assert.ok(continued.includes("AGENT_AUTHORITY_V2"));
  assert.ok(continued.includes("NEW_INCLUDED_AUTHORITY"));
  assert.ok(continued.includes("ROOT_AUTHORITY"));
  assert.ok(!continued.includes("<current_parent_instructions>"), "temporary update is not persisted as a turn");
});

test("changed ROOT and include sources append current authority after retained sections", async t => {
  const f = await fixture(t, { actualContext: true, agentsInstructions: "CURRENT_AGENT\n@rules.md", rootInstructions: "ROOT_AUTHORITY_V1",
    includes: { "rules.md": "INCLUDED_AUTHORITY_V1" } });
  await f.session.prompt("Present the plan.");
  await writeFile(join(f.agentDir, "ROOT.md"), "ROOT_AUTHORITY_V2");
  await writeFile(join(f.cwd, "rules.md"), "INCLUDED_AUTHORITY_V2");
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  const wire = textOf(f.requests[1]);
  const update = wire.slice(wire.lastIndexOf("<current_parent_instructions>"));
  assert.ok(update.includes("ROOT_AUTHORITY_V2"));
  assert.ok(update.includes("INCLUDED_AUTHORITY_V2"));
  assert.ok(!update.includes("ROOT_AUTHORITY_V1"));
  assert.ok(!update.includes("INCLUDED_AUTHORITY_V1"));
  assert.ok(wire.indexOf("ROOT_AUTHORITY_V2") > wire.indexOf("ROOT_AUTHORITY_V1"));
  assert.ok(wire.includes("<current_date>"));
});

test("removed ROOT and include directives explicitly supersede their retained historical contributions", async t => {
  const f = await fixture(t, { actualContext: true, agentsInstructions: "AGENT_AUTHORITY_V1\n@rules.md", rootInstructions: "ROOT_AUTHORITY_V1",
    includes: { "rules.md": "INCLUDED_AUTHORITY_V1" } });
  await f.session.prompt("Present the plan.");
  await unlink(join(f.agentDir, "ROOT.md"));
  await writeFile(join(f.cwd, "AGENTS.md"), "AGENT_AUTHORITY_V2");
  await f.session.reload();
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  const wire = textOf(f.requests[1]);
  const update = wire.slice(wire.lastIndexOf("<current_parent_instructions>"));
  assert.ok(update.includes("AGENT_AUTHORITY_V2"));
  assert.ok(update.includes("No ROOT instructions currently apply"));
  assert.ok(update.includes("No expanded instruction includes currently apply"));
  assert.ok(!update.includes("ROOT_AUTHORITY_V1"));
  assert.ok(!update.includes("INCLUDED_AUTHORITY_V1"));
  assert.ok(wire.includes("<current_date>"));
});

test("disabled context discovery does not introduce an on-disk AGENTS file into compaction", async t => {
  const f = await fixture(t, { agentsInstructions: "DISABLED_ON_DISK_AUTHORITY" });
  await f.session.prompt("Present the plan.");
  assertCheckpoint(f, await f.session.compact(), "reused");
  assert.ok(!textOf(f.requests[0]).includes("DISABLED_ON_DISK_AUTHORITY"));
  assert.ok(!textOf(f.requests[1]).includes("DISABLED_ON_DISK_AUTHORITY"));
  assert.deepEqual(f.requests[1].input.slice(0, f.requests[0].input.length), f.requests[0].input);
});

test("manual cold compaction uses current parent projection/settings and normal owned payload transforms", async t => {
  const f = await fixture(t);
  const result = await f.session.compact();
  assertCheckpoint(f, result, "rebuilt");
  assert.equal(f.requests.length, 1);
  const payload = f.requests[0];
  assert.ok(textOf(payload).includes("BASE_PARENT_PROMPT"));
  assert.ok(textOf(payload).includes("OLD_AUTHORITY"));
  assert.equal(payload.reasoning.summary, "detailed");
  assert.ok(payload.tools.some(tool => tool.type === "web_search"));
  assert.equal(payload.prompt_cache_key, f.manager.getSessionId());
});

test("a historical context edit rebuilds rather than resurrecting the cached old authority", async t => {
  const f = await fixture(t);
  await f.session.prompt("Present the plan.");
  f.manager.appendContextEdit(f.first, { content: "NEW_AUTHORITY: stop before implementation." });
  const result = await f.session.compact();
  assertCheckpoint(f, result, "rebuilt");
  assert.ok(textOf(f.requests[1]).includes("NEW_AUTHORITY"));
  assert.ok(!textOf(f.requests[1]).includes("OLD_AUTHORITY"));
});

test("model changes use the new active parent without a dedicated summary model", async t => {
  const f = await fixture(t);
  await f.session.prompt("Present the plan.");
  await f.session.setModel({ ...model, id: "other-parent" });
  const result = await f.session.compact();
  assertCheckpoint(f, result, "rebuilt");
  assert.equal(f.requests[1].model, "other-parent");
});

test("reload keeps manual compaction available without a prior live snapshot", async t => {
  const f = await fixture(t);
  await f.session.prompt("Present the plan.");
  await f.session.reload();
  const result = await f.session.compact();
  assertCheckpoint(f, result, "rebuilt");
  assert.equal(f.requests.length, 2);
});

test("malformed parent response preserves entries and makes only one generation request", async t => {
  const f = await fixture(t);
  f.response("I will implement the task instead.");
  const before = structuredClone(f.manager.getEntries());
  await assert.rejects(f.session.compact(), /Compaction cancelled/);
  assert.deepEqual(f.manager.getEntries(), before);
  assert.equal(f.requests.length, 1);
  assert.equal(f.toolsExecuted(), 0);
});

for (const [name, respond, diagnostic] of [
  ["provider authentication error", () => new Response(JSON.stringify({ error: { message: "Fixture credential rejected", type: "invalid_request_error" } }),
    { status: 401, headers: { "content-type": "application/json" } }), /Fixture credential rejected/],
  ["truncated response with a valid header", () => streamResponse(checkpoint, { truncated: true }), /Compaction ended with length/],
  ["tool call beside otherwise valid checkpoint text", () => streamResponse(checkpoint, { toolCall: true }), /Compaction attempted to call a tool/],
  ["empty response", () => streamResponse(""), /Compaction summary was empty/],
]) {
  test(`${name} preserves saved history without fallback or tool execution`, async t => {
    const f = await fixture(t);
    const before = structuredClone(f.manager.getEntries());
    const saved = await readFile(f.manager.getSessionFile(), "utf8");
    f.respond(respond);
    await assert.rejects(f.session.compact(), /Compaction cancelled/);
    assert.deepEqual(f.manager.getEntries(), before);
    assert.equal(await readFile(f.manager.getSessionFile(), "utf8"), saved);
    assert.equal(f.requests.length, 1);
    assert.equal(f.toolsExecuted(), 0);
    assert.ok(f.notifications.some(([message]) => message.startsWith("Compaction failed; keeping session history:") && diagnostic.test(message)),
      JSON.stringify(f.notifications));
  });
}

test("abort during parent generation preserves history and permits a later explicit compaction", async t => {
  const f = await fixture(t);
  const started = Promise.withResolvers();
  f.respond((input, init) => new Promise((_resolve, reject) => {
    const signal = init?.signal ?? input.signal;
    assert.ok(signal instanceof AbortSignal);
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    started.resolve();
  }));
  const before = structuredClone(f.manager.getEntries());
  const saved = await readFile(f.manager.getSessionFile(), "utf8");
  const compacting = f.session.compact();
  await started.promise;
  f.session.abortCompaction();
  await assert.rejects(compacting, /Compaction cancelled/);
  assert.deepEqual(f.manager.getEntries(), before);
  assert.equal(await readFile(f.manager.getSessionFile(), "utf8"), saved);
  assert.equal(f.requests.length, 1);
  assert.equal(f.toolsExecuted(), 0);
  f.respond(undefined);
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  assert.equal(f.requests.length, 2, "only the explicit second request starts another generation");
});

test("tree navigation discards the abandoned warm request before manual compaction", async t => {
  const f = await fixture(t);
  const target = f.manager.getLeafId();
  await f.session.prompt("ABANDONED_WARM_BRANCH");
  assert.equal((await f.session.navigateTree(target, { summarize: false })).cancelled, false);
  f.manager.appendMessage({ role: "user", content: "NEW_BRANCH_AUTHORITY: wait for permission.", timestamp: 4 });
  f.manager.appendMessage({ role: "assistant", content: [{ type: "text", text: "New branch plan." }], api: model.api,
    provider: model.provider, model: model.id, usage, stopReason: "stop", timestamp: 5 });
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  assert.equal(f.requests.length, 2);
  assert.ok(!textOf(f.requests[1]).includes("ABANDONED_WARM_BRANCH"));
  assert.ok(textOf(f.requests[1]).includes("NEW_BRANCH_AUTHORITY"));
});

for (const warm of [false, true]) {
  test(`shared guest projection accepts ${warm ? "warm" : "cold"} compaction with capture and retained-tail recovery`, async t => {
    const f = await fixture(t, { attached: true, actualContext: true, agentsInstructions: "CURRENT_AGENT_AUTHORITY", rootInstructions: "CURRENT_ROOT_AUTHORITY" });
    if (warm) await f.session.prompt("Present the plan.");
    const before = f.manager.buildSessionProjection().messages;
    const result = await f.session.compact();
    assertCheckpoint(f, result, warm ? "reused" : "rebuilt");
    const payload = f.requests.at(-1);
    assert.ok(textOf(payload).includes(f.guestCwd));
    assert.ok(textOf(payload).includes("CURRENT_SANDBOX_AUTHORITY_V1"));
    assert.ok(textOf(payload).includes("CURRENT_ROOT_AUTHORITY"));
    assert.ok(textOf(payload).includes("<current_date>") || !warm);
    if (warm) {
      assert.deepEqual(payload.input.slice(0, f.requests[0].input.length), f.requests[0].input);
      assert.deepEqual(withoutInput(payload), withoutInput(f.requests[0]));
    }
    assert.equal(f.requests.length, warm ? 2 : 1);
    assert.deepEqual(f.manager.buildSessionProjection().messages.at(-1), before.at(-1));
    const file = f.manager.getSessionFile();
    const guestFile = file.replace(join(f.root, "sessions"), f.guestSessions);
    const reopened = sdk.SessionManager.open(guestFile);
    const saved = reopened.getEntries().findLast(entry => entry.type === "compaction");
    assert.equal(reopened.getSessionId(), f.manager.getSessionId());
    assert.equal(saved.details.captureId, result.details.captureId);
    assert.equal(saved.details.repositoryState.stdout, result.details.repositoryState.stdout);
  });
}

for (const mode of ["on", "only"]) for (const rebuild of [false, true]) {
  test(`actual codemode ${mode} preserves prepared declarations and visibility on ${rebuild ? "thinking rebuild" : "warm compaction"}`, async t => {
    const f = await fixture(t, { attached: true, actualContext: true, codemodeMode: mode, agentsInstructions: "CURRENT_AGENT_RULE" });
    await f.session.prompt("Present the plan without using tools.");
    if (rebuild) f.session.setThinkingLevel("high");
    assertCheckpoint(f, await f.session.compact(), rebuild ? "rebuilt" : "reused");
    const functions = payload => payload.tools.filter(tool => tool.type === "function").sort((a, b) => a.name.localeCompare(b.name));
    const expected = functions(f.requests[0]);
    assert.ok(expected.find(tool => tool.name === "codemode").description.includes("codemode_probe"), "real producer renders callable schemas");
    assert.ok(!expected.some(tool => tool.name === "codemode_probe" || tool.name === "deferred_probe"));
    if (mode === "only") assert.deepEqual(expected.map(tool => tool.name), ["codemode"]);
    assert.deepEqual(functions(f.requests[1]), expected);
    assert.deepEqual(f.requests[1].input.slice(0, f.requests[0].input.length), f.requests[0].input);
  });
}

test("changed actual sandbox instructions invalidate only stale guest system projection", async t => {
  const f = await fixture(t, { attached: true, actualContext: true, agentsInstructions: "CURRENT_AGENT_AUTHORITY" });
  await f.session.prompt("Present the plan.");
  await writeFile(join(f.cwd, ".agents/sandbox/AGENTS.md"), "CURRENT_SANDBOX_AUTHORITY_V2");
  assertCheckpoint(f, await f.session.compact(), "rebuilt");
  const wire = textOf(f.requests[1]);
  assert.ok(wire.includes("CURRENT_SANDBOX_AUTHORITY_V2"));
  assert.ok(!wire.includes("CURRENT_SANDBOX_AUTHORITY_V1"));
  assert.ok(wire.includes(f.guestCwd));
  assert.ok(wire.includes("<current_date>"));
});

test("failed guest instruction expansion preserves saved history without a generation request", async t => {
  const f = await fixture(t, { attached: true, actualContext: true });
  await f.session.prompt("Present the plan.");
  await writeFile(join(f.cwd, ".agents/sandbox/AGENTS.md"), "@missing-required.md");
  const before = structuredClone(f.manager.getEntries());
  const saved = await readFile(f.manager.getSessionFile(), "utf8");
  await assert.rejects(f.session.compact(), /Compaction cancelled/);
  assert.deepEqual(f.manager.getEntries(), before);
  assert.equal(await readFile(f.manager.getSessionFile(), "utf8"), saved);
  assert.equal(f.requests.length, 1);
  assert.ok(f.notifications.some(([message]) => message.includes("instruction include does not exist")));
});
