import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function detailedReasoning(pi: ExtensionAPI) {
  pi.on("before_provider_request", (event, ctx) => {
    if (!ctx.model || !["openai", "openai-codex"].includes(ctx.model.provider)
      || !["openai-responses", "openai-codex-responses"].includes(ctx.model.api)) return;
    const payload = event.payload;
    if (!object(payload) || !object(payload.reasoning) || payload.reasoning.summary !== "auto") return;
    // Make the default explicit: "auto" can return only headings, without a summary body.
    return { ...payload, reasoning: { ...payload.reasoning, summary: "detailed" } };
  });
}
