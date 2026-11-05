import { describe, expect, test } from "bun:test";
import { setTimeout as delay } from "node:timers/promises";
import { waitWithSteering } from "./wait.js";

function untilAborted(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    if (signal.aborted) reject(signal.reason);
  });
}

describe("steering-interruptible waits", () => {
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
