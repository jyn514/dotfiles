import assert from "node:assert/strict";
import { test } from "node:test";

import { reconstructGoal, setEntry, createThreadGoal } from "../src/state.ts";
import { CUSTOM_ENTRY_TYPE } from "../src/types.ts";
import { createRuntimeHarness, assistantMessage, sessionCompactEvent } from "./support/runtime-harness.ts";

for (const [label, tokenBudget, tokensUsed, expectedStatus] of [
  ["unlimited", null, 120, "active"],
  ["under budget", 500_000, 120, "active"],
  ["exhausted budget", 500_000, 500_000, "budgetLimited"],
] as const) {
  test(`/goal resume reopens a saved completed goal: ${label}`, async () => {
    const saved = createThreadGoal("Finish the work", tokenBudget);
    saved.status = "complete";
    saved.usage = { tokensUsed, activeSeconds: 42 };
    const h = createRuntimeHarness();
    h.entries.push({
      type: "custom", id: "saved-goal", parentId: null, timestamp: new Date(0).toISOString(),
      customType: CUSTOM_ENTRY_TYPE, data: setEntry(saved, "tool"),
    });
    await h.reloadSession();
    // Recovery and agent requests must leave completion intact.
    await h.emit("session_compact", sessionCompactEvent());
    assert.equal(h.snapshot().goal?.status, "complete");
    assert.equal(h.sentMessages.length, 0);
    await assert.rejects(
      () => h.runTool("update_goal", { status: "active", goal_id: saved.goalId, reason: "More work" }),
      /Only a blocked goal/,
    );

    await h.runCommand("resume");
    const resumed = h.snapshot().goal;
    assert.deepEqual(resumed, { ...saved, status: expectedStatus, updatedAt: resumed?.updatedAt });
    assert.equal(h.sentMessages.length, expectedStatus === "active" ? 1 : 0);
    assert.deepEqual(reconstructGoal(h.entries).goal, resumed);
    if (expectedStatus === "active") {
      assert.deepEqual(h.sentMessages[0]?.options, { triggerTurn: true, deliverAs: "followUp" });
    }
  });
}

test("resuming before the completion response ends does not double-count its tokens", async () => {
  const h = createRuntimeHarness();
  await h.runTool("create_goal", { objective: "Finish the work" });
  await h.emit("turn_start", { type: "turn_start", turnIndex: 0, timestamp: 1 });
  const message = {
    ...assistantMessage("toolUse", { input: 100, output: 20 }),
    content: [{ type: "toolCall" as const, id: "finish", name: "update_goal", arguments: { status: "complete" } }],
  };
  h.appendMessage(message);
  await h.runTool("update_goal", { status: "complete" }, "finish");
  assert.equal(h.snapshot().goal?.usage.tokensUsed, 120);
  await h.runCommand("resume");
  await h.emit("turn_end", { type: "turn_end", turnIndex: 0, message, toolResults: [] });
  assert.equal(h.snapshot().goal?.status, "active");
  assert.equal(h.snapshot().goal?.usage.tokensUsed, 120);
});
