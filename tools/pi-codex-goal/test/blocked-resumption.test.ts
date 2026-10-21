import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { createThreadGoal, updateGoalFromTool } from "../src/state.ts";
import { assistantMessage, createRuntimeHarness } from "./support/runtime-harness.ts";

const resolution = "The user supplied report.md, resolving the recorded filename dependency.";

// Each invalid row differs from valid blocked activation in one admission condition.
test("tool activation accepts only the identified blocked goal with a resolution reason and remaining budget", () => {
  const blocked = { ...createThreadGoal("finish", 500_000), status: "blocked" as const, blockedReason: "Need filename" };
  const valid = updateGoalFromTool(blocked, "active", resolution, blocked.goalId);
  assert.equal(valid.ok, true);
  assert.equal(valid.goal?.status, "active");
  assert.equal(valid.goal?.blockedReason, undefined);
  assert.deepEqual(valid.goal?.usage, blocked.usage);
  const cases = [
    { goal: null, reason: resolution, id: blocked.goalId },
    ...(["active", "paused", "budgetLimited", "complete"] as const).map(status => ({ goal: { ...blocked, status }, reason: resolution, id: blocked.goalId })),
    { goal: blocked, reason: resolution, id: undefined },
    { goal: blocked, reason: resolution, id: "replaced-goal" },
    ...[undefined, "", "   "].map(reason => ({ goal: blocked, reason, id: blocked.goalId })),
    { goal: { ...blocked, usage: { tokensUsed: 500_000, activeSeconds: 1 } }, reason: resolution, id: blocked.goalId },
  ];
  for (const { goal, reason, id } of cases) {
    const before = structuredClone(goal);
    const result = updateGoalFromTool(goal, "active", reason, id);
    assert.equal(result.ok, false, JSON.stringify({ goal, reason, id }));
    assert.deepEqual(result.goal, before);
    assert.deepEqual(goal, before, "rejection does not mutate the input");
  }
});

async function blockedHarness() {
  const h = createRuntimeHarness();
  await h.runTool("create_goal", { objective: "Finish the report" });
  await h.emit("turn_start", { type: "turn_start", turnIndex: 0, timestamp: 1 });
  await h.runTool("update_goal", { status: "blocked", reason: "Need filename" });
  h.sentMessages.length = 0;
  return h;
}

test("ordinary input does not activate a blocked goal; explicit activation starts elapsed time but not response ownership", async () => {
  mock.timers.enable({ apis: ["Date"], now: 10_000 });
  try {
    const h = await blockedHarness();
    const saved = h.snapshot().goal!;
    await h.emit("input", { type: "input", text: "The filename is report.md", source: "interactive" });
    assert.deepEqual(h.snapshot().goal, saved);
    await h.emit("turn_start", { type: "turn_start", turnIndex: 1, timestamp: 1 });
    mock.timers.tick(30_000);
    await h.runTool("update_goal", { status: "active", goal_id: saved.goalId, reason: resolution });
    assert.equal(h.snapshot().goal?.status, "active");
    assert.equal(h.sentMessages.length, 0, "activation must not queue a command-resume turn");
    mock.timers.tick(2_000);
    await h.emit("turn_end", { type: "turn_end", turnIndex: 1, message: assistantMessage("toolUse", { input: 100, output: 20 }), toolResults: [] });
    assert.equal(h.snapshot().goal?.usage.tokensUsed, 0, "the response that began blocked is not goal work");
    assert.equal(h.snapshot().goal?.usage.activeSeconds, 2, "only time after activation is active time");
    await h.emit("turn_start", { type: "turn_start", turnIndex: 2, timestamp: 1 });
    const message = { ...assistantMessage("toolUse", { input: 10, output: 2 }), content: [{ type: "toolCall" as const, id: "complete", name: "update_goal", arguments: { status: "complete" } }] };
    h.appendMessage(message);
    await h.runTool("update_goal", { status: "complete" }, "complete");
    await h.emit("turn_end", { type: "turn_end", turnIndex: 2, message, toolResults: [] });
    assert.equal(h.snapshot().goal?.usage.tokensUsed, 12, "the later active response is counted exactly once");
  } finally { mock.timers.reset(); }
});

test("human pause, canceled activation, and goal-bound interruption prevent tool reactivation", async () => {
  for (const stop of ["pause", "signal", "turn_abort", "agent_abort"] as const) {
    const h = await blockedHarness();
    const saved = h.snapshot().goal!;
    await h.emit("turn_start", { type: "turn_start", turnIndex: 1, timestamp: 1 });
    const params = { status: "active", goal_id: saved.goalId, reason: resolution };
    if (stop === "signal") {
      await assert.rejects(() => h.runTool("update_goal", params, "unblock", AbortSignal.abort()), /canceled/);
      assert.deepEqual(h.snapshot().goal, saved);
      // A non-canceled sibling remains eligible until the native abort boundary pauses it.
      await h.runTool("update_goal", params);
      assert.equal(h.snapshot().goal?.status, "active");
      continue;
    }
    if (stop === "pause") await h.runCommand("pause");
    else {
      const message = assistantMessage("aborted", { input: 10, output: 2 });
      if (stop === "turn_abort") await h.emit("turn_end", { type: "turn_end", turnIndex: 1, message, toolResults: [] });
      else await h.emit("agent_end", { type: "agent_end", messages: [message] });
    }
    const paused = h.snapshot().goal!;
    assert.equal(paused.status, "paused", stop);
    assert.equal(paused.pausedReason, saved.blockedReason);
    assert.equal(paused.blockedReason, undefined);
    assert.deepEqual(paused.usage, saved.usage);
    await assert.rejects(() => h.runTool("update_goal", params), /Only a blocked goal/);
    await assert.rejects(() => h.runTool("update_goal", { status: "blocked", reason: "still waiting" }), /already-paused/);
    assert.deepEqual(h.snapshot().goal, paused);
  }
});

test("a replaced goal rejects the older activation and is not paused by its abort", async () => {
  const h = await blockedHarness();
  const oldId = h.snapshot().goal!.goalId;
  await h.emit("turn_start", { type: "turn_start", turnIndex: 1, timestamp: 1 });
  await h.runCommand("Replacement objective");
  const replacement = h.snapshot().goal!;
  assert.notEqual(replacement.goalId, oldId);
  await assert.rejects(() => h.runTool("update_goal", { status: "active", goal_id: oldId, reason: resolution }), /Goal changed/);
  const message = assistantMessage("aborted", { input: 10, output: 2 });
  await h.emit("turn_end", { type: "turn_end", turnIndex: 1, message, toolResults: [] });
  await h.emit("agent_end", { type: "agent_end", messages: [message] });
  assert.deepEqual(h.snapshot().goal, replacement);
});
