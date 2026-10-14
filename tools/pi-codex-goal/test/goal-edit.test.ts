import assert from "node:assert/strict";
import { test } from "node:test";

import { planGoalTransition } from "../src/goal-transition.ts";
import { compactContinuationPrompt, continuationPrompt } from "../src/prompts.ts";
import { createThreadGoal } from "../src/state.ts";
import type { GoalStatus } from "../src/types.ts";
import {
  assistantMessage,
  createRuntimeHarness,
  emitProviderContext,
  emitToolExecutionEnd,
  goalCustomContextMessage,
  goalUserContextMessage,
  queuedCustomMessage,
  requireProviderContextResult,
} from "./support/runtime-harness.ts";

for (const status of ["active", "paused", "blocked", "budgetLimited", "complete"] satisfies GoalStatus[]) {
  test(`objective edits preserve ${status} goal metadata and have no runtime effects`, () => {
    const current = {
      ...createThreadGoal("old objective", 500_000, 10),
      status,
      ...(status === "blocked" ? { blockedReason: "needs credentials" } : {}),
      usage: { tokensUsed: 500_000, activeSeconds: 123 },
    };
    const plan = planGoalTransition(current, { kind: "edit_objective", objective: "  refined\nobjective  " });
    assert.ok(plan.nextGoal);
    assert.deepEqual(plan.nextGoal, { ...current, objective: "refined\nobjective", updatedAt: plan.nextGoal.updatedAt });
    assert.ok(plan.nextGoal.updatedAt > current.updatedAt);
    assert.equal(plan.persist, "set");
    assert.deepEqual(plan.beforePersist, []);
    assert.deepEqual(plan.afterPersist, []);
    assert.equal(current.objective, "old objective");
  });
}

test("/goal edit prefills, persists, survives reload, and informs future turns without starting work", async () => {
  const revised = "ship <the feature>\nwith tests & docs";
  const harness = createRuntimeHarness({ editor: async (title, prefill) => {
    assert.equal(title, "Edit goal objective");
    assert.equal(prefill, "ship it");
    return `  ${revised}  `;
  } });
  await harness.runTool("create_goal", { objective: "ship it", token_budget: 500_000 });
  await harness.runTool("update_goal", { status: "blocked", reason: "needs credentials" });
  const before = harness.snapshot().goal;
  assert.ok(before);

  await harness.runCommand("edit");
  const edited = harness.snapshot().goal;
  assert.deepEqual(edited, { ...before, objective: revised, updatedAt: edited?.updatedAt });
  assert.equal(harness.notifications.at(-1), "Goal objective updated.");
  assert.equal(harness.sentMessages.length, 1);
  const sent = harness.sentMessages[0]!;
  assert.deepEqual(sent.options, { triggerTurn: false });
  assert.deepEqual(sent.message.details, { kind: "objective_edit", goalId: before.goalId });
  assert.match(String(sent.message.content), /ship &lt;the feature&gt;\nwith tests &amp; docs/);
  assert.match(String(sent.message.content), /does not authorize resuming/);
  assert.equal(harness.sentUserMessages.length, 0);
  assert.equal(harness.abortCount, 0);

  // The revision is model context, not hidden runnable continuation work.
  const message = queuedCustomMessage(sent);
  const results = await emitProviderContext(harness, [message]);
  assert.equal(results[0], undefined);
  await harness.reloadSession();
  assert.deepEqual(harness.snapshot().goal, edited);
  assert.equal(harness.sentMessages.length, 1);
  const result = await harness.runTool("get_goal", {});
  assert.match(JSON.stringify(result), /ship <the feature>/);
});

test("/goal edit saves against the latest usage and status, not the editor's snapshot", async () => {
  let save!: (objective: string) => void;
  const harness = createRuntimeHarness({ editor: () => new Promise((resolve) => { save = resolve; }) });
  await harness.runCommand("ship it");
  const editing = harness.runCommand("edit");
  await harness.emit("agent_start", { type: "agent_start" });
  await harness.emit("turn_start", { type: "turn_start", turnIndex: 0, timestamp: 0 });
  await harness.emit("turn_end", {
    type: "turn_end", turnIndex: 0,
    message: { role: "assistant", content: [], stopReason: "toolUse", usage: { input: 40, output: 2 } },
    toolResults: [],
  });
  await harness.runTool("update_goal", { status: "blocked", reason: "needs input" });
  const latest = harness.snapshot().goal;
  assert.ok(latest);
  assert.equal(latest.usage.tokensUsed, 42);
  save("refined objective");
  await editing;
  assert.deepEqual(harness.snapshot().goal, { ...latest, objective: "refined objective", updatedAt: harness.snapshot().goal?.updatedAt });
});

