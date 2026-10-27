import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  convertToLlm,
  serializeConversation,
  type ExtensionAPI,
  type SessionBeforeCompactEvent,
} from "@earendil-works/pi-coding-agent";

import { captureCheckpoint, checkpointText, COMPACTION_INSTRUCTIONS, requireCheckpointHeader } from "./checkpoint-capture.ts";

export const COMPACTION_MODEL = {
  provider: "openai",
  id: "gpt-6-luna",
} as const;

function previousCompaction(event: SessionBeforeCompactEvent) {
  const entry = event.branchEntries.findLast((entry) => entry.type === "compaction");
  return entry?.type === "compaction" && entry.summary === event.preparation.previousSummary ? entry : undefined;
}

function previousCheckpoint(event: SessionBeforeCompactEvent): string | undefined {
  const entry = previousCompaction(event);
  return entry ? checkpointText(entry) : event.preparation.previousSummary;
}

export default function lunaCompaction(pi: ExtensionAPI): void {
  pi.on("session_before_compact", async (event, ctx) => {
    const { preparation, signal } = event;
    try {
      const instructions = readFileSync(COMPACTION_INSTRUCTIONS, "utf8");
      const conversation = serializeConversation(convertToLlm([
        ...preparation.messagesToSummarize,
        ...preparation.turnPrefixMessages,
      ]));
      const previous = previousCheckpoint(event);
      const prompt = [
        previous ? `<previous-checkpoint>\n${previous}\n</previous-checkpoint>` : "",
        `<conversation>\n${conversation}\n</conversation>`,
        event.customInstructions ? `Additional compaction instructions:\n${event.customInstructions}` : "",
      ].filter(Boolean).join("\n\n");
      const luna = ctx.modelRegistry.find(COMPACTION_MODEL.provider, COMPACTION_MODEL.id);
      const models = luna ? [luna] : [];
      const active = ctx.model;
      if (active && (!luna || active.provider !== luna.provider || active.id !== luna.id)) {
        models.push(active);
      }
      let checkpoint: string | undefined;
      let usage;
      for (const [index, model] of models.entries()) {
        try {
          signal.throwIfAborted();
          const response = await ctx.modelRegistry.complete(model, {
            systemPrompt: instructions,
            messages: [{ role: "user", content: [{ type: "text", text: prompt }], timestamp: Date.now() }],
          }, {
            maxTokens: Math.min(Math.floor(0.8 * preparation.settings.reserveTokens), model.maxTokens > 0 ? model.maxTokens : Infinity),
            signal,
            cacheRetention: "none",
            sessionId: randomUUID(),
            reasoningEffort: "low",
          });
          signal.throwIfAborted();
          if (["error", "length", "aborted"].includes(response.stopReason)) {
            throw new Error(response.errorMessage || `Compaction ended with ${response.stopReason}`);
          }
          if (response.content.some((block) => block.type === "toolCall")) {
            throw new Error("Compaction attempted to call a tool");
          }
          const text = response.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
          requireCheckpointHeader(text);
          checkpoint = text;
          usage = response.usage;
          break;
        } catch (error) {
          if (signal.aborted || index === models.length - 1) throw error;
          ctx.ui.notify(`Luna compaction failed; using the active model: ${error instanceof Error ? error.message : String(error)}`, "warning");
        }
      }
      if (checkpoint === undefined) throw new Error("No compaction model is available");

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
