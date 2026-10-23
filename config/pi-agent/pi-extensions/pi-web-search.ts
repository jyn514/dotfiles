import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  addWebSearchToPayload,
  appendWebSearchSources,
  formatWebSearchActivity,
  createMetadataCollector,
  linkWebSearchCitations,
  SUPPORTED_SEARCH_APIS,
} from "./pi-web-search-core";

const SEARCH_INSTRUCTIONS = `Web search is available through the active model provider.
Use it for current facts, recent events, or information requiring external sources.
Search results and snippets may lag behind origin sites. For claims about what is latest or current, verify against a live first-party page, feed, or source repository instead of relying only on result ordering or snippets.
Honor any domain, date-range, result-count, or primary-source constraints in the user's request.
Web activity messages record provider-reported operations, not page contents or proof of correct interpretation. An absent activity record does not prove that no retrieval happened.`;

export default function webSearch(pi: ExtensionAPI) {
  let collector = createMetadataCollector();

  function clearWidget(ctx: ExtensionContext) {
    if (ctx.mode === "tui") ctx.ui.setWidget("web-activity", undefined);
  }

  function updateWidget(ctx: ExtensionContext) {
    if (ctx.mode !== "tui") return;
    const { activities } = collector.metadata;
    const activity = formatWebSearchActivity(activities);
    if (!activity) return;
    const lines = activity.split("\n").map((line, index) => {
      const status = activities[index - 1]?.status;
      const color = status === "completed" ? "success"
        : status === "failed" || status === "incomplete" ? "error" : "muted";
      return ctx.ui.theme.fg(color, line);
    });
    ctx.ui.setWidget("web-activity", lines, { placement: "aboveEditor" });
  }

  pi.on("agent_end", (_event, ctx) => clearWidget(ctx));
  pi.on("session_start", (_event, ctx) => clearWidget(ctx));
  pi.on("session_shutdown", (_event, ctx) => clearWidget(ctx));

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

  pi.on("turn_start", (_event, ctx) => {
    collector = createMetadataCollector();
    clearWidget(ctx);
  });

  // The installed SDK calls this provider_event; stock v0.99 calls it
  // provider_stream_event. Register both notification shapes for the upgrade.
  type ProviderNotification = { data: unknown } | { event: { payload: unknown } };
  const onProviderEvent = pi.on.bind(pi) as (
    name: "provider_event" | "provider_stream_event",
    handler: (event: ProviderNotification, ctx: ExtensionContext) => void,
  ) => unknown;
  const observe = (event: ProviderNotification, ctx: ExtensionContext) => {
    collector.observe("data" in event ? event.data : event.event.payload);
    updateWidget(ctx);
  };
  onProviderEvent("provider_event", observe);
  onProviderEvent("provider_stream_event", observe);

  pi.on("message_end", (event, ctx) => {
    if (event.message.role !== "assistant") return;
    clearWidget(ctx);
    const { sources, annotatedTexts, activities } = collector.metadata;
    const activity = formatWebSearchActivity(activities);
    if (activity) {
      pi.sendMessage({ customType: "web-activity", content: activity, display: true }, { triggerTurn: false });
    }
    if (sources.length === 0) return;
    return {
      message: {
        ...event.message,
        content: appendWebSearchSources(linkWebSearchCitations(event.message.content, annotatedTexts), sources),
      },
    };
  });
}