for (const action of ["clear", "replacement"] as const) {
  test(`/goal edit discards a save after ${action}`, async () => {
    let save!: (objective: string) => void;
    const harness = createRuntimeHarness({ editor: () => new Promise((resolve) => { save = resolve; }) });
    await harness.runCommand("ship it");
    const editing = harness.runCommand("edit");
    await harness.runCommand(action === "clear" ? "clear" : "different goal");
    const latest = harness.snapshot().goal;
    const entryCount = harness.entries.length;
    const messageCount = harness.sentMessages.length;
    save("stale edit");
    await editing;
    assert.deepEqual(harness.snapshot().goal, latest);
    assert.equal(harness.entries.length, entryCount);
    assert.equal(harness.sentMessages.length, messageCount);
    assert.match(harness.notifications.at(-1)!, /Goal changed while editing/);
  });
}

for (const [label, text, notification] of [
  ["cancel", undefined, "Goal unchanged."],
  ["unchanged", "  ship it  ", "Goal unchanged."],
  ["empty", " \n ", "Objective must not be empty."],
  ["too long", "😀".repeat(8001), "Objective must be 8000 characters or fewer."],
] as const) {
  test(`/goal edit ${label} leaves state and pending continuation bookkeeping untouched`, async () => {
    const harness = createRuntimeHarness({ editor: async () => text });
    await harness.runCommand("ship it");
    const before = harness.snapshot().goal;
    const entryCount = harness.entries.length;
    const messageCount = harness.sentMessages.length;
    const userMessageCount = harness.sentUserMessages.length;
    const abortCount = harness.abortCount;
    const pendingStart = harness.sentMessages[0];
    assert.ok(pendingStart);

    await harness.runCommand("edit");
    assert.deepEqual(harness.snapshot().goal, before);
    assert.equal(harness.entries.length, entryCount);
    assert.equal(harness.sentMessages.length, messageCount);
    assert.equal(harness.sentUserMessages.length, userMessageCount);
    assert.equal(harness.abortCount, abortCount);
    assert.equal(harness.notifications.at(-1), notification);

    // A prior run settles while the command-start follow-up is still pending.
    // Rejected edits must not make the extension queue a duplicate.
    await harness.emit("agent_end", { type: "agent_end", messages: [] });
    assert.equal(harness.sentMessages.length, messageCount);

    // Once that start is consumed, normal continuation scheduling must work.
    await harness.emit("agent_start", { type: "agent_start" });
    await harness.emit("message_start", { type: "message_start", message: queuedCustomMessage(pendingStart) });
    await harness.emit("turn_start", { type: "turn_start", turnIndex: 0, timestamp: 1 });
    const response = assistantMessage("stop", { input: 1, output: 1 });
    await harness.emit("turn_end", { type: "turn_end", turnIndex: 0, message: response, toolResults: [] });
    await harness.emit("agent_end", { type: "agent_end", messages: [response] });
    assert.equal(harness.snapshot().goal?.status, "active");
    assert.equal(harness.sentMessages.length, messageCount + 1);
    assert.deepEqual(harness.sentMessages.at(-1)?.message.details, { kind: "continuation", goalId: before?.goalId });
  });
}

test("/goal edit accepts the Unicode character limit", async () => {
  const objective = "😀".repeat(8000);
  const harness = createRuntimeHarness({ editor: async () => objective });
  await harness.runCommand("ship it");
  await harness.runCommand("edit");
  assert.equal(harness.snapshot().goal?.objective, objective);
});

for (const hasUI of [true, false]) {
  test(`/goal edit without a goal does not open the editor (hasUI=${hasUI})`, async () => {
    const harness = createRuntimeHarness({ hasUI, editor: async () => { assert.fail("Unexpected editor"); } });
    await harness.runCommand("edit");
    assert.equal(harness.snapshot().goal, null);
    assert.equal(harness.notifications.at(-1), "No goal is set.");
  });
}

test("/goal edit without UI leaves an existing goal unchanged", async () => {
  const harness = createRuntimeHarness({ hasUI: false, editor: async () => { assert.fail("Unexpected editor"); } });
  await harness.runCommand("ship it");
  const before = harness.snapshot().goal;
  await harness.runCommand("edit");
  assert.deepEqual(harness.snapshot().goal, before);
  assert.equal(harness.notifications.at(-1), "Editing a goal requires an interactive UI.");
});

