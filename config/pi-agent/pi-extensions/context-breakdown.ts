import type {
  BuildSystemPromptOptions,
  ExtensionAPI,
  ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import {
  estimateTokens,
  sessionEntryToContextMessages,
} from "@earendil-works/pi-coding-agent";

import {
  describeSystemPromptSnapshot, NO_PROMPT_CAPTURE, observeSystemPrompt,
  type SystemPromptSnapshot,
} from "./system-prompt-core.ts";

type BreakdownRow = {
  label: string;
  tokens: number;
};

type ToolSchema = {
  name: string;
  description: string;
  parameters: unknown;
};

type ContextUsage = {
  tokens: number | null;
  contextWindow: number;
  percent: number | null;
};

type Message = ReturnType<typeof sessionEntryToContextMessages>[number];

export type ContextBreakdown = {
  promptRows: BreakdownRow[];
  promptTotal: number;
  conversationRows: BreakdownRow[];
  conversationTotal: number;
  toolRows: BreakdownRow[];
  toolTotal: number;
  accountingDifference: number | null;
  usage: ContextUsage | undefined;
};

const IMAGE_CHARS = 4800;

function estimateText(text: string): number {
  return Math.ceil(text.length / 4);
}

function contentChars(content: unknown): number {
  if (typeof content === "string") return content.length;
  if (!Array.isArray(content)) return 0;

  return content.reduce((total, block) => {
    if (!block || typeof block !== "object") return total;
    if ("type" in block && block.type === "image") return total + IMAGE_CHARS;
    if ("text" in block && typeof block.text === "string") return total + block.text.length;
    return total;
  }, 0);
}

function addChars(categories: Map<string, number>, label: string, chars: number): void {
  if (chars <= 0) return;
  categories.set(label, (categories.get(label) ?? 0) + chars);
}

function rowsFromChars(categories: Map<string, number>): BreakdownRow[] {
  return [...categories].map(([label, chars]) => ({
    label,
    tokens: Math.ceil(chars / 4),
  }));
}

function skillCatalogChars(options: BuildSystemPromptOptions): number {
  const selectedTools = options.selectedTools ?? ["read", "bash", "edit", "write"];
  if (!selectedTools.includes("read")) return 0;

  return (options.skills ?? [])
    .filter((skill) => !skill.disableModelInvocation)
    .reduce(
      (total, skill) => total + skill.name.length + skill.description.length + skill.filePath.length,
      0,
    );
}

function reconcileRows(
  rows: BreakdownRow[],
  total: number,
  remainderLabel: string,
): BreakdownRow[] {
  const attributed = rows.reduce((sum, row) => sum + row.tokens, 0);
  if (attributed < total) {
    return [{ label: remainderLabel, tokens: total - attributed }, ...rows];
  }
  if (attributed === total || rows.length === 0) return rows;

  // Per-source estimates round independently. Remove that rounding excess from
  // the largest rows rather than displaying impossible negative token usage.
  let excess = attributed - total;
  const reconciled = rows.map((row) => ({ ...row }));
  for (const row of [...reconciled].sort((left, right) => right.tokens - left.tokens)) {
    const reduction = Math.min(row.tokens, excess);
    row.tokens -= reduction;
    excess -= reduction;
    if (excess === 0) break;
  }
  return reconciled.filter((row) => row.tokens > 0);
}

function promptBreakdown(
  effectivePrompt: string,
  options: BuildSystemPromptOptions,
): { rows: BreakdownRow[]; total: number } {
  const total = estimateText(effectivePrompt);
  const rows: BreakdownRow[] = [];

  if (options.customPrompt) {
    rows.push({ label: "Custom system prompt", tokens: estimateText(options.customPrompt) });
  }
  if (options.appendSystemPrompt) {
    rows.push({ label: "Appended system prompt", tokens: estimateText(options.appendSystemPrompt) });
  }
  for (const file of options.contextFiles ?? []) {
    rows.push({ label: `Context: ${file.path}`, tokens: estimateText(file.content) });
  }

  const skills = skillCatalogChars(options);
  if (skills > 0) {
    rows.push({ label: "Skills catalog metadata", tokens: Math.ceil(skills / 4) });
  }

  if (!options.customPrompt) {
    const selectedTools = new Set(options.selectedTools ?? ["read", "bash", "edit", "write"]);
    const selectedSnippets = Object.entries(options.toolSnippets ?? {})
      .filter(([name]) => selectedTools.has(name))
      .map(([, snippet]) => snippet);
    const toolMetadata = [
      ...selectedSnippets,
      ...(options.promptGuidelines ?? []),
    ].join("\n");
    if (toolMetadata) {
      rows.push({ label: "Tool prompt metadata", tokens: estimateText(toolMetadata) });
    }
  }

  return {
    rows: reconcileRows(
      rows,
      total,
      options.customPrompt ? "System prompt structure/remainder" : "Base system prompt/remainder",
    ),
    total,
  };
}

function conversationBreakdown(messages: Message[]): { rows: BreakdownRow[]; total: number } {
  const categories = new Map<string, number>();
  let total = 0;

  for (const message of messages) {
    total += estimateTokens(message);

    switch (message.role) {
      case "user":
        addChars(categories, "User messages", contentChars(message.content));
        break;
      case "assistant":
        for (const block of message.content) {
          if (block.type === "text") addChars(categories, "Assistant text", block.text.length);
          else if (block.type === "thinking") addChars(categories, "Assistant reasoning", block.thinking.length);
          else if (block.type === "toolCall") {
            addChars(categories, "Tool calls", block.name.length + JSON.stringify(block.arguments).length);
          }
        }
        break;
      case "toolResult":
        addChars(categories, "Tool results", contentChars(message.content));
        break;
      case "compactionSummary":
        addChars(categories, "Compaction summaries", message.summary.length);
        break;
      case "branchSummary":
        addChars(categories, "Branch summaries", message.summary.length);
        break;
      case "bashExecution":
        addChars(categories, "Bash execution messages", message.command.length + message.output.length);
        break;
      case "custom":
        addChars(categories, "Extension messages", contentChars(message.content));
        break;
    }
  }

  return {
    rows: reconcileRows(rowsFromChars(categories), total, "Conversation estimation remainder"),
    total,
  };
}

function toolBreakdown(tools: ToolSchema[]): { rows: BreakdownRow[]; total: number } {
  const rows = tools.map((tool) => ({
    label: `Tool schema: ${tool.name}`,
    tokens: estimateText(JSON.stringify({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    })),
  }));
  return { rows, total: rows.reduce((sum, row) => sum + row.tokens, 0) };
}

export function buildContextBreakdown(
  effectivePrompt: string,
  options: BuildSystemPromptOptions,
  messages: Message[],
  tools: ToolSchema[],
  usage: ContextUsage | undefined,
): ContextBreakdown {
  const prompt = promptBreakdown(effectivePrompt, options);
  const conversation = conversationBreakdown(messages);
  const toolSchemas = toolBreakdown(tools);
  const estimatedTotal = prompt.total + conversation.total + toolSchemas.total;

  return {
    promptRows: prompt.rows,
    promptTotal: prompt.total,
    conversationRows: conversation.rows,
    conversationTotal: conversation.total,
    toolRows: toolSchemas.rows,
    toolTotal: toolSchemas.total,
    accountingDifference: usage?.tokens == null ? null : usage.tokens - estimatedTotal,
    usage,
  };
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function formatRows(rows: BreakdownRow[], contextWindow: number | undefined): string[] {
  const labelWidth = Math.max(24, ...rows.map((row) => row.label.length));
  return rows.map((row) => {
    const percent = contextWindow && contextWindow > 0
      ? `${((row.tokens / contextWindow) * 100).toFixed(1)}%`
      : "—";
    return `${row.label.padEnd(labelWidth)}  ${formatNumber(row.tokens).padStart(9)}  ${percent.padStart(7)}`;
  });
}

export function formatContextBreakdown(breakdown: ContextBreakdown): string {
  const window = breakdown.usage?.contextWindow;
  const lines = [
    "Context breakdown — estimated",
    "",
    "Persisted session state and the last prepared Pi system prompt are measured locally.",
    "Prompt source attribution uses current base inputs; extension additions appear in the remainder.",
    "Extension context rewrites, provider payload rewrites, and provider tool schemas are not attributed.",
    "",
    "System prompt",
    ...formatRows(breakdown.promptRows, window),
    `Prompt subtotal: ${formatNumber(breakdown.promptTotal)}`,
    "",
    "Persisted conversation",
    ...formatRows(breakdown.conversationRows, window),
    `Conversation subtotal: ${formatNumber(breakdown.conversationTotal)}`,
    "",
    "Active tool schemas",
    ...formatRows(breakdown.toolRows, window),
    `Tool schema subtotal: ${formatNumber(breakdown.toolTotal)}`,
    "",
  ];

  if (breakdown.usage?.tokens == null) {
    lines.push(
      "Pi context total: unavailable until a post-compaction response provides fresh usage",
    );
  } else {
    const percent = breakdown.usage.percent == null ? "" : ` (${breakdown.usage.percent.toFixed(1)}%)`;
    lines.push(
      `Estimated system prompt: ${formatNumber(breakdown.promptTotal)}`,
      `Estimated persisted conversation: ${formatNumber(breakdown.conversationTotal)}`,
      `Estimated active tool schemas: ${formatNumber(breakdown.toolTotal)}`,
      `Accounting/rewrite difference: ${formatNumber(breakdown.accountingDifference ?? 0)}`,
      `Pi context total: ${formatNumber(breakdown.usage.tokens)} / ${formatNumber(
        breakdown.usage.contextWindow,
      )}${percent}`,
    );
  }

  return lines.join("\n");
}

export async function showContextBreakdown(
  ctx: ExtensionCommandContext,
  tools: ToolSchema[],
  snapshot: SystemPromptSnapshot | undefined,
): Promise<void> {
  if (ctx.mode !== "tui") {
    ctx.ui.notify("The context breakdown is available only in interactive mode", "warning");
    return;
  }

  if (!snapshot) {
    ctx.ui.notify(NO_PROMPT_CAPTURE, "info");
    return;
  }

  const messages = ctx.sessionManager
    .buildContextEntries()
    .flatMap(sessionEntryToContextMessages);
  const breakdown = buildContextBreakdown(
    snapshot.prompt,
    ctx.getSystemPromptOptions(),
    messages,
    tools,
    ctx.getContextUsage(),
  );

  await ctx.ui.editor(
    "Context breakdown (estimates; edits are discarded)",
    `${describeSystemPromptSnapshot(snapshot)}\n\n${formatContextBreakdown(breakdown)}`,
  );
}

export default function contextBreakdown(pi: ExtensionAPI): void {
  const capture = observeSystemPrompt(pi);
  pi.registerCommand("context-breakdown", {
    description: "Estimate current context usage by source",
    handler: async (_args, ctx) => {
      const active = new Set(pi.getActiveTools());
      const tools = pi.getAllTools().filter((tool) => active.has(tool.name));
      await showContextBreakdown(ctx, tools, capture());
    },
  });
}
