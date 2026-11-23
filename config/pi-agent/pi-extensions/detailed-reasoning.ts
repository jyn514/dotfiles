import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function detailedReasoningPayload(payload: unknown, model: { provider: string; api: string } | undefined): unknown {
  if (!model || !["openai", "openai-codex"].includes(model.provider)
    || !["openai-responses", "openai-codex-responses"].includes(model.api)) return payload;
  if (!object(payload) || !object(payload.reasoning) || payload.reasoning.summary !== "auto") return payload;
  // Make the default explicit: "auto" can return only headings, without a summary body.
  return { ...payload, reasoning: { ...payload.reasoning, summary: "detailed" } };
}

export default function detailedReasoning(pi: ExtensionAPI) {
  pi.on("before_provider_request", (event, ctx) => {
    const payload = detailedReasoningPayload(event.payload, ctx.model);
    return payload === event.payload ? undefined : payload;
  });
}
