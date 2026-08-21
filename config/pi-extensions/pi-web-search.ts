import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { formatWebSearchResult, runNativeWebSearch } from "./pi-web-search-core";

export default function webSearch(pi: ExtensionAPI) {
  pi.registerTool({
    name: "web_search",
    label: "Web Search",
    description: "Search the web with the active model's native search API and return an answer with cited sources.",
    promptSnippet: "Search the web using the active model's native search capability",
    promptGuidelines: [
      "Use web_search for current facts, recent events, or information that requires external sources.",
    ],
    parameters: Type.Object({
      query: Type.String({ description: "Question or search query" }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const model = ctx.model;
      if (!model) throw new Error("No active model");

      const result = await runNativeWebSearch(
        model,
        params.query,
        signal,
        (context, options) => ctx.modelRegistry.complete(model, context, options),
      );

      const retrievedAt = new Date().toISOString();
      return {
        content: [{
          type: "text",
          text: formatWebSearchResult({
            query: params.query,
            answer: result.answer,
            retrievedAt,
            sources: result.sources,
            searches: result.searches,
          }),
        }],
        details: {
          query: params.query,
          retrievedAt,
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
