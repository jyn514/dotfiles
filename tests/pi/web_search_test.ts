import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import webSearch from "../../config/pi-agent/pi-extensions/pi-web-search";
import {
  addWebSearchToPayload,
  appendWebSearchSources,
  createMetadataCollector,
  linkWebSearchCitations,
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
      annotatedTexts: [],
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
    expect(collector.metadata).toEqual({ sources: [], searches: [], annotatedTexts: [] });
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

describe("position-bound inline citations", () => {
  const marker = "\uE200cite\uE202turn1search0\uE201";
  const otherMarker = "\uE200cite\uE202turn2search9\uE201";
  const source = { type: "url_citation", url: "https://example.com/a", title: "A" };
  const citation = (text: string, currentMarker = marker, resource = source) => ({
    ...resource, start_index: text.indexOf(currentMarker), end_index: text.indexOf(currentMarker) + currentMarker.length,
  });
  const item = (id: string, text: string, annotations: unknown[]) => ({
    type: "message", role: "assistant", id,
    content: [{ type: "output_text", text, annotations }],
  });
  const collect = (...items: ReturnType<typeof item>[]) => {
    const collector = createMetadataCollector();
    for (const current of items) collector.observe({ type: "response.output_item.done", item: current });
    collector.observe({ type: "response.completed", response: { output: structuredClone(items) } });
    return collector.metadata;
  };
  const render = (text: string, metadata: ReturnType<typeof collect>) => appendWebSearchSources(
    linkWebSearchCitations([{ type: "text", text }], metadata.annotatedTexts), metadata.sources,
  );

  test("links by position, not source discovery order or the turn search number", () => {
    const text = `First ${marker}; second ${otherMarker}.`;
    const b = { ...source, url: "https://example.com/b", title: "B" };
    const metadata = collect(item("answer", text, [citation(text, otherMarker, b), citation(text)]));
    expect(metadata.sources[0].url).toBe(b.url);
    expect(render(text, metadata)).toEqual([
      { type: "text", text: "First [A](<https://example.com/a>); second [B](<https://example.com/b>)." },
    ]);
    expect(metadata.annotatedTexts).toHaveLength(1); // Both final notifications describe the same item.
  });

  test("binds annotations to separate final output texts, preserving block fields", () => {
    const first = `First ${marker}`;
    const second = `Second ${marker}`;
    const b = { ...source, url: "https://example.com/b", title: "B" };
    const metadata = collect(item("second", second, [citation(second, marker, b)]), item("first", first, [citation(first)]));
    expect(linkWebSearchCitations([
      { type: "thinking", text: "untouched" },
      { type: "text", text: first, textSignature: "opaque signature" },
      { type: "text", text: second },
    ], metadata.annotatedTexts)).toEqual([
      { type: "thinking", text: "untouched" },
      { type: "text", text: "First [A](<https://example.com/a>)", textSignature: "opaque signature" },
      { type: "text", text: "Second [B](<https://example.com/b>)" },
    ]);
  });

  test("keeps all URLs on a grouped marker, deduplicating repeated annotations", () => {
    const grouped = "\uE200cite\uE202turn1search0\uE202turn1search1\uE201";
    const text = `Claim ${grouped}`;
    const a = citation(text, grouped);
    const b = citation(text, grouped, { ...source, url: "https://example.com/b", title: "B" });
    expect(render(text, collect(item("answer", text, [a, b, a])))).toEqual([
      { type: "text", text: "Claim [A](<https://example.com/a>) [B](<https://example.com/b>)" },
    ]);
  });

  for (const units of ["characters", "UTF-16"] as const) {
    for (const inclusive of [false, true]) {
      test(`supports ${units} offsets with ${inclusive ? "inclusive" : "exclusive"} ends after emoji`, () => {
        const text = `😀 Claim ${marker}`;
        const start = units === "characters" ? [..."😀 Claim "].length : "😀 Claim ".length;
        const annotation = { ...source, start_index: start, end_index: start + marker.length - Number(inclusive) };
        expect(render(text, collect(item("answer", text, [annotation])))).toEqual([
          { type: "text", text: "😀 Claim [A](<https://example.com/a>)" },
        ]);
      });
    }
  }

  test("offsets are local to each provider content part", () => {
    const text = `Claim ${marker}`;
    const current = item("answer", text, [citation(text)]);
    current.content.unshift({ type: "output_text", text: "😀 Preface. ", annotations: [] });
    expect(render(`😀 Preface. ${text}`, collect(current))).toEqual([
      { type: "text", text: "😀 Preface. Claim [A](<https://example.com/a>)" },
    ]);
  });

  test("unusable annotations keep the source list without changing prose or guessing links", () => {
    const text = `Claim ${marker}`;
    for (const invalid of [
      { start_index: -1, end_index: marker.length },
      { start_index: 6.5, end_index: 6 + marker.length },
      { start_index: 6, end_index: NaN },
      { start_index: 7, end_index: 6 + marker.length },
      { start_index: 6, end_index: 500 },
      { start_index: 6, end_index: 5 },
      {},
      { start_index: 0, end_index: 5 }, // Cited prose is not a provider marker.
    ]) {
      expect(render(text, collect(item("answer", text, [{ ...source, ...invalid }])))).toEqual([
        { type: "text", text }, { type: "text", text: "Sources:\n- A: https://example.com/a" },
      ]);
    }
    const unsafe = { ...citation(text), url: "javascript:alert(1)" };
    expect(render(text, collect(item("answer", text, [unsafe])))).toEqual([{ type: "text", text }]);
  });

  test("does not attach citations to stale or ambiguous output text", () => {
    const text = `Claim ${marker}`;
    const a = item("a", text, [citation(text)]);
    const b = item("b", text, [citation(text, marker, { ...source, url: "https://example.com/b", title: "B" })]);
    const content = [{ type: "text", text }];
    expect(linkWebSearchCitations(content, collect(a, b).annotatedTexts)).toEqual(content);
    expect(linkWebSearchCitations([...content, ...content], collect(a).annotatedTexts)).toEqual([...content, ...content]);
    const changed = [{ type: "text", text: `Changed ${marker}` }];
    expect(linkWebSearchCitations(changed, collect(a).annotatedTexts)).toEqual(changed);
  });

  test("refuses offsets that identify different markers under different Unicode counting conventions", () => {
    const text = `${"😀".repeat(marker.length)}${marker}${marker}`;
    const annotation = { ...source, start_index: 2 * marker.length, end_index: 3 * marker.length };
    expect(render(text, collect(item("answer", text, [annotation])))).toEqual([
      { type: "text", text }, { type: "text", text: "Sources:\n- A: https://example.com/a" },
    ]);
  });

  test("does not use a streamed URL without its final positioned annotation", () => {
    const text = `Claim ${marker}`;
    const collector = createMetadataCollector();
    collector.observe({ type: "response.output_text.annotation.added", annotation: citation(text) });
    collector.observe({ type: "response.output_item.done", item: item("answer", text, []) });
    expect(render(text, collector.metadata)).toEqual([
      { type: "text", text }, { type: "text", text: "Sources:\n- A: https://example.com/a" },
    ]);
  });

  test("escaped URL destinations do not acquire duplicate source footers", () => {
    const text = `Claim ${marker}`;
    for (const [url, destination] of [
      ["https://example.com/a>z", "https://example.com/a%3Ez"],
      ["https://example.com/a<z", "https://example.com/a%3Cz"],
      ["https://example.com/a z", "https://example.com/a%20z"],
      ["https://example.com/a\\z", "https://example.com/a%5Cz"],
    ]) {
      expect(render(text, collect(item("answer", text, [citation(text, marker, { ...source, url })])))).toEqual([
        { type: "text", text: `Claim [A](<${destination}>)` },
      ]);
    }
  });

  test("escapes source titles so they cannot create extra Markdown links", () => {
    const text = `Claim ${marker}`;
    const hostile = { ...source, title: "[A](https://wrong.invalid) *bold*\n<unsafe>" };
    expect(render(text, collect(item("answer", text, [citation(text, marker, hostile)])))).toEqual([
      { type: "text", text: "Claim [\\[A\\](https://wrong.invalid) \\*bold\\* \\<unsafe\\>](<https://example.com/a>)" },
    ]);
  });
});
