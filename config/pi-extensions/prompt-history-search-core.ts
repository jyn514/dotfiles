export interface PromptHistoryEntry {
  text: string;
  timestamp?: number;
}

interface TextContent {
  type: "text";
  text: string;
}

interface UserMessageEntry {
  type: "message";
  message: {
    role: "user";
    content: string | Array<TextContent | { type: string }>;
    timestamp?: number;
  };
}

function isUserMessageEntry(entry: unknown): entry is UserMessageEntry {
  if (!entry || typeof entry !== "object") return false;
  const candidate = entry as { type?: unknown; message?: { role?: unknown } };
  return candidate.type === "message" && candidate.message?.role === "user";
}

function messageText(content: UserMessageEntry["message"]["content"]): string {
  if (typeof content === "string") return content.trim();
  return content
    .filter((block): block is TextContent => block.type === "text" && "text" in block)
    .map((block) => block.text)
    .join("\n")
    .trim();
}

export function collectPromptHistory(entries: readonly unknown[]): PromptHistoryEntry[] {
  const seen = new Set<string>();
  const prompts: PromptHistoryEntry[] = [];

  for (let index = entries.length - 1; index >= 0; index--) {
    const entry = entries[index];
    if (!isUserMessageEntry(entry)) continue;
    const text = messageText(entry.message.content);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    prompts.push({ text, timestamp: entry.message.timestamp });
  }

  return prompts;
}

export function mergePromptHistories(
  histories: readonly (readonly PromptHistoryEntry[])[],
): PromptHistoryEntry[] {
  const newestByText = new Map<string, PromptHistoryEntry>();

  for (const history of histories) {
    for (const prompt of history) {
      const existing = newestByText.get(prompt.text);
      if (!existing || (prompt.timestamp ?? 0) > (existing.timestamp ?? 0)) {
        newestByText.set(prompt.text, prompt);
      }
    }
  }

  return [...newestByText.values()].sort(
    (left, right) => (right.timestamp ?? 0) - (left.timestamp ?? 0),
  );
}

export function searchPromptHistory(
  prompts: readonly PromptHistoryEntry[],
  query: string,
): PromptHistoryEntry[] {
  const terms = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [...prompts];

  return prompts.filter(({ text }) => {
    const searchable = text.toLocaleLowerCase();
    return terms.every((term) => searchable.includes(term));
  });
}
