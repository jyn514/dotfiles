import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test, type TestContext } from "node:test";

import {
  createAssistantMessageEventStream,
  InMemoryCredentialStore,
  type AssistantMessage,
  type StreamFunction,
} from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

import goalExtension from "../src/index.ts";
import { CONTINUATION_RETRY_MS } from "../src/runtime-config.ts";
import { reconstructGoal } from "../src/state.ts";
import { CUSTOM_ENTRY_TYPE } from "../src/types.ts";

function assistantResponse(
  model: Parameters<StreamFunction>[0],
  contextTokens: number,
  content: string | AssistantMessage["content"],
): ReturnType<StreamFunction> {
  const stream = createAssistantMessageEventStream();
  const parts: AssistantMessage["content"] = typeof content === "string" ? [{ type: "text", text: content }] : content;
  const stopReason = parts.some((part) => part.type === "toolCall") ? "toolUse" : "stop";
  const message: AssistantMessage = {
    role: "assistant",
    content: parts,
    api: model.api,
    provider: model.provider,
    model: model.id,
    usage: {
      input: contextTokens - 1,
      output: 1,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: contextTokens,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason,
    timestamp: Date.now(),
  };
  queueMicrotask(() => {
    stream.push({ type: "start", partial: message });
    stream.push({ type: "done", reason: stopReason, message });
    stream.end();
  });
  return stream;
}

test("SDK completion report includes its calling response exactly once", async () => {
  const modelRuntime = await ModelRuntime.create({
    allowModelNetwork: false,
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
  });
  const loader = new DefaultResourceLoader({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    noContextFiles: true,
    noExtensions: true,
    extensionFactories: [goalExtension],
  });
  await loader.reload();
  modelRuntime.registerProvider("sdk-smoke", { apiKey: "test" });
  const { session } = await createAgentSession({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    model: {
      provider: "sdk-smoke",
      id: "completion",
      name: "SDK Completion Smoke",
      api: "openai-completions",
      baseUrl: "http://localhost",
      reasoning: false,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 1_000_000,
      maxTokens: 1_000,
    },
    modelRuntime,
    noTools: "builtin",
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(process.cwd()),
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
  });
  let requests = 0;
  let providerPrompt = "";
  session.agent.streamFunction = (model, context) => {
    requests += 1;
    if (requests === 1) providerPrompt = JSON.stringify(context.messages);
    if (requests > 2) {
      assert.equal(requests, 3, "completed goals must not queue another continuation");
      return assistantResponse(model, 7, "Done");
    }
    return assistantResponse(model, requests === 1 ? 410_000 : 100_000, [{
      type: "toolCall",
      id: `call-${requests}`,
      name: requests === 1 ? "get_goal" : "update_goal",
      arguments: requests === 1 ? {} : { status: "complete" },
    }]);
  };
  try {
    const runner = session.extensionRunner;
    const createGoal = runner.getToolDefinition("create_goal");
    assert.ok(createGoal);
    await createGoal.execute("create", { objective: "ship it", token_budget: 500_000 },
      undefined, undefined, runner.createToolContext("create", undefined));
    await session.prompt("Complete the goal");

    // Check the actual provider transcript, including all three tools, not
    // just one producer's guidelines. Repeated inline aliases are noise.
    assert.deepEqual(providerPrompt.match(/\bpi__\w+_goal\b/g), ["pi__update_goal"]);
    assert.match(providerPrompt, /every explicit requirement has concrete verification evidence and no required work remains/);
    assert.match(providerPrompt, /Only explicit \/goal resume reactivates a blocked goal; ordinary input does not/);
    assert.equal(providerPrompt.match(/For a tracked goal requesting implementation through verified completion/g)?.length, 1,
      "model-created goals receive skill routing through standing guidance without a command continuation");
    assert.match(providerPrompt, /read the autonomous-implementation skill file at its advertised path, if available, when starting or resuming work/);
    assert.match(providerPrompt, /Do not activate this skill for plan-only, review, research, or writing goals/);

    const entries = session.sessionManager.getBranch();
    const goal = reconstructGoal(entries).goal;
    assert.equal(goal?.status, "complete");
    assert.equal(goal?.usage.tokensUsed, 510_000);
    const result = entries.find((entry) =>
      entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "update_goal");
    assert.match(JSON.stringify(result), /tokens used: 510,000 of 500,000/);
    assert.equal(requests, 3);
  } finally {
    session.dispose();
  }
});

function goalIdFromToolResult(result: unknown): string {
  assert.ok(result && typeof result === "object");
  const details = (result as { details?: unknown }).details;
  assert.ok(details && typeof details === "object");
  const goal = (details as { goal?: unknown }).goal;
  assert.ok(goal && typeof goal === "object");
  const goalId = (goal as { goalId?: unknown }).goalId;
  if (typeof goalId !== "string") {
    assert.fail("Expected tool result goal id.");
  }
  return goalId;
}

test("SDK runtime uses Pi settings for the sole persisted threshold compaction", async () => {
  const modelRuntime = await ModelRuntime.create({
    allowModelNetwork: false,
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
  });
  const loader = new DefaultResourceLoader({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    noContextFiles: true,
    noExtensions: true,
    extensionFactories: [goalExtension],
  });
  await loader.reload();

  modelRuntime.registerProvider("sdk-smoke", {
    api: "openai-completions",
    apiKey: "test",
    baseUrl: "http://localhost",
    models: [{
      id: "compaction",
      name: "SDK Compaction Smoke",
      reasoning: false,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 272_000,
      maxTokens: 1_000,
    }],
  });
  const model = modelRuntime.getModel("sdk-smoke", "compaction");
  assert.ok(model);
  const sessionManager = SessionManager.inMemory(process.cwd());
  const { session } = await createAgentSession({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    model,
    modelRuntime,
    noTools: "builtin",
    resourceLoader: loader,
    sessionManager,
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: true, reserveTokens: 16_834, keepRecentTokens: 40_000 },
    }),
  });

  let nextContextTokens = 247_783;
  let streamCalls = 0;
  session.agent.streamFunction = (activeModel) => {
    streamCalls += 1;
    return assistantResponse(
      activeModel,
      nextContextTokens,
      streamCalls === 1 ? "x".repeat(200_000) : "summary",
    );
  };

  try {
    await session.prompt("below configured threshold");
    assert.equal(sessionManager.getEntries().filter((entry) => entry.type === "compaction").length, 0);

    nextContextTokens = 255_167;
    await session.prompt("above configured threshold");

    assert.equal(sessionManager.getEntries().filter((entry) => entry.type === "compaction").length, 1);
  } finally {
    session.dispose();
  }
});

