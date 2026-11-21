import { describe, expect, test } from "bun:test";
import { setTimeout as delay } from "node:timers/promises";
import { waitWithSteering } from "./wait.js";
import subagentExtension from "./implementation.js";

function untilAborted(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    if (signal.aborted) reject(signal.reason);
  });
}

describe("wait_agent registration", () => {
  test("only direct interrupted results request follow-up delivery", async () => {
    const tools = new Map<string, any>();
    const handlers = new Map<string, Function>();
    const pi: any = {
      events: { on() {}, emit() {} },
      on(name: string, handler: Function) { handlers.set(name, handler); },
      registerTool(tool: any) { tools.set(tool.name, tool); },
      registerMessageRenderer() {}, registerCommand() {}, registerShortcut() {},
    };
    subagentExtension(pi);
    const wait = tools.get("wait_agent");
    const context = { sessionManager: { getSessionId: () => "wait-test" }, isDirectToolCall: true,
      hasPendingSteeringMessages: () => false, hasPendingMessages: () => true };
    try {
      const direct = await wait.execute("direct", {}, undefined, undefined, context);
      expect(direct.yieldToFollowUps).toBe(true);
      expect(JSON.parse(direct.content[0].text).reason).toBe("follow-up");
      const steering = await wait.execute("steering", {}, undefined, undefined, { ...context, hasPendingSteeringMessages: () => true });
      expect(steering.yieldToFollowUps).toBe(true);
      expect(JSON.parse(steering.content[0].text).reason).toBe("steering");
      const nested = await wait.execute("nested", {}, undefined, undefined, { ...context, isDirectToolCall: false, hasPendingSteeringMessages: () => true });
      expect(nested.yieldToFollowUps).toBeUndefined();
      const completed = await wait.execute("completed", { until: "all" }, undefined, undefined, { ...context, hasPendingMessages: () => false });
      expect(JSON.parse(completed.content[0].text).reason).toBe("completion");
      expect(completed.yieldToFollowUps).toBeUndefined();
      const timeout = await wait.execute("timeout", { timeout_seconds: 0.01 }, undefined, undefined, { ...context, hasPendingMessages: () => false });
      expect(JSON.parse(timeout.content[0].text).reason).toBe("timeout");
      expect(timeout.yieldToFollowUps).toBeUndefined();
      await expect(wait.execute("error", { targets: ["missing"] }, undefined, undefined, { ...context, hasPendingMessages: () => false })).rejects.toThrow("Agent not found");
    } finally {
      await handlers.get("session_shutdown")?.({ reason: "shutdown" }, context);
    }
  });
});

