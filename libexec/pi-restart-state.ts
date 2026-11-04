import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

export const RESTART_STATE_CHANNEL = "sandbox:restart-state:v1";

/** Optional extension state carried by the explicit sandbox restart protocol.
 * Capture records the live owner's selection; reopened pending generations
 * retain their existing capture. Restore runs after generation validation but
 * before children and queued work resume. Ordinary session loads do not invoke
 * these methods. Each extension owns its durable representation.
 */
export interface RestartState {
  capture(ctx: ExtensionCommandContext): void | Promise<void>;
  restore(ctx: ExtensionCommandContext): void | Promise<void>;
}

export interface RestartStateDiscovery {
  provide(state: RestartState): void;
}

/** Discover synchronously, then await participants directly rather than relying
 * on event-bus handlers, whose errors Pi logs without propagating to callers.
 */
export function restartStates(pi: Pick<ExtensionAPI, "events">): RestartState[] {
  const states: RestartState[] = [];
  pi.events.emit(RESTART_STATE_CHANNEL, {
    provide(state: RestartState) { states.push(state); },
  } satisfies RestartStateDiscovery);
  return states;
}