test("SDK runtime emits a continuation after willRetry compaction when no retry agent starts", async () => {
  const modelRuntime = await ModelRuntime.create({
    allowModelNetwork: false,
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
  });
  const loader = new DefaultResourceLoader({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    noContextFiles: true,
    noExtensions: true,
    extensionFactories: [goalExtension],
  });
  await loader.reload();

  const model = {
    provider: "sdk-smoke",
    id: "mini",
    name: "SDK Smoke",
    api: "sdk-smoke-api",
    baseUrl: "http://localhost",
    reasoning: false,
    input: ["text" as const],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 1_000,
    maxTokens: 100,
  };
  const { session } = await createAgentSession({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    model,
    modelRuntime,
    noTools: "builtin",
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(process.cwd()),
    settingsManager: SettingsManager.inMemory(),
  });

  try {
    const runner = session.extensionRunner;
    assert.equal(runner.getToolDefinition("get_goal")?.executionMode, undefined);
    for (const toolName of ["create_goal", "update_goal"]) {
      assert.equal(runner.getToolDefinition(toolName)?.executionMode, "sequential");
    }
    const createGoal = runner.getToolDefinition("create_goal");
    assert.ok(createGoal);
    const result = await createGoal.execute(
      "tool-call",
      { objective: "ship it" },
      undefined,
      undefined,
      runner.createToolContext("tool-call", undefined),
    );
    const goalId = goalIdFromToolResult(result);

    await runner.emit({
      type: "session_compact",
      compactionEntry: {
        type: "compaction",
        id: "compaction-entry",
        parentId: null,
        timestamp: new Date().toISOString(),
        summary: "compact summary",
        firstKeptEntryId: "entry-1",
        tokensBefore: 100,
      },
      fromExtension: false,
      reason: "manual",
      willRetry: true,
    });
    await new Promise((resolve) => setTimeout(resolve, CONTINUATION_RETRY_MS + 25));

    const continuationMessages = session.sessionManager.getEntries().filter((entry) => {
      return (
        entry.type === "custom_message" &&
        entry.customType === CUSTOM_ENTRY_TYPE &&
        "details" in entry &&
        (entry.details as { kind?: unknown } | undefined)?.kind === "continuation"
      );
    });
    assert.equal(continuationMessages.length, 1);
    const continuationMessage = continuationMessages[0];
    assert.ok(continuationMessage && "details" in continuationMessage);
    assert.deepEqual(continuationMessage.details, { kind: "continuation", goalId });
  } finally {
    session.dispose();
  }
});

const SDK_EDIT_TIMEOUT_MS = 5_000;

async function withinSdkEditTest<T>(operation: Promise<T>, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), SDK_EDIT_TIMEOUT_MS);
  });
  try {
    return await Promise.race([operation, timeout]);
  } finally {
    clearTimeout(timer!);
  }
}

