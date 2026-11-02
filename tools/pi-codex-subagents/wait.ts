export interface InterruptedWait {
  message: string;
  interrupted: true;
}

/** End only the wait when steering arrives; the manager owns completion delivery and cleanup. */
export async function waitWithSteering<T>(
  ctx: { hasPendingSteeringMessages?(): boolean },
  wait: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
): Promise<T | InterruptedWait> {
  signal?.throwIfAborted();
  if (typeof ctx.hasPendingSteeringMessages !== "function") {
    throw new Error("Interruptible agent waits require Pi with hasPendingSteeringMessages() support. Restart with the updated Pi core.");
  }
  const hasSteering = ctx.hasPendingSteeringMessages.bind(ctx);
  const interrupted: InterruptedWait = {
    message: "Wait interrupted by queued steering. Child agents were not stopped.",
    interrupted: true,
  };
  if (hasSteering()) return interrupted;

  const controller = new AbortController();
  const waitSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  const steeringArrived = new Error("Queued steering arrived.");
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
  }
}
