import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { formatWebSearchResult, runNativeWebSearch } from "./pi-web-search-core";

export default function webSearch(pi: ExtensionAPI) {
  pi.registerTool({
    name: "web_search",
    label: "Web Search",
    description: "Search the web with the active model's native search API and return structured results with cited sources.",
    promptSnippet: "Search the web using the active model's native search capability",
    promptGuidelines: [
      "Use web_search for current facts, recent events, or information that requires external sources.",
    ],
    parameters: Type.Object({
      query: Type.String({ description: "Question or search query" }),
      domains: Type.Optional(Type.Array(Type.String({
        pattern: "^(?:[a-zA-Z0-9-]+\\.)*[a-zA-Z0-9-]+$",
      }), {
        description: "Only use sources from these domains",
        maxItems: 10,
      })),
      startDate: Type.Optional(Type.String({
        description: "Earliest publication date, in YYYY-MM-DD format",
        pattern: "^\\d{4}-\\d{2}-\\d{2}$",
      })),
      endDate: Type.Optional(Type.String({
        description: "Latest publication date, in YYYY-MM-DD format",
        pattern: "^\\d{4}-\\d{2}-\\d{2}$",
      })),
      maxResults: Type.Optional(Type.Integer({
        description: "Maximum number of cited sources to return",
        minimum: 1,
        maximum: 20,
      })),
      primarySourcesOnly: Type.Optional(Type.Boolean({
        description: "Use only first-party or otherwise primary sources",
      })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const model = ctx.model;
      if (!model) throw new Error("No active model");

      const filters = {
        ...(params.domains ? { domains: params.domains } : {}),
        ...(params.startDate ? { startDate: params.startDate } : {}),
        ...(params.endDate ? { endDate: params.endDate } : {}),
        ...(params.maxResults ? { maxResults: params.maxResults } : {}),
        ...(params.primarySourcesOnly !== undefined ? { primarySourcesOnly: params.primarySourcesOnly } : {}),
      };
      const result = await runNativeWebSearch(
        model,
        params.query,
        signal,
        (context, options) => ctx.modelRegistry.complete(model, context, options),
        filters,
      );

      const retrievedAt = new Date().toISOString();
      return {
        content: [{
          type: "text",
          text: formatWebSearchResult({
            query: params.query,
            answer: result.answer,
            retrievedAt,
            ...(Object.keys(filters).length > 0 ? { filters } : {}),
            sources: result.sources,
            searches: result.searches,
          }),
        }],
        details: {
          query: params.query,
          retrievedAt,
          filters,
          provider: model.provider,
          model: model.id,
          sources: result.sources,
          searches: result.searches,
        },
        usage: result.usage,
      };
    },
  });
}
