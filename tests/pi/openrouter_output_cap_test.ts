import { expect, test } from "bun:test";
import openRouterOutputCap from "../../config/pi-agent/pi-extensions/openrouter-output-cap";

function request(payload: unknown, provider = "openrouter", api = "openai-completions", cap = "10000") {
  let handler: (event: { payload: unknown }, ctx: unknown) => unknown;
  openRouterOutputCap({
    registerFlag() {},
    getFlag: () => cap,
    on(_name: string, callback: typeof handler) { handler = callback; },
  } as never);
  return handler!({ payload }, { model: { provider, api } });
}

test("caps both wire formats, preserving smaller limits and unrelated payload data", () => {
  for (const field of ["max_tokens", "max_completion_tokens"]) {
    for (const [original, expected] of [[128000, 10000], [4096, 4096]]) {
      const payload = { [field]: original, messages: [{ role: "user", content: "hello" }], tools: [], provider: { order: ["anthropic"] } };
      expect(request(payload)).toEqual({ ...payload, [field]: expected });
      expect(payload[field]).toBe(original);
    }
  }
});

test("explicit thinking budgets fit the reduced output allowance in both protocols", () => {
  for (const [api, field, budget] of [
    ["anthropic-messages", "thinking", "budget_tokens"],
    ["openai-completions", "reasoning", "max_tokens"],
  ]) {
    const payload = { max_tokens: 128000, [field]: { [budget]: 32000, type: "enabled" } };
    expect(request(payload, "openrouter", api)).toEqual({
      max_tokens: 10000, [field]: { [budget]: 8976, type: "enabled" },
    });
    expect(payload[field][budget]).toBe(32000);
    const smaller = { max_tokens: 4096, [field]: { [budget]: 1024 } };
    expect(request(smaller, "openrouter", api)).toEqual(smaller);
  }
});

test("preserves effort, adaptive thinking, and valid small requests", () => {
  for (const extra of [{ reasoning: { effort: "high" } }, { thinking: { type: "adaptive" } }]) {
    expect(request({ max_tokens: 128000, ...extra })).toEqual({ max_tokens: 10000, ...extra });
  }
  const small = { max_tokens: 1500, thinking: { type: "enabled", budget_tokens: 1024 } };
  expect(request(small, "openrouter", "anthropic-messages")).toEqual(small);
});

test("other providers and protocols pass through; absent or invalid limits are untouched", () => {
  expect(request({ max_tokens: 128000 }, "anthropic", "anthropic-messages")).toBeUndefined();
  expect(request({ max_tokens: 128000 }, "openrouter", "openai-responses")).toBeUndefined();
  for (const payload of [null, [], {}, { max_tokens: "128000" }, { max_tokens: -1 }]) {
    expect(request(payload)).toBe(payload);
  }
});

test("one flag changes the cap and its derived thinking allowance together", () => {
  expect(request({ max_tokens: 128000, reasoning: { max_tokens: 32000 } }, "openrouter", "openai-completions", "6000"))
    .toEqual({ max_tokens: 6000, reasoning: { max_tokens: 4976 } });
  for (const cap of ["0", "1024", "no", "Infinity", "2048.5"]) {
    expect(() => request({ max_tokens: 128000 }, "openrouter", "openai-completions", cap)).toThrow("at least 2048");
  }
});
