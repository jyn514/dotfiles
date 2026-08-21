export interface WebSource {
  url: string;
  title?: string;
}

export interface SearchMetadata {
  sources: WebSource[];
  searches: string[];
}

export const SUPPORTED_SEARCH_APIS = new Set([
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

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function createMetadataCollector(): {
  metadata: SearchMetadata;
  observe(payload: unknown): void;
} {
  const sources = new Map<string, WebSource>();
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
    observe: visit,
  };
}

export function appendWebSearchSources<T extends { type: string; text?: string }>(
  content: T[],
  sources: WebSource[],
): T[] {
  const existingText = content
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
  const missing = sources.filter((source) => !existingText.includes(source.url)).slice(0, 20);
  if (missing.length === 0) return content;

  const lines = missing.map((source) => source.title ? `- ${source.title}: ${source.url}` : `- ${source.url}`);
  return [
    ...content,
    { type: "text", text: `Sources:\n${lines.join("\n")}` } as T,
  ];
}
