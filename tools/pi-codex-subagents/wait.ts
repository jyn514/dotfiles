export class WaitTimeout extends Error {}

export interface InterruptedWait {
  message: string;
  interrupted: true;
  reason: "steering";
}

/** End only the wait when steering arrives; the manager owns completion delivery and cleanup. */
export async function waitWithSteering<T>(
  ctx: { hasPendingSteeringMessages?(): boolean },
  wait: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
  timeoutSeconds?: number,
): Promise<T | InterruptedWait> {
  signal?.throwIfAborted();
  if (typeof ctx.hasPendingSteeringMessages !== "function") {
    throw new Error("Interruptible agent waits require Pi with hasPendingSteeringMessages() support. Restart with the updated Pi core.");
  }
  const hasSteering = ctx.hasPendingSteeringMessages.bind(ctx);
  const interrupted: InterruptedWait = {
    message: "Wait interrupted by queued steering. Child agents were not stopped.",
    interrupted: true,
    reason: "steering",
  };
  if (hasSteering()) return interrupted;

  const controller = new AbortController();
  const waitSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  const steeringArrived = new Error("Queued steering arrived.");
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
    try {
      if (hasSteering()) controller.abort(steeringArrived);
    } catch (error) {
      controller.abort(error instanceof Error ? error : new Error(String(error)));
    }
  }, 50);
  try {
    // Await the manager, not a separate race: a fulfilled wait may already own a completion.
    return await wait(waitSignal);
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error === steeringArrived || (error instanceof Error && error.name === "AbortError" && error.cause === steeringArrived)) {
      return interrupted;
    }
    throw error;
  } finally {
    clearInterval(timer);
    if (timeoutTimer !== undefined) clearTimeout(timeoutTimer);
  }
}
