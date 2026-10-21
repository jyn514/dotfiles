import assert from "node:assert/strict";
import { test } from "node:test";
import { formatFooterStatus, formatGoalSummary, toToolGoal } from "../src/format.ts";
import { createThreadGoal, goalsEquivalent, isThreadGoal, updateGoalFromTool, updateGoalStatus } from "../src/state.ts";
import { planGoalTransition } from "../src/goal-transition.ts";
import { createRuntimeHarness } from "./support/runtime-harness.ts";

// A model may explain a pause, but may not turn it into a resumable dependency block.
test("pause annotations require an already-paused goal and a non-empty reason", () => {
  const active = createThreadGoal("finish");
  for (const status of ["active", "blocked", "budgetLimited", "complete"] as const) {
    const goal = { ...active, status };
    const result = updateGoalFromTool(goal, "paused", "Need the filename");
    assert.equal(result.ok, false, status);
    assert.deepEqual(result.goal, goal);
  }
  assert.equal(updateGoalFromTool(null, "paused", "Need the filename").ok, false);
  const paused = { ...active, status: "paused" as const, updatedAt: 1 };
  for (const reason of [undefined, "", "   "]) {
    assert.equal(updateGoalFromTool(paused, "paused", reason).ok, false);
  }
  const result = updateGoalFromTool(paused, "paused", "  Need the filename  ");
  assert.equal(result.ok, true);
  assert.deepEqual(result.goal, { ...paused, pausedReason: "Need the filename", updatedAt: result.goal?.updatedAt });
  assert.equal(goalsEquivalent(paused, result.goal!), false);
  const repeated = updateGoalFromTool(result.goal, "paused", "Need the filename");
  assert.deepEqual(repeated.goal, result.goal);
  assert.match(updateGoalFromTool(paused, "blocked", "Need filename").message, /already-paused/);
  assert.equal(updateGoalFromTool(paused, "blocked", "Need filename").ok, false);
});

test("pause reasons survive edit and reload, display outside the footer, and clear on resume or completion", async () => {
  const h = createRuntimeHarness();
  await h.runCommand("finish");
  await h.runCommand("pause");
  const original = h.snapshot().goal!;
  await h.runTool("update_goal", { status: "paused", reason: " Need the filename " });
  const annotated = h.snapshot().goal!;
  assert.equal(annotated.status, "paused");
  assert.deepEqual(annotated.usage, original.usage);
  assert.equal(annotated.pausedReason, "Need the filename");
  const count = h.entries.length;
  await h.runTool("update_goal", { status: "paused", reason: "Need the filename" });
  assert.equal(h.entries.length, count);
  assert.deepEqual(h.snapshot().goal, annotated);
  await h.reloadSession("reload");
  assert.deepEqual(h.snapshot().goal, annotated);
  const edited = planGoalTransition(annotated, { kind: "edit_objective", objective: "finish the new task" }).nextGoal!;
  assert.equal(edited.pausedReason, annotated.pausedReason);
  assert.match(formatGoalSummary(edited), /Paused because: Need the filename/);
  assert.doesNotMatch(formatFooterStatus(edited) ?? "", /Need the filename/);
  assert.equal(toToolGoal(edited).pausedReason, "Need the filename");
  assert.equal(isThreadGoal(edited), true);
  assert.equal(isThreadGoal({ ...edited, pausedReason: 4 }), false);
  assert.equal(isThreadGoal(original), true, "old snapshots without a pause reason still load");
  for (const status of ["active", "complete"] as const) {
    assert.equal(updateGoalStatus(annotated, status).goal?.pausedReason, undefined);
  }
  assert.equal(planGoalTransition(annotated, { kind: "resume_active" }).nextGoal?.pausedReason, undefined);
  await h.runCommand("resume");
  assert.equal(h.snapshot().goal?.status, "active");
  assert.equal(h.snapshot().goal?.pausedReason, undefined);
});
