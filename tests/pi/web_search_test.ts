import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import webSearch from "../../config/pi-agent/pi-extensions/pi-web-search";
import {
  addWebSearchToPayload,
  appendWebSearchSources,
  createMetadataCollector,
} from "../../config/pi-agent/pi-extensions/pi-web-search-core";

describe("provider web search extension", () => {
  for (const [notificationName, notification] of [
    ["provider_event", { event: { payload: { type: "url_citation", url: "https://example.com/a", title: "A" } } }],
    ["provider_stream_event", { data: { type: "url_citation", url: "https://example.com/a", title: "A" } }],
  ] as const) {
    test(`injects provider search without fork registration and persists ${notificationName} citations on the same turn`, () => {
      const handlers = new Map<string, (...args: unknown[]) => unknown>();
      // This API deliberately has no registerProviderTool().
      const pi = {
        on(event: string, handler: (...args: unknown[]) => unknown) {
          handlers.set(event, handler);
        },
      } as unknown as ExtensionAPI;
      webSearch(pi);

      expect(handlers.get("before_provider_request")?.(
        { payload: { model: "test", input: [] } },
        { model: { api: "openai-responses" } },
      )).toEqual({
        model: "test", input: [],
        tools: [{ type: "web_search", search_context_size: "medium" }],
      });
      const event = {
        systemPrompt: "Base instructions.",
        systemPromptOptions: { sections: { other: "other guidance", web_search: "stale" } },
      };
      expect(handlers.get("before_agent_start")?.(
        event,
        { model: { api: "openai-responses" } },
      )).toBeUndefined();
      expect(event.systemPrompt).toBe("Base instructions.");
      expect(event.systemPromptOptions.sections).toEqual({
        other: "other guidance",
        web_search: expect.stringContaining(
          "Search results and snippets may lag behind origin sites.",
        ),
      });
      // Changing providers must remove earlier search guidance, not leave it stale.
      for (const model of [{ api: "unsupported" }, { api: "pi-virtual" }, undefined]) {
        event.systemPromptOptions.sections.web_search = "stale";
        expect(handlers.get("before_agent_start")?.(event, { model })).toBeUndefined();
        expect(event.systemPrompt).toBe("Base instructions.");
        expect(event.systemPromptOptions.sections).toEqual({ other: "other guidance" });
      }
      handlers.get("turn_start")?.({});
      handlers.get(notificationName)?.(notification);
      const result = handlers.get("message_end")?.({
        message: {
          role: "assistant",
          content: [{ type: "text", text: "The answer." }],
        },
      }) as { message: { content: unknown[] } };

      expect(result.message.content).toEqual([
        { type: "text", text: "The answer." },
        { type: "text", text: "Sources:\n- A: https://example.com/a" },
      ]);
      handlers.get("turn_start")?.({});
      expect(handlers.get("message_end")?.({
        message: { role: "assistant", content: [{ type: "text", text: "Next answer." }] },
      })).toBeUndefined();
    });
  }
});

