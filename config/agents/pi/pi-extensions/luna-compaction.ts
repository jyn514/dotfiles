import { compact, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const COMPACTION_MODEL = {
  provider: "openai-codex",
  id: "gpt-5.6-luna",
} as const;

export default function lunaCompaction(pi: ExtensionAPI): void {
  pi.on("session_before_compact", async (event, ctx) => {
    const model = ctx.modelRegistry.find(
      COMPACTION_MODEL.provider,
      COMPACTION_MODEL.id,
    );
    if (!model) return;

    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
    if (!auth.ok) return;

    try {
      const result = await compact(
        event.preparation,
        model,
        auth.apiKey,
        auth.headers,
        event.customInstructions,
        event.signal,
        "low",
        undefined,
        auth.env,
      );
      return { compaction: result };
    } catch (error) {
      if (!event.signal.aborted) {
        ctx.ui.notify(
          `Luna compaction failed; using the active model: ${error instanceof Error ? error.message : String(error)}`,
          "warning",
        );
      }
      return;
    }
  });
}
