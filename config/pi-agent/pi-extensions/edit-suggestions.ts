// Register native edit diagnostics without replacing Pi's execution or previews.
import {
  createEditToolDefinition,
  generateDiffString,
  type EditToolOptions,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { createEditSuggestionsTool as createSuggestedEdit } from "./edit-suggestions-core.ts";

/** Compose diagnostic-only edit behavior with the caller's operations and context. */
export function createEditSuggestionsTool(cwd: string, options?: EditToolOptions): ReturnType<typeof createEditToolDefinition> {
  return createSuggestedEdit({ createEditToolDefinition, generateDiffString }, cwd, options);
}

export default function editSuggestions(pi: ExtensionAPI) {
  // The guest worker owns its read snapshot; a host override cannot enrich it.
  if (process.env.CODEX_SANDBOX_TOOL_CONTAINER) return;
  pi.registerTool({
    ...createEditSuggestionsTool(process.cwd()),
    execute(id, input, signal, onUpdate, ctx) {
      return createEditSuggestionsTool(ctx.cwd, {
        contextLines: pi.getSettings().editContextLines,
      }).execute(id, input, signal, onUpdate, ctx);
    },
  });
}