async function createSdkEditSession(t: TestContext, edit: (prefill: string | undefined) => string | undefined) {
  const root = mkdtempSync(join(tmpdir(), "goal-edit-sdk-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({
    allowModelNetwork: false,
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
  });
  const loader = new DefaultResourceLoader({
    cwd: root,
    agentDir: root,
    settingsManager,
    noContextFiles: true,
    noExtensions: true,
    extensionFactories: [goalExtension],
  });
  await loader.reload();
  modelRuntime.registerProvider("sdk-smoke", { apiKey: "test" });
  const { session } = await createAgentSession({
    cwd: root,
    agentDir: root,
    model: {
      provider: "sdk-smoke", id: "edit", name: "SDK Edit Smoke",
      api: "openai-completions", baseUrl: "http://localhost", reasoning: false,
      input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 1_000_000, maxTokens: 1_000,
    },
    modelRuntime,
    noTools: "builtin",
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(root),
    settingsManager,
  });
  t.after(() => session.dispose());
  const runner = session.extensionRunner;
  runner.setUIContext({
    ...runner.createCommandContext().ui,
    confirm: async () => true,
    editor: async (_title, prefill) => edit(prefill),
  }, "tui");
  const createGoal = runner.getToolDefinition("create_goal");
  assert.ok(createGoal);
  await createGoal.execute("create", { objective: "original objective", token_budget: 500_000 },
    undefined, undefined, runner.createToolContext("create", undefined));
  const command = runner.getCommand("goal");
  assert.ok(command);
  const runCommand = (args: string) => withinSdkEditTest(Promise.resolve(command.handler(args, runner.createCommandContext())), `/goal ${args}`);
  await runCommand("pause");
  return {
    session,
    runCommand,
    goal: () => reconstructGoal(session.sessionManager.getBranch()).goal,
  };
}

function heldSdkEditResponse(model: Parameters<StreamFunction>[0], signal: AbortSignal | undefined) {
  assert.ok(signal, "native provider requests must expose their abort signal");
  const stream = createAssistantMessageEventStream();
  let finished: Promise<void> | undefined;
  const finish = () => finished ??= (async () => {
    for await (const event of assistantResponse(model, 7, "Inspected")) stream.push(event);
    stream.end();
  })();
  return { stream, signal, finish };
}

function sdkEditText(messages: Parameters<StreamFunction>[1]["messages"]): string[] {
  return messages.flatMap((message) => typeof message.content === "string" ? [message.content] :
    message.content.map((part) => "text" in part ? part.text : ""));
}

test("SDK objective edit while idle preserves status and reaches the next explicit request", { timeout: 10_000 }, async (t) => {
  const harness = await createSdkEditSession(t, (prefill) => {
    assert.equal(prefill, "original objective");
    return "refined idle objective";
  });
  const { session } = harness;
  try {
    const before = harness.goal();
    assert.ok(before);
    const requests: string[] = [];
    session.agent.streamFunction = (model, context) => {
      requests.push(JSON.stringify(context.messages));
      if (requests.length > 1) {
        void harness.runCommand("clear");
        session.agent.abort();
      }
      return assistantResponse(model, 7, "Inspected");
    };
    await harness.runCommand("edit");
    assert.equal(requests.length, 0, "idle edits must not start a turn");
    const edited = harness.goal();
    assert.deepEqual(edited, { ...before, objective: "refined idle objective", updatedAt: edited?.updatedAt });
    await withinSdkEditTest(session.prompt("Inspect without resuming"), "inspection after idle edit");
    await withinSdkEditTest(session.waitForIdle(), "settlement after idle edit");
    assert.equal(requests.length, 1);
    assert.match(requests[0]!, /refined idle objective/);
    assert.equal(harness.goal()?.status, "paused");
  } finally {
    session.dispose();
  }
});

