import * as piAI from "@earendil-works/pi-ai";
import { estimateTokens, type ContextEditEntryDraft, type ExtensionContext, type TurnEndEvent } from "@earendil-works/pi-coding-agent";

/** Propose recoverable tool-body replacements without persisting them.
 * Only results preceding the current assistant response are eligible: the model
 * has seen them, but has not yet seen the current batch's tool results.
 * Callers own threshold policy and append the proposal at the turn boundary.
 */
export function toolOutputPruning(event: TurnEndEvent, ctx: ExtensionContext) {
  if (!ctx.sessionManager.getSessionFile()) return;
  const branch = ctx.sessionManager.getBranch();
  const currentIndex = branch.findIndex(entry => entry.id === event.messageEntryId);
  if (currentIndex < 0) return;
  const older = new Set(branch.slice(0, currentIndex).map(entry => entry.id));
  const { contextMessages, llmMessages, contextEntries, pendingMessages } = event.context;
  const system = piAI.getCurrentSystemMessage(llmMessages);
  const tokensBefore = (system ? estimateTokens(system) : 0) + contextMessages
    .filter(message => message.role !== "system")
    .reduce((total, message) => total + estimateTokens(message), 0);
  const edits: ContextEditEntryDraft[] = [];
  let tokensAfter = tokensBefore + pendingMessages.reduce((total, message) => total + estimateTokens(message), 0);
  for (const { sourceEntry, messages } of contextEntries) {
    if (!older.has(sourceEntry.id) || sourceEntry.type !== "message" || sourceEntry.message.role !== "toolResult") continue;
    const message = messages.find(message => message.role === "toolResult");
    if (!message) continue;
    const content = [{ type: "text" as const,
      text: `[Output omitted. Recover with read_session aroundEntryId: ${JSON.stringify(sourceEntry.id)}.]` }];
    const saved = estimateTokens(message) - estimateTokens({ ...message, content });
    if (saved <= 0) continue;
    edits.push({ type: "context_edit", targetId: sourceEntry.id, replacement: { content } });
    tokensAfter -= saved;
  }
  return { edits, tokensBefore, tokensAfter };
}
