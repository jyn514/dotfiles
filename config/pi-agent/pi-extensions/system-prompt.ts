import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";

import {
  describeSystemPromptSnapshot, NO_PROMPT_CAPTURE, observeSystemPrompt,
  type SystemPromptSnapshot,
} from "./system-prompt-core.ts";

export async function showSystemPrompt(
  ctx: ExtensionCommandContext,
  snapshot: SystemPromptSnapshot | undefined,
): Promise<void> {
  if (ctx.mode !== "tui") {
    ctx.ui.notify("The system prompt viewer is available only in interactive mode", "warning");
    return;
  }

  if (!snapshot) {
    ctx.ui.notify(NO_PROMPT_CAPTURE, "info");
    return;
  }

  await ctx.ui.editor(
    "Last prepared system prompt (edits are discarded)",
    `${describeSystemPromptSnapshot(snapshot)}\n\n${snapshot.prompt}`,
  );
}

export default function systemPrompt(pi: ExtensionAPI): void {
  const capture = observeSystemPrompt(pi);
  pi.registerCommand("system-prompt", {
    description: "Show the last prepared system prompt",
    handler: async (_args, ctx) => showSystemPrompt(ctx, capture()),
  });
}
