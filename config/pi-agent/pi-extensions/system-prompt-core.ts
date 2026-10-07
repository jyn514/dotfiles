import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type SystemPromptSnapshot = {
  readonly prompt: string;
  readonly model: { readonly provider: string; readonly id: string } | undefined;
  readonly capturedAt: string;
};

type PromptCapture = () => SystemPromptSnapshot | undefined;
const captures = new WeakMap<ExtensionAPI, PromptCapture>();

// Both viewers share one capture per extension API, not process-global state.
// Pi clears per-run prompt options at settlement, so idle getters lose changes.
export function observeSystemPrompt(pi: ExtensionAPI): PromptCapture {
  const existing = captures.get(pi);
  if (existing) return existing;

  let snapshot: SystemPromptSnapshot | undefined;
  pi.on("session_start", () => { snapshot = undefined; });
  pi.on("before_provider_request", (_event, ctx) => {
    snapshot = {
      prompt: ctx.getSystemPrompt(),
      model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : undefined,
      capturedAt: new Date().toISOString(),
    };
  });
  const capture = () => snapshot;
  captures.set(pi, capture);
  return capture;
}

export const NO_PROMPT_CAPTURE =
  "No system prompt captured since session start or reload. Send a prompt first.";

export function describeSystemPromptSnapshot(snapshot: SystemPromptSnapshot): string {
  return [
    `Selected model: ${snapshot.model ? `${snapshot.model.provider}/${snapshot.model.id}` : "unknown"}`,
    `Captured at: ${snapshot.capturedAt}`,
    "Pi prompt snapshot; excludes context-message and provider-payload rewrites.",
  ].join("\n");
}
