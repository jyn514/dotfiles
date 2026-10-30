import { expect, test } from "bun:test";
import detailedReasoning from "../../config/pi-agent/pi-extensions/detailed-reasoning";

function request(payload: unknown, provider = "openai", api = "openai-responses") {
  let handler: (event: { payload: unknown }, ctx: unknown) => unknown;
  detailedReasoning({
    on(name: string, callback: typeof handler) {
      expect(name).toBe("before_provider_request");
      handler = callback;
    },
  } as never);
  return handler!({ payload }, { model: { provider, api } });
}

test("requests detailed summaries for OpenAI Responses and Codex without changing effort or other data", () => {
  for (const [provider, api] of [["openai", "openai-responses"], ["openai-codex", "openai-codex-responses"]]) {
    for (const effort of ["low", "high"]) {
      const payload = { reasoning: { effort, summary: "auto" }, input: [], include: ["reasoning.encrypted_content"] };
      expect(request(payload, provider, api)).toEqual({
        ...payload, reasoning: { effort, summary: "detailed" },
      });
      expect(payload.reasoning.summary).toBe("auto");
    }
  }
});

test("leaves other providers and protocols unchanged", () => {
  const payload = { reasoning: { effort: "high", summary: "auto" } };
  for (const [provider, api] of [
    ["openrouter", "openai-responses"],
    ["azure-openai-responses", "azure-openai-responses"],
    ["openai", "openai-completions"],
  ]) {
    expect(request(payload, provider, api)).toBeUndefined();
  }
});

test("does not enable summaries or replace explicit summary choices", () => {
  for (const payload of [
    null, [], {}, { reasoning: null }, { reasoning: [] }, { reasoning: { effort: "none" } },
    ...["detailed", "concise", "off", null].map(summary => ({ reasoning: { effort: "high", summary } })),
  ]) {
    expect(request(payload)).toBeUndefined();
  }
});
