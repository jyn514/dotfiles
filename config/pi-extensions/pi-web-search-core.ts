export interface WebSource {
  url: string;
  title?: string;
}

export interface SearchMetadata {
  sources: WebSource[];
  searches: string[];
}

interface SearchModel {
  api: string;
  provider: string;
  id: string;
  maxTokens: number;
}

interface SearchResponse<TUsage> {
  content: Array<{ type: string; text?: string }>;
  stopReason: string;
  errorMessage?: string;
  usage: TUsage;
}

export interface NativeSearchResult<TUsage> extends SearchMetadata {
  answer: string;
  usage: TUsage;
}

export type SearchApi =
  | "anthropic-messages"
  | "azure-openai-responses"
  | "google-generative-ai"
  | "google-vertex"
  | "openai-codex-responses"
  | "openai-responses";

const SUPPORTED_APIS = new Set<string>([
  "anthropic-messages",
  "azure-openai-responses",
  "google-generative-ai",
  "google-vertex",
  "openai-codex-responses",
  "openai-responses",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function isSearchApi(api: string): api is SearchApi {
  return SUPPORTED_APIS.has(api);
}

export function addNativeSearchTool(payload: unknown, api: SearchApi): unknown {
  if (!isRecord(payload)) throw new Error(`Invalid ${api} request payload`);

  if (api === "anthropic-messages") {
    const tools = recordArray(payload.tools);
    if (tools.some((tool) => tool.type === "web_search_20250305")) return payload;
    return { ...payload, tools: [...tools, { type: "web_search_20250305", name: "web_search" }] };
  }

  if (api === "google-generative-ai" || api === "google-vertex") {
    const config = isRecord(payload.config) ? payload.config : {};
    const tools = recordArray(config.tools);
    if (tools.some((tool) => "googleSearch" in tool)) return payload;
    return { ...payload, config: { ...config, tools: [...tools, { googleSearch: {} }] } };
  }

  const tools = recordArray(payload.tools);
  if (tools.some((tool) => tool.type === "web_search")) return payload;
  return { ...payload, tools: [...tools, { type: "web_search" }] };
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function createMetadataCollector(): {
  metadata: SearchMetadata;
  eventCount: number;
  observe(payload: unknown): void;
} {
  const sources = new Map<string, WebSource>();
  let eventCount = 0;
  const searches = new Set<string>();
  const seen = new Set<object>();

  function addSource(url: unknown, title: unknown): void {
    const parsedUrl = optionalString(url);
    if (!parsedUrl || !/^https?:\/\//i.test(parsedUrl)) return;
    const parsedTitle = optionalString(title);
    const current = sources.get(parsedUrl);
    if (!current || (!current.title && parsedTitle)) {
      sources.set(parsedUrl, { url: parsedUrl, ...(parsedTitle ? { title: parsedTitle } : {}) });
    }
  }

  function visit(value: unknown): void {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    if (!isRecord(value) || seen.has(value)) return;
    seen.add(value);

    if (
      value.type === "url_citation" ||
      value.type === "web_search_result" ||
      value.type === "web_search_result_location"
    ) {
      addSource(value.url, value.title);
    }

    if (isRecord(value.web)) addSource(value.web.uri, value.web.title);

    if (Array.isArray(value.webSearchQueries)) {
      for (const query of value.webSearchQueries) {
        if (typeof query === "string" && query.length > 0) searches.add(query);
      }
    }
    if (value.type === "server_tool_use" && value.name === "web_search" && isRecord(value.input)) {
      const query = optionalString(value.input.query);
      if (query) searches.add(query);
    }
    if (value.type === "web_search_call" && isRecord(value.action)) {
      const query = optionalString(value.action.query);
      if (query) searches.add(query);
      if (Array.isArray(value.action.queries)) {
        for (const current of value.action.queries) {
          if (typeof current === "string" && current.length > 0) searches.add(current);
        }
      }
      for (const source of recordArray(value.action.sources)) addSource(source.url, source.title);
    }

    for (const child of Object.values(value)) visit(child);
  }

  return {
    get metadata() {
      return { sources: [...sources.values()], searches: [...searches] };
    },
    get eventCount() {
      return eventCount;
    },
    observe(payload) {
      eventCount++;
      visit(payload);
    },
  };
}

function textContent(content: Array<{ type: string; text?: string }>): string {
  return content
    .filter((block): block is { type: "text"; text: string } => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
}

function appendSources(answer: string, sources: WebSource[]): string {
  const missing = sources.filter((source) => !answer.includes(source.url)).slice(0, 20);
  if (missing.length === 0) return answer;
  const lines = missing.map((source) => source.title ? `- ${source.title}: ${source.url}` : `- ${source.url}`);
  return `${answer}\n\nSources:\n${lines.join("\n")}`;
}

export async function runNativeWebSearch<TUsage>(
  model: SearchModel,
  query: string,
  signal: AbortSignal | undefined,
  complete: (
    context: {
      systemPrompt: string;
      messages: Array<{
        role: "user";
        content: Array<{ type: "text"; text: string }>;
        timestamp: number;
      }>;
    },
    options: {
      signal: AbortSignal | undefined;
      cacheRetention: "none";
      maxTokens: number;
      onPayload(payload: unknown): unknown;
      onProviderEvent(event: { payload: unknown }): void;
    },
  ) => Promise<SearchResponse<TUsage>>,
): Promise<NativeSearchResult<TUsage>> {
  if (!isSearchApi(model.api)) {
    throw new Error(`Native web search is not supported by ${model.provider}/${model.id} (${model.api})`);
  }

  const collector = createMetadataCollector();
  const response = await complete(
    {
      systemPrompt:
        "Use the provider's native web search tool to answer the question. Be concise and distinguish uncertainty.",
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: query }],
          timestamp: Date.now(),
        },
      ],
    },
    {
      signal,
      cacheRetention: "none",
      maxTokens: model.maxTokens > 0 ? Math.min(4096, model.maxTokens) : 4096,
      onPayload: (payload) => addNativeSearchTool(payload, model.api),
      onProviderEvent: (event) => collector.observe(event.payload),
    },
  );

  if (response.stopReason === "error" || response.stopReason === "aborted") {
    throw new Error(response.errorMessage || `Web search ${response.stopReason}`);
  }
  if (collector.eventCount === 0) {
    throw new Error("This Pi build does not expose native provider events; update Pi before using web_search");
  }

  const answer = textContent(response.content);
  if (!answer) throw new Error("Web search returned no text");
  const metadata = collector.metadata;
  if (metadata.sources.length === 0 && metadata.searches.length === 0) {
    throw new Error("The provider returned an answer without using native web search");
  }
  return {
    answer: appendSources(answer, metadata.sources),
    sources: metadata.sources.slice(0, 20),
    searches: metadata.searches.slice(0, 20),
    usage: response.usage,
  };
}
