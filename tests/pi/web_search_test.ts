import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import webSearch from "../../config/pi-extensions/pi-web-search";
import {
  appendWebSearchSources,
  createMetadataCollector,
  SUPPORTED_SEARCH_APIS,
} from "../../config/pi-extensions/pi-web-search-core";

describe("provider web search extension", () => {
  test("does not break startup on Pi versions without provider tools", () => {
    expect(() => webSearch({} as ExtensionAPI)).not.toThrow();
  });

  test("registers provider search and persists citations on the same assistant turn", () => {
    const handlers = new Map<string, (...args: unknown[]) => unknown>();
    const providerTools: unknown[] = [];
    const pi = {
      registerProviderTool(tool: unknown) {
        providerTools.push(tool);
      },
      on(event: string, handler: (...args: unknown[]) => unknown) {
        handlers.set(event, handler);
      },
    } as unknown as ExtensionAPI;
    webSearch(pi);

    expect(providerTools).toEqual([{ type: "web_search", searchContextSize: "medium" }]);
    expect(handlers.get("before_agent_start")?.(
      { systemPrompt: "Base instructions." },
      { model: { api: "openai-responses" } },
    )).toEqual({
      systemPrompt: expect.stringContaining(
        "Search results and snippets may lag behind origin sites.",
      ),
    });
    handlers.get("turn_start")?.({});
    handlers.get("provider_event")?.({
      event: {
        payload: { type: "url_citation", url: "https://example.com/a", title: "A" },
      },
    });
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
  });
});

describe("provider web search support", () => {
  test("lists APIs with first-class provider search serialization", () => {
    expect([...SUPPORTED_SEARCH_APIS]).toEqual([
      "anthropic-messages",
      "azure-openai-responses",
      "google-generative-ai",
      "google-vertex",
      "openai-codex-responses",
      "openai-responses",
    ]);
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