describe("provider web search payloads", () => {
  const families = [
    {
      apis: ["anthropic-messages"],
      google: false,
      search: { type: "web_search_20250305", name: "web_search" },
      local: { name: "read", input_schema: { type: "object", properties: {} } },
    },
    {
      apis: ["azure-openai-responses", "openai-codex-responses", "openai-responses"],
      google: false,
      search: { type: "web_search", search_context_size: "medium" },
      local: { type: "function", name: "read", parameters: { type: "object", properties: {} } },
    },
    {
      apis: ["google-generative-ai", "google-vertex"],
      google: true,
      search: { googleSearch: {} },
      local: { functionDeclarations: [{ name: "read", parameters: { type: "OBJECT", properties: {} } }] },
    },
  ];

  for (const { apis, google, search, local } of families) {
    for (const api of apis) {
      test(`${api} adds native search without changing existing declarations or request fields`, () => {
        const payload = google
          ? { model: "test", contents: [], config: { temperature: 0.2, tools: [local] } }
          : { model: "test", messages: [], temperature: 0.2, tools: [local] };
        const original = structuredClone(payload);
        const result = addWebSearchToPayload(payload, api);
        expect(result).toEqual(google
          ? { ...payload, config: { ...payload.config, tools: [local, search] } }
          : { ...payload, tools: [local, search] });
        expect(payload).toEqual(original);
        expect(addWebSearchToPayload(result, api)).toBeUndefined();
      });

      test(`${api} enables native search without any local tools`, () => {
        const payload = google ? { model: "test", contents: [] } : { model: "test", messages: [] };
        expect(addWebSearchToPayload(payload, api)).toEqual(google
          ? { ...payload, config: { tools: [search] } }
          : { ...payload, tools: [search] });
      });
    }
  }

  test("keeps search options supplied by an earlier request handler", () => {
    for (const type of ["web_search", "web_search_preview", "web_search_20260209"]) {
      const payload = { tools: [{ type, filters: { allowed_domains: ["example.com"] } }] };
      expect(addWebSearchToPayload(payload, "openai-responses")).toBeUndefined();
      expect(payload.tools[0].filters.allowed_domains).toEqual(["example.com"]);
    }
    expect(addWebSearchToPayload({ config: { tools: [{ googleSearch: {} }] } }, "google-vertex"))
      .toBeUndefined();
  });

  test("leaves unsupported APIs and unavailable model identity unchanged", () => {
    for (const api of ["openai-completions", "bedrock-converse-stream", "pi-virtual", "unknown", "toString", undefined]) {
      expect(addWebSearchToPayload({ model: "test", tools: [] }, api)).toBeUndefined();
    }
  });

  test("does not replace malformed payloads or tool arrays", () => {
    for (const payload of [null, "text", [], { tools: null }, { tools: {} }]) {
      expect(addWebSearchToPayload(payload, "anthropic-messages")).toBeUndefined();
    }
    for (const config of [null, [], "text", { tools: {} }]) {
      expect(addWebSearchToPayload({ config }, "google-generative-ai")).toBeUndefined();
    }
  });
});

describe("native web search metadata", () => {
  test("collects and deduplicates citations and provider search queries", () => {
    const collector = createMetadataCollector();
    collector.observe({
      type: "content_block_start",
      content_block: {
        type: "web_search_result",
        url: "https://example.com/a",
        title: "A",
      },
    });
    collector.observe({
      candidates: [{
        groundingMetadata: {
          webSearchQueries: ["first query"],
          groundingChunks: [{ web: { uri: "https://example.com/b", title: "B" } }],
        },
      }],
    });
    collector.observe({
      type: "response.completed",
      response: {
        output: [
          {
            type: "web_search_call",
            action: {
              type: "search",
              queries: ["second query", "third query"],
              sources: [{ type: "url", url: "https://example.com/c", title: "C" }],
            },
          },
          { annotations: [{ type: "url_citation", url: "https://example.com/a" }] },
        ],
      },
    });

    expect(collector.metadata).toEqual({
      sources: [
        { url: "https://example.com/a", title: "A" },
        { url: "https://example.com/b", title: "B" },
        { url: "https://example.com/c", title: "C" },
      ],
      searches: ["first query", "second query", "third query"],
    });
  });

  test("ignores malformed URLs and handles cycles", () => {
    const payload: Record<string, unknown> = {
      type: "url_citation",
      url: "javascript:alert(1)",
    };
    payload.self = payload;
    const collector = createMetadataCollector();
    collector.observe(payload);
    expect(collector.metadata).toEqual({ sources: [], searches: [] });
  });
});

describe("web search citations", () => {
  test("appends missing sources to assistant content", () => {
    expect(appendWebSearchSources(
      [{ type: "text", text: "The answer." }],
      [
        { url: "https://example.com/a", title: "A" },
        { url: "https://example.com/b" },
      ],
    )).toEqual([
      { type: "text", text: "The answer." },
      {
        type: "text",
        text: "Sources:\n- A: https://example.com/a\n- https://example.com/b",
      },
    ]);
  });

  test("does not duplicate citations already present in text", () => {
    const content = [{ type: "text", text: "See https://example.com/a." }];
    expect(appendWebSearchSources(content, [{ url: "https://example.com/a", title: "A" }])).toBe(content);
  });
});
