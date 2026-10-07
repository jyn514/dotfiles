import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  addWebSearchToPayload,
  appendWebSearchSources,
  createMetadataCollector,
  SUPPORTED_SEARCH_APIS,
} from "./pi-web-search-core";

const SEARCH_INSTRUCTIONS = `Web search is available through the active model provider.
Use it for current facts, recent events, or information requiring external sources.
Search results and snippets may lag behind origin sites. For claims about what is latest or current, verify against a live first-party page, feed, or source repository instead of relying only on result ordering or snippets.
Honor any domain, date-range, result-count, or primary-source constraints in the user's request.`;

export default function webSearch(pi: ExtensionAPI) {
  let collector = createMetadataCollector();

  pi.on("before_provider_request", (event, ctx) => {
    return addWebSearchToPayload(event.payload, ctx.model?.api);
  });

  pi.on("before_agent_start", (event, ctx) => {
    if (!ctx.model || !SUPPORTED_SEARCH_APIS.has(ctx.model.api)) {
      delete event.systemPromptOptions.sections.web_search;
      return;
    }
    event.systemPromptOptions.sections.web_search = SEARCH_INSTRUCTIONS;
  });

  pi.on("turn_start", () => {
    collector = createMetadataCollector();
  });

  // The installed SDK calls this provider_event; stock v0.99 calls it
  // provider_stream_event. Register both notification shapes for the upgrade.
  type ProviderNotification = { data: unknown } | { event: { payload: unknown } };
  const onProviderEvent = pi.on.bind(pi) as (
    name: "provider_event" | "provider_stream_event",
    handler: (event: ProviderNotification) => void,
  ) => unknown;
  const observe = (event: ProviderNotification) => {
    collector.observe("data" in event ? event.data : event.event.payload);
  };
  onProviderEvent("provider_event", observe);
  onProviderEvent("provider_stream_event", observe);

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