describe("interruptible waits", () => {
  test("direct waits return immediately for a prequeued follow-up", async () => {
    let called = false;
    const result = await waitWithSteering({ isDirectToolCall: true, hasPendingSteeringMessages: () => false, hasPendingMessages: () => true }, async () => { called = true; });
    expect(result).toMatchObject({ interrupted: true, reason: "follow-up" });
    expect(called).toBe(false);
  });

  test("a newly queued follow-up cancels a direct wait without cancelling its parent", async () => {
    let queued = false;
    const parent = new AbortController();
    const result = waitWithSteering({ isDirectToolCall: true, hasPendingSteeringMessages: () => false, hasPendingMessages: () => queued }, untilAborted, parent.signal);
    queued = true;
    expect(await result).toMatchObject({ reason: "follow-up" });
    expect(parent.signal.aborted).toBe(false);
  });

  test("a manager completion claimed during follow-up cancellation is not lost", async () => {
    let queued = false;
    const completion = { message: "finished", event: { id: "claimed" } };
    const result = waitWithSteering({ isDirectToolCall: true, hasPendingSteeringMessages: () => false, hasPendingMessages: () => queued }, async signal => {
      try { await untilAborted(signal); } catch { return completion; }
    });
    queued = true;
    expect(await result).toBe(completion);
  });

  test("nested waits ignore follow-ups and still return the manager's completion", async () => {
    const completion = { message: "finished" };
    const result = await waitWithSteering({ isDirectToolCall: false, hasPendingSteeringMessages: () => false, hasPendingMessages: () => true }, async () => {
      await delay(80);
      return completion;
    });
    expect(result).toBe(completion);
  });

  test("steering takes precedence when both queues contain input", async () => {
    const result = await waitWithSteering({ isDirectToolCall: true, hasPendingSteeringMessages: () => true, hasPendingMessages: () => true }, untilAborted);
    expect(result).toMatchObject({ reason: "steering" });
  });

  test("direct waits require the all-input predicate", async () => {
    await expect(waitWithSteering({ isDirectToolCall: true, hasPendingSteeringMessages: () => false }, untilAborted)).rejects.toThrow("hasPendingMessages() support");
  });
  test("requires an explicit core capability rather than trusting an older all-input predicate", async () => {
    let called = false;
    await expect(waitWithSteering({}, async () => { called = true; })).rejects.toThrow("hasPendingSteeringMessages() support");
    expect(called).toBe(false);
  });

  test("already queued steering skips the wait without aborting the parent", async () => {
    const parent = new AbortController();
    let called = false;
    const result = await waitWithSteering({ hasPendingSteeringMessages: () => true }, async () => { called = true; }, parent.signal);
    expect(result).toMatchObject({ interrupted: true });
    expect(called).toBe(false);
    expect(parent.signal.aborted).toBe(false);
  });

  test("new steering aborts only the local wait and stops queue polling", async () => {
    const parent = new AbortController();
    let queued = false;
    let checks = 0;
    let waitSignal: AbortSignal | undefined;
    const result = waitWithSteering({ hasPendingSteeringMessages() { checks++; return queued; } }, (signal) => {
      waitSignal = signal;
      return untilAborted(signal);
    }, parent.signal);
    queued = true;
    expect(await result).toMatchObject({ interrupted: true });
    expect(waitSignal?.aborted).toBe(true);
    expect(parent.signal.aborted).toBe(false);
    const settledChecks = checks;
    await delay(75);
    expect(checks).toBe(settledChecks);
  });

  test("recognizes the timer cancellation shape used by the all-target wait", async () => {
    let queued = false;
    const result = waitWithSteering({ hasPendingSteeringMessages: () => queued }, async (signal) => {
      await delay(10000, undefined, { signal });
      return { message: "finished" };
    });
    queued = true;
    expect(await result).toMatchObject({ interrupted: true });
  });

  test("returns the manager's consumed completion even if steering has since queued", async () => {
    let queued = false;
    const completion = { message: "finished", event: { id: "consumed-completion" } };
    const result = await waitWithSteering({ hasPendingSteeringMessages: () => queued }, async () => {
      queued = true;
      return completion;
    });
    expect(result).toBe(completion);
  });

  test("clears polling after an ordinary completion", async () => {
    let checks = 0;
    let waitSignal: AbortSignal | undefined;
    const result = await waitWithSteering({ hasPendingSteeringMessages() { checks++; return false; } }, async (signal) => {
      waitSignal = signal;
      return { message: "finished" };
    });
    const settledChecks = checks;
    await delay(75);
    expect(result).toEqual({ message: "finished" });
    expect(checks).toBe(settledChecks);
    expect(waitSignal?.aborted).toBe(false);
  });

  test("clears the timeout after completion and preserves the manager result", async () => {
    let captured: AbortSignal | undefined;
    const result = await waitWithSteering({ hasPendingSteeringMessages: () => false }, async signal => {
      captured = signal;
      return { message: "finished" };
    }, undefined, 0.02);
    await delay(75);
    expect(result).toEqual({ message: "finished" });
    expect(captured?.aborted).toBe(false);
  });

  test("parent abort wins before the timeout", async () => {
    const parent = new AbortController();
    const reason = new Error("parent stopped");
    const result = waitWithSteering({ hasPendingSteeringMessages: () => false }, untilAborted, parent.signal, 0.2);
    parent.abort(reason);
    await expect(result).rejects.toBe(reason);
  });

  test("steering wins before the timeout", async () => {
    let queued = false;
    const result = waitWithSteering({ hasPendingSteeringMessages: () => queued }, untilAborted, undefined, 0.3);
    queued = true;
    expect(await result).toMatchObject({ reason: "steering" });
  });

  test("preserves a pre-existing parent abort even when input is queued", async () => {
    const parent = new AbortController();
    const reason = new Error("parent stopped");
    parent.abort(reason);
    await expect(waitWithSteering({ hasPendingSteeringMessages: () => true }, untilAborted, parent.signal)).rejects.toBe(reason);
  });

  test("preserves parent cancellation instead of reporting a steering wake", async () => {
    const parent = new AbortController();
    const reason = new Error("parent stopped");
    const result = waitWithSteering({ hasPendingSteeringMessages: () => false }, untilAborted, parent.signal);
    parent.abort(reason);
    await expect(result).rejects.toBe(reason);
  });

  test("does not mask unrelated failures after a local cancellation", async () => {
    let queued = false;
    const reason = new Error("manager failed");
    const result = waitWithSteering({ hasPendingSteeringMessages: () => queued }, async (signal) => {
      try { await untilAborted(signal); } catch { throw reason; }
    });
    queued = true;
    await expect(result).rejects.toBe(reason);
  });

  test("propagates queue-observation failures without leaving the manager waiting", async () => {
    const reason = new Error("context expired");
    let checks = 0;
    const result = waitWithSteering({ hasPendingSteeringMessages() {
      if (++checks > 1) throw reason;
      return false;
    } }, untilAborted);
    await expect(result).rejects.toBe(reason);
  });
});
