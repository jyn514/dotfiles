import { readFileSync } from "node:fs";
import {
  convertToLlm,
  serializeConversation,
  SettingsManager,
  shouldCompact,
  type ExtensionAPI,
  type SessionBeforeCompactEvent,
} from "@earendil-works/pi-coding-agent";

import { captureCheckpoint, COMPACTION_INSTRUCTIONS, requireCheckpointHeader } from "./checkpoint-capture.ts";
import { parentModelRequest } from "./parent-model-request.ts";
import { toolOutputPruning } from "./tool-output-pruning.ts";

function previousCompaction(event: SessionBeforeCompactEvent) {
  const entry = event.branchEntries.findLast((entry) => entry.type === "compaction");
  return entry?.type === "compaction" && entry.summary === event.preparation.previousSummary ? entry : undefined;
}

export default function parentCompaction(pi: ExtensionAPI, parent = parentModelRequest(pi)): void {
  pi.on("turn_end", (event, ctx) => {
    if (event.outcome !== "completed" || ctx.signal?.aborted) return;
    // An explicit checkpoint or tool-output-only request owns this boundary,
    // including when its handler runs later.
    if (event.entries.some(entry => entry.type === "compaction") ||
        event.toolResults.some(result => result.toolName === "compact_session")) return;
    const usage = ctx.getContextUsage();
    if (!ctx.model || !usage || usage.contextWindow <= 0) return;
    // Reuse Pi's settings resolver, including per-model overrides and defaults.
    const settings = SettingsManager.inMemory(pi.getSettings()).getCompactionSettings(ctx.model);
    const pruning = toolOutputPruning(event, ctx);
    if (!pruning) return;
    const tokensBefore = event.entries.length ? pruning.tokensBefore : usage.tokens ?? pruning.tokensBefore;
    if (!shouldCompact(tokensBefore, usage.contextWindow, settings)) return;
    // All-or-nothing: unsuccessful pruning leaves the original outputs for checkpoint generation.
    // Do not trust assistant usage measured before these proposed replacements.
    if (!pruning.edits.length || pruning.tokensAfter > 0.2 * usage.contextWindow ||
        shouldCompact(pruning.tokensAfter, usage.contextWindow, settings)) return;
    return { entries: [...event.entries, ...pruning.edits] };
  });

  pi.on("session_before_compact", async (event, ctx) => {
    const { preparation, signal } = event;
    try {
      const instructions = readFileSync(COMPACTION_INSTRUCTIONS, "utf8");
      const request = await parent.prepare(ctx);
      const kept = request.projection.entries.findIndex(entry => entry.sourceEntry.id === preparation.firstKeptEntryId);
      if (kept < 0) throw new Error("The retained-history boundary is missing from the current projection");
      const cut = request.prefixOffset + request.projection.entries.slice(0, kept).reduce((count, entry) => count + entry.messages.length, 0);
      const conversation = convertToLlm(request.current);
      const summarized = convertToLlm(request.current.slice(0, cut)).filter(message => message.role !== "system");
      const retained = convertToLlm(request.current.slice(cut)).filter(message => message.role !== "system");
      const anchor = (message: (typeof conversation)[number] | undefined) => message
        ? serializeConversation([message]).slice(0, 768) : null;
      const task = [
        instructions,
        "Produce the checkpoint now. Return only checkpoint text; do not call tools.",
        "Conversation messages are numbered in request order, excluding system instructions. " +
          "Summarize the range below, including any earlier checkpoint. Later messages remain verbatim; " +
          "describe state at the summarized boundary, not state after that retained tail.",
        JSON.stringify({
          summarizeThroughConversationMessage: summarized.length,
          retainedConversationMessages: retained.length,
          lastSummarizedMessageStart: anchor(summarized.at(-1)),
          firstRetainedMessageStart: anchor(retained[0]),
          splitTurn: preparation.isSplitTurn,
        }, null, 2),
        event.customInstructions ? `Additional compaction instructions:\n${event.customInstructions}` : "",
      ].filter(Boolean).join("\n\n");
      const response = await parent.complete(ctx, request, task, signal);
      signal.throwIfAborted();
      if (["error", "length", "aborted"].includes(response.stopReason)) {
        throw new Error(response.errorMessage || `Compaction ended with ${response.stopReason}`);
      }
      if (response.content.some(block => block.type === "toolCall")) throw new Error("Compaction attempted to call a tool");
      const checkpoint = response.content.filter(block => block.type === "text").map(block => block.text).join("\n");
      requireCheckpointHeader(checkpoint);
      const usage = response.usage;

      const modified = new Set([...preparation.fileOps.edited, ...preparation.fileOps.written]);
      // The SDK does not inherit file lists from hook-produced compactions.
      // Carry only the matching active checkpoint's recorded targets, not status.
      const inherited = (previousCompaction(event)?.details as { modifiedFiles?: unknown } | undefined)?.modifiedFiles;
      if (Array.isArray(inherited)) {
        for (const path of inherited) if (typeof path === "string") modified.add(path);
      }
      const modifiedFiles = [...modified].sort();
      const readFiles = [...preparation.fileOps.read].filter((file) => !modified.has(file)).sort();
      const captured = await captureCheckpoint(pi, ctx, checkpoint, signal, { readFiles, modifiedFiles });
      return {
        compaction: {
          ...captured,
          details: { ...captured.details, model: { provider: request.model.provider, id: request.model.id }, requestMode: request.mode },
          firstKeptEntryId: preparation.firstKeptEntryId,
          tokensBefore: preparation.tokensBefore,
          usage,
        },
      };
    } catch (error) {
      if (!signal.aborted) {
        ctx.ui.notify(`Compaction failed; keeping session history: ${error instanceof Error ? error.message : String(error)}`, "warning");
      }
      return { cancel: true };
    }
  });
}