test("SDK objective edit during a request does not abort it or queue another request", { timeout: 10_000 }, async (t) => {
  const objective = "refined streaming objective";
  const harness = await createSdkEditSession(t, () => objective);
  const { session } = harness;
  const started = Promise.withResolvers<ReturnType<typeof heldSdkEditResponse>>();
  let held: ReturnType<typeof heldSdkEditResponse> | undefined;
  const requests: string[] = [];
  let phase: "hold" | "inspect-revision" = "hold";
  session.agent.streamFunction = (model, context, options) => {
    requests.push(JSON.stringify(context.messages));
    if (phase === "hold" && !held) {
      held = heldSdkEditResponse(model, options?.signal);
      started.resolve(held);
      return held.stream;
    }
    if (phase === "hold" || requests.length > 2) {
      void harness.runCommand("clear");
      session.agent.abort();
    }
    return assistantResponse(model, 7, "Inspected");
  };
  try {
    const before = harness.goal();
    assert.ok(before);
    const prompt = session.prompt("Inspect without resuming");
    const request = await withinSdkEditTest(Promise.race([
      started.promise,
      prompt.then(() => { throw new Error("Inspection ended before the provider request started"); }),
    ]), "held provider request");
    assert.equal(request.signal.aborted, false);
    await harness.runCommand("edit");
    assert.equal(request.signal.aborted, false, "editing must not abort the in-flight request");
    assert.equal(requests.length, 1);
    await request.finish();
    await withinSdkEditTest(prompt, "held request completion");
    await withinSdkEditTest(session.waitForIdle(), "settlement after streaming edit");
    assert.equal(request.signal.aborted, false, "editing must not defer an abort until settlement");
    assert.equal(requests.length, 1, "editing must not queue another request");
    phase = "inspect-revision";
    await withinSdkEditTest(session.prompt("Inspect the revision without resuming"), "inspection after streaming edit");
    assert.equal(requests.length, 2);
    assert.doesNotMatch(requests[0]!, /refined streaming objective/);
    assert.match(requests.at(-1)!, /refined streaming objective/);
    const edited = harness.goal();
    assert.deepEqual(edited, { ...before, objective, updatedAt: edited?.updatedAt });
  } finally {
    // Release the fake provider even when an assertion fails before normal completion.
    await held?.finish();
    session.dispose();
  }
});

for (const [label, text, expectedObjective] of [
  ["saved", "refined queued objective", "refined queued objective"],
  ["canceled", undefined, "queued original objective"],
  ["unchanged", "  queued original objective  ", "queued original objective"],
  ["empty", " \n ", "queued original objective"],
  ["too long", "😀".repeat(8001), "queued original objective"],
] as const) {
  test(`SDK objective edit ${label} preserves and delivers the pending command start`, { timeout: 10_000 }, async (t) => {
    const harness = await createSdkEditSession(t, (prefill) => {
      assert.equal(prefill, "queued original objective");
      return text;
    });
    const { session } = harness;
    const started = Promise.withResolvers<ReturnType<typeof heldSdkEditResponse>>();
    let held: ReturnType<typeof heldSdkEditResponse> | undefined;
    let phase: "hold-inspection" | "start-goal" | "report-completion" = "hold-inspection";
    let requests = 0;
    const starts: string[] = [];
    session.agent.streamFunction = (model, context, options) => {
      requests += 1;
      if (requests > 3) {
        // Clear disposable goal work synchronously: this fake provider does not
        // honor aborts, and immediate continuations can starve timeout timers.
        void harness.runCommand("clear");
        session.agent.abort();
        return assistantResponse(model, 7, "Unexpected extra request");
      }
      if (phase === "hold-inspection" && !held) {
        held = heldSdkEditResponse(model, options?.signal);
        started.resolve(held);
        return held.stream;
      }
      if (phase === "start-goal") {
        const start = sdkEditText(context.messages).find((part) =>
          part.startsWith("<pi_goal_continuation") && part.includes("<untrusted_objective>"));
        if (start) starts.push(start);
        phase = "report-completion";
        return assistantResponse(model, 7, [{ type: "toolCall", id: "finish-edited", name: "update_goal",
          arguments: { status: "complete" } }]);
      }
      if (phase === "hold-inspection") {
        void harness.runCommand("clear");
        session.agent.abort();
      }
      return assistantResponse(model, 7, "Done");
    };
    try {
      const prompt = session.prompt("Inspect without resuming");
      const request = await withinSdkEditTest(Promise.race([
        started.promise,
        prompt.then(() => { throw new Error("Inspection ended before the provider request started"); }),
      ]), "provider request before queuing goal");
      await harness.runCommand("queued original objective");
      const queued = harness.goal();
      assert.ok(queued);
      await harness.runCommand("edit");
      assert.equal(request.signal.aborted, false, "editing must not abort the request ahead of the queued start");
      assert.equal(requests, 1, "editing must not start work before the held request finishes");
      const edited = harness.goal();
      assert.deepEqual(edited, { ...queued, objective: expectedObjective, updatedAt: edited?.updatedAt });
      phase = "start-goal";
      await request.finish();
      await withinSdkEditTest(prompt, "completion of request ahead of queued start");
      await withinSdkEditTest(session.waitForIdle(), "queued goal completion");
      assert.equal(requests, 3, "only the held inspection, queued start, and completion report may run");
      assert.equal(starts.length, 1, "the original pending start must reach the provider exactly once");
      assert.ok(starts[0]?.includes(`<untrusted_objective>\n${expectedObjective}\n</untrusted_objective>`));
      assert.equal(harness.goal()?.goalId, queued.goalId);
      assert.equal(harness.goal()?.status, "complete");
    } finally {
      await held?.finish();
      session.dispose();
    }
  });
}
