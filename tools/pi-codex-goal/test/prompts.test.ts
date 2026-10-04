import assert from "node:assert/strict";
import test from "node:test";

import {
  TOOL_PROMPT_GUIDELINES,
  budgetLimitPrompt,
  compactContinuationPrompt,
  continuationGoalIdFromPrompt,
  continuationPrompt,
  supersededContinuationMessage,
} from "../src/prompts.ts";
import { createThreadGoal } from "../src/state.ts";

// Public prompt text is the contract: lost guards and repeated tool-name
// alternatives both matter, regardless of how the strings are assembled.
const created = createThreadGoal("ship it", 10);
const standing = TOOL_PROMPT_GUIDELINES.join("\n");
const full = continuationPrompt(created);
const compact = compactContinuationPrompt(created);
const budget = budgetLimitPrompt(created);

for (const [kind, prompt] of Object.entries({ standing, full, compact, budget })) {
  test(`${kind} prompt explains exposed tool names once without inline alternatives`, () => {
    assert.match(prompt, /available tool list/);
    assert.match(prompt, /display, history, or transcript labels/);
    assert.deepEqual(prompt.match(/\bpi__\w+_goal\b/g), ["pi__update_goal"]);
    assert.doesNotMatch(prompt, /or the exposed namespaced equivalent/);
  });
}

for (const [kind, prompt] of Object.entries({ standing, full, compact })) {
  test(`${kind} prompt requires concrete evidence for every requirement and no remaining work`, () => {
    assert.match(prompt, /update_goal with status "complete" only when every explicit requirement has concrete verification evidence and no required work remains/);
  });
}

for (const [kind, prompt] of Object.entries({ standing, full })) {
  test(`${kind} prompt blocks only on dependencies and requires explicit resume`, () => {
    assert.match(prompt, /missing user input or external work prevents meaningful progress/);
    assert.match(prompt, /status "blocked" and a dependency reason/);
    assert.match(prompt, /explain what is needed to the user/);
    assert.match(prompt, /Do not block while useful work remains/);
    assert.match(prompt, /Only explicit \/goal resume reactivates a blocked goal; ordinary input does not/);
    assert.match(prompt, /Never complete a blocked goal/);
  });
}

for (const [kind, prompt] of Object.entries({ standing, full, compact })) {
  test(`${kind} prompt routes tracked implementation through verified completion to available skill guidance`, () => {
    assert.match(prompt, /For a tracked goal requesting implementation through verified completion, read the autonomous-implementation skill file at its advertised path, if available, when starting or resuming work/);
    assert.match(prompt, /stuck or repeatedly making no progress on that implementation goal/);
    assert.match(prompt, /re-read its recovery guidance before choosing the next action/);
    assert.match(prompt, /Do not activate this skill for plan-only, review, research, or writing goals/);
    assert.doesNotMatch(prompt, /\/skill:autonomous-implementation/);
  });
}

for (const [kind, prompt] of Object.entries({ full, compact })) {
  test(`${kind} continuation leaves work-selection procedure to the skill`, () => {
    assert.doesNotMatch(prompt, /Avoid repeating work that is already done/);
    assert.doesNotMatch(prompt, /Choose the next concrete action toward the objective/);
  });
}

test("budget-limit prompt does not request skill recovery after work has stopped", () => {
  assert.doesNotMatch(budget, /autonomous-implementation/);
});

test("standing guidance preserves explicit goal creation authorization", () => {
  assert.match(standing, /only when the user explicitly asks you to start tracking a concrete goal/);
  assert.match(standing, /do not infer goals from ordinary tasks/);
  assert.match(standing, /do not create a second goal while a non-complete goal already exists/);
  assert.match(standing, /When a goal is active, keep working through clear low-risk next steps instead of stopping at a plan/);
});

test("full continuation reports usage only after successful completion", () => {
  assert.match(full, /After the completion tool succeeds, report final elapsed time/);
  assert.match(full, /if the goal has a token budget, final consumed token budget/);
});

test("compact continuation keeps marker, budget and local guards without the full objective", () => {
  assert.equal(continuationGoalIdFromPrompt(compact), created.goalId);
  assert.match(compact, /<pi_goal_continuation goal_id="/);
  assert.doesNotMatch(compact, /<untrusted_objective>/);
  assert.match(compact, /get_goal/);
  assert.match(compact, /Tokens used: 0/);
  assert.match(compact, /Tokens remaining: 10/);
  assert.match(compact, /status "complete" only when every explicit requirement has concrete verification evidence/);
  assert.match(compact, /status "blocked"/);
  assert.match(compact, /dependency in reason/);
  assert.match(compact, /explicit \/goal resume/);
  assert.ok(compact.length < full.length);
});

test("superseded continuation bookkeeping does not expose a runnable marker", () => {
  const superseded = supersededContinuationMessage(created.goalId);
  assert.equal(continuationGoalIdFromPrompt(superseded), null);
  assert.match(superseded, /Superseded hidden goal continuation bookkeeping/);
});

test("budget-limit prompt preserves the stop-work instruction and completion exception", () => {
  assert.match(budget, /marked the goal as budgetLimited/);
  assert.doesNotMatch(budget, /budget_limited/);
  assert.match(budget, /do not start new substantive work/);
  assert.match(budget, /Do not call update_goal unless the goal is actually complete/);
});
