import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  appendWebSearchSources,
  createMetadataCollector,
  SUPPORTED_SEARCH_APIS,
} from "./pi-web-search-core";

const SEARCH_INSTRUCTIONS = `Web search is available through the active model provider.
Use it for current facts, recent events, or information requiring external sources.
Search results and snippets may lag behind origin sites. For claims about what is latest or current, verify against a live first-party page, feed, or source repository instead of relying only on result ordering or snippets.
Honor any domain, date-range, result-count, or primary-source constraints in the user's request.`;

export default function webSearch(pi: ExtensionAPI) {
  if (typeof pi.registerProviderTool !== "function") return;

  let collector = createMetadataCollector();

  pi.registerProviderTool({
    type: "web_search",
    searchContextSize: "medium",
  });

  pi.on("before_agent_start", (event, ctx) => {
    if (!ctx.model || !SUPPORTED_SEARCH_APIS.has(ctx.model.api)) return;
    return { systemPrompt: `${event.systemPrompt}\n\n${SEARCH_INSTRUCTIONS}` };
  });

  pi.on("turn_start", () => {
    collector = createMetadataCollector();
  });

  pi.on("provider_event", ({ event }) => {
    collector.observe(event.payload);
  });

  pi.on("message_end", (event) => {
    if (event.message.role !== "assistant") return;
    const sources = collector.metadata.sources;
    if (sources.length === 0) return;
    return {
      message: {
        ...event.message,
        content: appendWebSearchSources(event.message.content, sources),
      },
    };
  });
}
