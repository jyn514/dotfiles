export interface WebSource {
  url: string;
  title?: string;
}

interface WebCitation extends WebSource {
  start: number;
  end: number;
}

export interface AnnotatedText {
  text: string;
  citations: WebCitation[];
}

export interface SearchMetadata {
  sources: WebSource[];
  searches: string[];
  annotatedTexts: AnnotatedText[];
}

const openAISearch = () => ({ type: "web_search", search_context_size: "medium" });
const googleSearch = () => ({ googleSearch: {} });
const SEARCH_TOOLS = new Map<string, () => Record<string, unknown>>([
  ["anthropic-messages", () => ({ type: "web_search_20250305", name: "web_search" })],
  ["azure-openai-responses", openAISearch],
  ["google-generative-ai", googleSearch],
  ["google-vertex", googleSearch],
  ["openai-codex-responses", openAISearch],
  ["openai-responses", openAISearch],
]);

export const SUPPORTED_SEARCH_APIS = new Set(SEARCH_TOOLS.keys());

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Return a replacement provider payload, or undefined to leave it unchanged. */
export function addWebSearchToPayload(payload: unknown, api: string | undefined): unknown {
  const createTool = api === undefined ? undefined : SEARCH_TOOLS.get(api);
  if (!createTool || !isRecord(payload)) return;

  const searchTool = createTool();
  const google = "googleSearch" in searchTool;
  const owner = google ? (payload.config === undefined ? {} : payload.config) : payload;
  if (!isRecord(owner) || (owner.tools !== undefined && !Array.isArray(owner.tools))) return;
  const tools: unknown[] = owner.tools ?? [];

  // Preserve a search tool configured by an earlier payload handler rather than
  // adding another one or replacing its filters/context settings.
  if (tools.some((tool) => isRecord(tool) && (google
    ? "googleSearch" in tool
    : typeof tool.type === "string" && /^web_search(?:_|$)/.test(tool.type)))) return;

  const replacement = { ...owner, tools: [...tools, searchTool] };
  return google ? { ...payload, config: replacement } : replacement;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

const CITATION_MARKER = /\uE200cite\uE202[^\uE200\uE201\r\n]+\uE201/g;

/** Bind only a complete provider marker, never guess a URL from a search ID. */
function markerCitation(text: string, annotation: Record<string, unknown>): WebCitation | undefined {
  const { start_index: start, end_index: end, url } = annotation;
  if (annotation.type !== "url_citation" || typeof url !== "string" || !/^https?:\/\//i.test(url) ||
      typeof start !== "number" || typeof end !== "number" || !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) || start < 0 || end < start) return;

  // Provider offsets can count Unicode characters or UTF-16 code units, and
  // end_index can name the last character or the position after it. Accept
  // either only when it identifies the same complete marker unambiguously.
  const matches = [...text.matchAll(CITATION_MARKER)].filter((match) => {
    const unitsStart = match.index;
    const unitsEnd = unitsStart + match[0].length;
    const charactersStart = [...text.slice(0, unitsStart)].length;
    const charactersEnd = charactersStart + [...match[0]].length;
    return (start === unitsStart && (end === unitsEnd || end === unitsEnd - 1)) ||
      (start === charactersStart && (end === charactersEnd || end === charactersEnd - 1));
  });
  if (matches.length !== 1) return;
  const match = matches[0];
  const title = optionalString(annotation.title);
  return { start: match.index, end: match.index + match[0].length, url, ...(title ? { title } : {}) };
}

function annotatedResponseText(item: unknown): AnnotatedText | undefined {
  if (!isRecord(item) || item.type !== "message" || item.role !== "assistant" || !Array.isArray(item.content)) return;
  let text = "";
  const citations: WebCitation[] = [];
  for (const part of recordArray(item.content)) {
    const partText = part.type === "output_text" ? part.text : part.refusal;
    if (typeof partText !== "string") return;
    for (const annotation of recordArray(part.annotations)) {
      const citation = markerCitation(partText, annotation);
      if (citation) citations.push({ ...citation, start: text.length + citation.start, end: text.length + citation.end });
    }
    text += partText;
  }
  return { text, citations };
}

export function createMetadataCollector(): {
  metadata: SearchMetadata;
  observe(payload: unknown): void;
} {
  const sources = new Map<string, WebSource>();
  const searches = new Set<string>();
  const seen = new Set<object>();
  const annotatedTexts = new Map<string, AnnotatedText>();

  function collectResponseItem(item: unknown): void {
    if (!isRecord(item) || typeof item.id !== "string") return;
    const annotated = annotatedResponseText(item);
    if (annotated) annotatedTexts.set(item.id, annotated);
  }

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

    // Final output items bind offsets to their authoritative text. The same
    // item may arrive both on output_item.done and response.completed.
    if (value.type === "response.output_item.done") collectResponseItem(value.item);
    if (value.type === "response.completed" && isRecord(value.response)) {
      for (const item of recordArray(value.response.output)) collectResponseItem(item);
    }

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
      return { sources: [...sources.values()], searches: [...searches], annotatedTexts: [...annotatedTexts.values()] };
    },
    observe: visit,
  };
}

function citationDestination(url: string): string {
  // Angle-bracket destinations accept parentheses; encode characters that can
  // terminate the destination or escape its closing bracket.
  return url.replace(/[\\<>\s]/g, (character) => encodeURIComponent(character));
}

function citationLink(source: WebSource): string {
  const label = (source.title ?? "source").replace(/[\r\n]+/g, " ").replace(/[\\`*_[\]<>]/g, "\\$&");
  return `[${label}](<${citationDestination(source.url)}>)`;
}

export function linkWebSearchCitations<T extends { type: string; text?: string }>(
  content: T[],
  annotatedTexts: AnnotatedText[],
): T[] {
  return content.map((block) => {
    if (block.type !== "text" || typeof block.text !== "string") return block;
    const candidates = annotatedTexts.filter((annotated) => annotated.text === block.text);
    // Pi textSignature is opaque. Match the complete final text instead, and
    // refuse ambiguous repeated text rather than attaching another item's URL.
    if (candidates.length !== 1 || content.filter((other) => other.type === "text" && other.text === block.text).length !== 1) return block;
    const groups = new Map<number, { end: number; sources: Map<string, WebSource> }>();
    for (const citation of candidates[0].citations) {
      let group = groups.get(citation.start);
      if (!group) {
        group = { end: citation.end, sources: new Map() };
        groups.set(citation.start, group);
      }
      group.sources.set(citation.url, citation);
    }
    if (groups.size === 0) return block;
    let text = block.text;
    for (const [start, group] of [...groups].sort(([a], [b]) => b - a)) {
      const links = [...group.sources.values()].map(citationLink).join(" ");
      text = text.slice(0, start) + links + text.slice(group.end);
    }
    return { ...block, text };
  });
}

export function appendWebSearchSources<T extends { type: string; text?: string }>(
  content: T[],
  sources: WebSource[],
): T[] {
  const existingText = content
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
  const missing = sources.filter((source) => !existingText.includes(source.url) &&
    !existingText.includes(`](<${citationDestination(source.url)}>)`)).slice(0, 20);
  if (missing.length === 0) return content;

  const lines = missing.map((source) => source.title ? `- ${source.title}: ${source.url}` : `- ${source.url}`);
  return [
    ...content,
    { type: "text", text: `Sources:\n${lines.join("\n")}` } as T,
  ];
}
