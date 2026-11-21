export class WaitTimeout extends Error {}

export interface InterruptedWait {
  message: string;
  interrupted: true;
  reason: "steering" | "follow-up";
}

/** End only the wait when eligible input arrives; the manager owns completion delivery and cleanup. */
export async function waitWithSteering<T>(
  ctx: { isDirectToolCall?: boolean; hasPendingSteeringMessages?(): boolean; hasPendingMessages?(): boolean },
  wait: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
  timeoutSeconds?: number,
): Promise<T | InterruptedWait> {
  signal?.throwIfAborted();
  if (typeof ctx.hasPendingSteeringMessages !== "function") {
    throw new Error("Interruptible agent waits require Pi with hasPendingSteeringMessages() support. Restart with the updated Pi core.");
  }
  if (ctx.isDirectToolCall && typeof ctx.hasPendingMessages !== "function") {
    throw new Error("Direct interruptible agent waits require Pi with hasPendingMessages() support. Restart with the updated Pi core.");
  }
  const pendingInput = (): InterruptedWait | undefined => {
    const reason = ctx.hasPendingSteeringMessages!() ? "steering"
      : ctx.isDirectToolCall && ctx.hasPendingMessages!() ? "follow-up" : undefined;
    return reason ? { message: `Wait interrupted by queued ${reason}. Child agents were not stopped.`, interrupted: true, reason } : undefined;
  };
  const pending = pendingInput();
  if (pending) return pending;

  const controller = new AbortController();
  const waitSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  let interruption: InterruptedWait | undefined;
  const inputArrived = new Error("Queued input arrived.");
  const timeout = new WaitTimeout("Agent wait timed out.");
  let remainingSeconds = timeoutSeconds;
  let timeoutTimer: ReturnType<typeof setTimeout> | undefined;
  const scheduleTimeout = () => {
    if (remainingSeconds === undefined) return;
    const seconds = Math.min(remainingSeconds, 2_147_483);
    timeoutTimer = setTimeout(() => {
      remainingSeconds! -= seconds;
      if (remainingSeconds! <= 0) controller.abort(timeout);
      else scheduleTimeout();
    }, seconds * 1000);
  };
  scheduleTimeout();
  const timer = setInterval(() => {
    if (controller.signal.aborted) return;
    try {
      interruption = pendingInput();
      if (interruption) controller.abort(inputArrived);
    } catch (error) {
      controller.abort(error instanceof Error ? error : new Error(String(error)));
    }
  }, 50);
  try {
    // Await the manager, not a separate race: a fulfilled wait may already own a completion.
    return await wait(waitSignal);
  } catch (error) {
    if (signal?.aborted) throw error;
    if (interruption && (error === inputArrived || (error instanceof Error && error.name === "AbortError" && error.cause === inputArrived))) {
      return interruption;
    }
    throw error;
  } finally {
    clearInterval(timer);
    if (timeoutTimer !== undefined) clearTimeout(timeoutTimer);
  }
}
