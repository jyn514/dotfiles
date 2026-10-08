import { randomUUID } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  convertToLlm,
  serializeConversation,
  type ExecResult,
  type ExtensionAPI,
  type SessionBeforeCompactEvent,
} from "@earendil-works/pi-coding-agent";

export const COMPACTION_MODEL = {
  provider: "openai-codex",
  id: "gpt-5.6-luna",
} as const;

// Installed entrypoints are symlinks; resolve the source checkout, not ~/.pi.
export const COMPACTION_INSTRUCTIONS = resolve(
  dirname(realpathSync(fileURLToPath(import.meta.url))),
  "compaction.md",
);

export function checkpointText(entry: { summary: string; details?: unknown }): string {
  const length = (entry.details as { checkpointLength?: number } | undefined)?.checkpointLength;
  // The saved offset separates generated prose from the caller's status block.
  return typeof length === "number" && Number.isSafeInteger(length) && length > 0 && length <= entry.summary.length
    ? entry.summary.slice(0, length)
    : entry.summary;
}

export function requireCheckpointHeader(text: string): void {
  if (!text.trim()) throw new Error("Compaction summary was empty");
  if (!/^#{1,6}[ \t]+Objective and authority[ \t]*\r?$/m.test(text)) {
    throw new Error("Compaction summary is missing the Objective and authority header");
  }
}

const REPOSITORY_STATE_LIMIT = 8192;
type RepositoryState = {
  cwd: string;
  capturedAt: string;
  state: "observed" | "unknown";
} & (ExecResult | { error: string });

function repositoryStateText(state: RepositoryState): string {
  const full = JSON.stringify(state, null, 2);
  if (full.length <= REPOSITORY_STATE_LIMIT) return full;

  // Keep both ends (jj puts revision IDs last), without interpreting status lines.
  // Bound the serialized text too: JSON escaping can multiply output length.
  for (let limit = 1024; ; limit = Math.floor(limit / 2)) {
    const visible = Object.fromEntries(Object.entries(state).map(([key, value]) => {
      if (typeof value !== "string" || value.length <= limit) return [key, value];
      const half = Math.floor(limit / 2);
      return [key, `${value.slice(0, half)}\n[${value.length - 2 * half} characters omitted]\n${half ? value.slice(-half) : ""}`];
    }));
    const text = JSON.stringify({
      ...visible,
      truncated: true,
      fullCapture: "Saved compaction entry details.repositoryState",
    }, null, 2);
    if (text.length <= REPOSITORY_STATE_LIMIT) return text;
  }
}

function previousCheckpoint(event: SessionBeforeCompactEvent): string | undefined {
  const previous = event.preparation.previousSummary;
  const entry = event.branchEntries.findLast((entry) => entry.type === "compaction");
  return previous && entry?.type === "compaction" && entry.summary === previous ? checkpointText(entry) : previous;
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

      let repositoryState: RepositoryState;
      try {
        // Keep the subcommand first for the sandbox's jj wrapper.
        const result = await pi.exec("jj", ["status", "--no-pager", "--color=never"], {
          cwd: ctx.cwd,
          signal,
          timeout: 10_000,
        });
        repositoryState = {
          cwd: ctx.cwd,
          capturedAt: new Date().toISOString(),
          state: result.code === 0 && !result.killed ? "observed" : "unknown",
          ...result,
        };
      } catch (error) {
        repositoryState = {
          cwd: ctx.cwd,
          capturedAt: new Date().toISOString(),
          state: "unknown",
          error: error instanceof Error ? error.message : String(error),
        };
      }
      signal.throwIfAborted();
      const modified = new Set([...preparation.fileOps.edited, ...preparation.fileOps.written]);
      const modifiedFiles = [...modified].sort();
      const readFiles = [...preparation.fileOps.read].filter((file) => !modified.has(file)).sort();
      return {
        compaction: {
          summary: `${checkpoint}\n\n## Repository state (caller-captured after summary)\n\nAuthoritative for working-copy state at capture time only; later edits can invalidate it. This is not evidence of task completion.\n\n${repositoryStateText(repositoryState)}`,
          firstKeptEntryId: preparation.firstKeptEntryId,
          tokensBefore: preparation.tokensBefore,
          usage,
          details: { readFiles, modifiedFiles, checkpointLength: checkpoint.length, repositoryState },
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
