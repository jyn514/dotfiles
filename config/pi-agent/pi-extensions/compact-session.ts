import type { CompactionEntryDraft, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { captureCheckpoint, COMPACTION_INSTRUCTIONS, requireCheckpointHeader } from "./checkpoint-capture.ts";
import { parsePiResourcePaths, rewritePiResourcePaths } from "./guest-tools-core.ts";
import { toolOutputPruning } from "./tool-output-pruning.ts";

type PendingCompaction = {
  sessionId: string;
  messageEntryId: string;
  toolCallId: string;
  signal: AbortSignal;
} & ({ mode: "checkpoint"; draft: CompactionEntryDraft } | { mode: "tool_output" });

function callingMessage(ctx: ExtensionContext, toolCallId: string) {
  const entry = ctx.sessionManager.getBranch().findLast(entry =>
    entry.type === "message" && entry.message.role === "assistant");
  if (entry?.type !== "message" || entry.message.role !== "assistant") {
    throw new Error("Call compact_session directly as the only tool call in an assistant message.");
  }
  const calls = entry.message.content.filter(block => block.type === "toolCall");
  if (calls.length !== 1 || calls[0].id !== toolCallId || calls[0].name !== "compact_session") {
    throw new Error("Call compact_session alone, after other tools have finished; session history was kept.");
  }
  return entry;
}

export default function compactSession(pi: ExtensionAPI): void {
  let pending: PendingCompaction | undefined;
  let lifetime = new AbortController();
  const reset = () => {
    pending = undefined;
    lifetime.abort();
    lifetime = new AbortController();
  };
  for (const event of ["session_start", "session_switch", "session_fork", "session_tree", "session_shutdown", "agent_settled"] as const) {
    pi.on(event, reset);
  }

  const instructionsPath = rewritePiResourcePaths(
    COMPACTION_INSTRUCTIONS,
    parsePiResourcePaths(process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS),
  );
  pi.registerTool({
    name: "compact_session",
    label: "Compact session",
    description: `Replace preceding conversation context with your own checkpoint, or pass tool_output_only: true without report to remove older tool-output bodies while keeping conversation messages. Both modes continue in the same session. Before preparing report, read ${instructionsPath}. Pass the checkpoint itself, not instructions for another summarizer. Call this tool alone, after other tools finish. History remains recoverable through read_session; checkpoint metadata or output markers supply recovery references.`,
    promptSnippet: "Replace conversation context with a checkpoint or remove only older tool-output bodies",
    parameters: Type.Object({
      report: Type.Optional(Type.String({ minLength: 1, description: "Checkpoint prepared using compaction.md, including an Objective and authority Markdown heading. Omit for tool_output_only." })),
      tool_output_only: Type.Optional(Type.Boolean({ description: "Remove only older tool-output bodies, without a checkpoint or summarizer. Raw history remains recoverable. Works below the automatic threshold; no 20% target is required. Ordinary automatic compaction still applies. Do not combine with report." })),
    }),
    async execute(toolCallId, { report, tool_output_only }, signal, _onUpdate, ctx) {
      if (tool_output_only && report !== undefined) throw new Error("Choose report or tool_output_only, not both.");
      const checkpoint = report ?? "";
      if (!tool_output_only) requireCheckpointHeader(checkpoint);
      signal.throwIfAborted();
      const message = callingMessage(ctx, toolCallId);
      const sessionId = ctx.sessionManager.getSessionId();
      if (pending) throw new Error("A compact_session request is already pending for this turn.");
      const captureSignal = AbortSignal.any([signal, lifetime.signal]);
      if (tool_output_only) {
        if (!ctx.sessionManager.getSessionFile()) throw new Error("Tool-output pruning requires a saved transcript for recovery.");
        pending = { mode: "tool_output", sessionId, messageEntryId: message.id, toolCallId, signal: captureSignal };
        return {
          content: [{ type: "text", text: "Tool-output pruning queued. Pi will replace eligible older output bodies with recovery markers after this result is saved, then continue. Conversation messages remain intact." }],
          details: { pending: true },
        };
      }
      const previous = ctx.sessionManager.getBranch().findLast(entry => entry.type === "compaction");
      const inherited = (previous?.type === "compaction" ? previous.details as { modifiedFiles?: unknown } : undefined)?.modifiedFiles;
      const modifiedFiles = Array.isArray(inherited)
        ? [...new Set(inherited.filter((path): path is string => typeof path === "string"))].sort()
        : [];
      // These are prior recorded targets, not a new inventory of intervening calls.
      const captured = await captureCheckpoint(pi, ctx, checkpoint, captureSignal,
        modifiedFiles.length ? { modifiedFiles } : {});
      captureSignal.throwIfAborted();
      if (ctx.sessionManager.getSessionId() !== sessionId || callingMessage(ctx, toolCallId).id !== message.id) {
        throw new Error("Session or branch changed during compact_session; session history was kept.");
      }
      pending = {
        mode: "checkpoint", sessionId, messageEntryId: message.id, toolCallId, signal: captureSignal,
        draft: { type: "compaction", ...captured, firstKeptEntryId: null },
      };
      return {
        content: [{ type: "text", text: "Checkpoint queued. Pi will replace context after this turn's tool result is saved, then continue from your report." }],
        details: { pending: true },
      };
    },
  });

  pi.on("turn_end", (event, ctx) => {
    const request = pending;
    pending = undefined;
    if (!request || request.signal.aborted || event.outcome !== "completed") return;
    if (ctx.sessionManager.getSessionId() !== request.sessionId || event.messageEntryId !== request.messageEntryId) return;
    const branch = ctx.sessionManager.getBranch();
    if (!branch.some(entry => entry.id === request.messageEntryId)) return;
    const resultIndex = event.toolResults.findIndex(result => result.toolCallId === request.toolCallId && !result.isError);
    if (resultIndex < 0 || !branch.some(entry => entry.id === event.toolResultEntryIds[resultIndex])) return;
    // Pi previews/validates the returned entries and owns persistence, context
    // projection, and queued-input ordering. Never edit agent messages directly.
    if (request.mode === "tool_output") {
      const pruning = toolOutputPruning(event, ctx);
      return { entries: [...event.entries, ...(pruning?.edits ?? [])], continue: true };
    }
    return { entries: [...event.entries, request.draft], continue: true };
  });
}
