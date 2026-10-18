import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ObjectValue = Record<string, unknown>;
function object(value: unknown): value is ObjectValue {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function capOpenRouterOutput(payload: unknown, cap: number): unknown {
  if (!object(payload)) return payload;
  const fields = ["max_tokens", "max_completion_tokens"];
  const limits = fields.map((field) => payload[field]).filter(
    (value): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0,
  );
  if (limits.length === 0) return payload;
  const limit = Math.min(cap, ...limits);
  const result = { ...payload };
  for (const field of fields) {
    if (limits.includes(payload[field] as number)) result[field] = limit;
  }
  // The hook runs after Pi computes thinking budgets. Keep its 1024-token answer
  // allowance when lowering an explicit budget; adaptive/effort settings stay intact.
  for (const [field, budget] of [["thinking", "budget_tokens"], ["reasoning", "max_tokens"]]) {
    const settings = payload[field];
    if (object(settings) && typeof settings[budget] === "number" && settings[budget] > limit - 1024) {
      // Existing tiny output limits cannot accommodate budget-based thinking.
      // Preserve those requests rather than inventing a provider-specific disable mode.
      if (limit < 2048) continue;
      result[field] = { ...settings, [budget]: limit - 1024 };
    }
  }
  return result;
}

export default function openRouterOutputCap(pi: ExtensionAPI) {
  pi.registerFlag("openrouter-max-tokens", {
    type: "string", default: "10000", description: "OpenRouter output cap (at least 2048 tokens)",
  });
  pi.on("before_provider_request", (event, ctx) => {
    if (ctx.model?.provider !== "openrouter"
      || !["anthropic-messages", "openai-completions"].includes(ctx.model.api)) return;
    const cap = Number(pi.getFlag("openrouter-max-tokens"));
    if (!Number.isSafeInteger(cap) || cap < 2048) {
      throw new Error("--openrouter-max-tokens must be an integer of at least 2048");
    }
    return capOpenRouterOutput(event.payload, cap);
  });
}
