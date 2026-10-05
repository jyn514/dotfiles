import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";

export async function showSystemPrompt(ctx: ExtensionCommandContext): Promise<void> {
  if (ctx.mode !== "tui") {
    ctx.ui.notify("The system prompt viewer is available only in interactive mode", "warning");
    return;
  }

  await ctx.ui.editor(
    "Effective system prompt (edits are discarded)",
    ctx.getSystemPrompt(),
  );
}

export default function systemPrompt(pi: ExtensionAPI): void {
  pi.registerCommand("system-prompt", {
    description: "Show the effective system prompt",
    handler: async (_args, ctx) => showSystemPrompt(ctx),
  });
}
