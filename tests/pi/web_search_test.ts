import { describe, expect, test } from "bun:test";
import {
  addNativeSearchTool,
  createMetadataCollector,
  runNativeWebSearch,
} from "../../config/pi-web-search-core";

describe("native web search payloads", () => {
  test("adds each provider's native tool without losing existing tools", () => {
    expect(addNativeSearchTool(
      { tools: [{ name: "local", input_schema: {} }] },
      "anthropic-messages",
    )).toEqual({
      tools: [
        { name: "local", input_schema: {} },
        { type: "web_search_20250305", name: "web_search" },
      ],
    });

    expect(addNativeSearchTool(
      { config: { temperature: 0, tools: [{ functionDeclarations: [] }] } },
      "google-generative-ai",
    )).toEqual({
      config: {
        temperature: 0,
        tools: [{ functionDeclarations: [] }, { googleSearch: {} }],
      },
    });

    expect(addNativeSearchTool(
      { tools: [{ type: "function", name: "local" }] },
      "openai-responses",
    )).toEqual({
      tools: [{ type: "function", name: "local" }, { type: "web_search" }],
    });
  });

  test("does not add duplicate native tools", () => {
    const payload = { tools: [{ type: "web_search" }] };
    expect(addNativeSearchTool(payload, "openai-codex-responses")).toBe(payload);
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

  test("returns citations and nested usage to the calling tool", async () => {
    const usage = { input: 4, output: 8 };
    const result = await runNativeWebSearch(
      { api: "openai-responses", provider: "openai", id: "gpt-test", maxTokens: 2048 },
      "what happened?",
      undefined,
      async (context, options) => {
        expect(context.messages[0].content[0].text).toBe("what happened?");
        expect(options.maxTokens).toBe(2048);
        expect(options.onPayload({ tools: [] })).toEqual({ tools: [{ type: "web_search" }] });
        options.onProviderEvent({
          payload: {
            type: "response.completed",
            response: {
              output: [{
                annotations: [{ type: "url_citation", url: "https://example.com/news", title: "News" }],
              }],
            },
          },
        });
        return {
          content: [{ type: "text", text: "The answer." }],
          stopReason: "stop",
          usage,
        };
      },
    );

    expect(result).toEqual({
      answer: "The answer.\n\nSources:\n- News: https://example.com/news",
      sources: [{ url: "https://example.com/news", title: "News" }],
      searches: [],
      usage,
    });
  });

  test("fails clearly when Pi drops provider events", async () => {
    await expect(runNativeWebSearch(
      { api: "openai-responses", provider: "openai", id: "gpt-test", maxTokens: 8192 },
      "query",
      undefined,
      async () => ({
        content: [{ type: "text", text: "Uncited answer" }],
        stopReason: "stop",
        usage: {},
      }),
    )).rejects.toThrow("update Pi");
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