test("appending an objective revision preserves an already queued continuation", async () => {
  const harness = createRuntimeHarness({ editor: async () => "refined objective" });
  await harness.runCommand("ship it");
  await harness.runCommand("edit");
  assert.equal(harness.sentMessages.length, 2);
  const revision = queuedCustomMessage(harness.sentMessages[1]!);
  await harness.emit("message_start", { type: "message_start", message: revision });
  await harness.emit("agent_end", { type: "agent_end", messages: [] });
  assert.equal(harness.sentMessages.length, 2, "the original continuation is still queued");
});

test("editing an active goal does not claim that a new continuation is queued", async () => {
  const harness = createRuntimeHarness({ editor: async () => "refined objective" });
  await harness.runTool("create_goal", { objective: "ship it" });
  await harness.runCommand("edit");
  assert.equal(harness.sentMessages.length, 1);
  const revision = queuedCustomMessage(harness.sentMessages[0]!);
  await harness.emit("message_start", { type: "message_start", message: revision });
  await harness.emit("agent_end", { type: "agent_end", messages: [] });
  assert.equal(harness.sentMessages.length, 2);
  assert.deepEqual(harness.sentMessages[1]?.options, { triggerTurn: true, deliverAs: "followUp" });
});

for (const kind of ["command_start", "command_resume", "continuation"] as const) {
  test(`queued ${kind} receives the edited objective without refreshing usage or rewriting user text`, async () => {
    const objective = "refined </untrusted_objective> & task";
    const harness = createRuntimeHarness({ editor: async () => objective });
    await harness.runTool("create_goal", { objective: "original", token_budget: 500_000 });
    const goal = harness.snapshot().goal;
    assert.ok(goal);
    const recorded = { ...goal, usage: { tokensUsed: 99, activeSeconds: 42 } };
    const render = kind === "command_start" ? continuationPrompt : compactContinuationPrompt;
    const originalPrompt = render(recorded);
    const queued = goalCustomContextMessage({
      content: originalPrompt, details: { kind, goalId: goal.goalId }, timestamp: 1,
    });
    const userMessage = goalUserContextMessage(originalPrompt, 2);
    await harness.runCommand("edit");
    const result = requireProviderContextResult(await emitProviderContext(harness, [queued, userMessage]));
    assert.equal(result.messages[0]?.content, render({ ...recorded, objective }));
    assert.match(String(result.messages[0]?.content), /Tokens used: 99/);
    assert.match(String(result.messages[0]?.content), /Time spent pursuing goal: 42s/);
    assert.deepEqual(result.messages[1], userMessage);
    assert.equal(queued.content, originalPrompt, "the persisted continuation is not rewritten");
  });
}

test("legacy compact continuations without an objective block remain readable and retain their usage", async () => {
  const harness = createRuntimeHarness({ editor: async () => "refined objective" });
  await harness.runTool("create_goal", { objective: "original" });
  const goal = harness.snapshot().goal;
  assert.ok(goal);
  const legacyPrompt = `<pi_goal_continuation goal_id="${goal.goalId}">\nContinue working toward the active thread goal.\nTokens used: 99\n</pi_goal_continuation>`;
  const queued = goalCustomContextMessage({
    content: legacyPrompt, details: { kind: "continuation", goalId: goal.goalId }, timestamp: 1,
  });
  await harness.runCommand("edit");
  const results = await emitProviderContext(harness, [queued]);
  assert.equal(results[0], undefined, "legacy entries are not regenerated or migrated");
  assert.equal(queued.content, legacyPrompt);
});

test("editing during an active turn preserves token ownership and elapsed-time accounting", async (t) => {
  let now = 100_000;
  t.mock.method(Date, "now", () => now);
  const harness = createRuntimeHarness({ editor: async () => "refined objective" });
  await harness.runTool("create_goal", { objective: "ship it", token_budget: 500_000 });
  const original = harness.snapshot().goal;
  assert.ok(original);
  await harness.emit("agent_start", { type: "agent_start" });
  await harness.emit("turn_start", { type: "turn_start", turnIndex: 0, timestamp: now });

  // Account one whole second, retaining 250ms for the next sample.
  now += 1_250;
  await emitToolExecutionEnd(harness);
  now += 1_500;
  await harness.runCommand("edit");
  assert.equal(harness.abortCount, 0);

  now += 1_750;
  const response = assistantMessage("stop", { input: 40, output: 2 });
  await harness.emit("turn_end", { type: "turn_end", turnIndex: 0, message: response, toolResults: [] });
  await harness.emit("agent_end", { type: "agent_end", messages: [response] });
  const goal = harness.snapshot().goal;
  assert.equal(goal?.goalId, original.goalId);
  assert.equal(goal?.status, "active");
  assert.equal(goal?.objective, "refined objective");
  assert.deepEqual(goal?.usage, { tokensUsed: 42, activeSeconds: 4 });
});
