import { spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { readdir } from "node:fs/promises";
import { createInterface } from "node:readline";
import { join } from "node:path";

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

function promptFromLine(line: string): PromptHistoryEntry | undefined {
  if (!/"role"\s*:\s*"user"/.test(line)) return undefined;
  try {
    const entry: unknown = JSON.parse(line);
    if (!isUserMessageEntry(entry)) return undefined;
    const text = messageText(entry.message.content);
    return text ? { text, timestamp: entry.message.timestamp } : undefined;
  } catch {
    return undefined;
  }
}

export async function collectPromptHistoryFile(path: string): Promise<PromptHistoryEntry[]> {
  const prompts: PromptHistoryEntry[] = [];
  const lines = createInterface({
    input: createReadStream(path, { encoding: "utf8" }),
    crlfDelay: Infinity,
  });

  for await (const line of lines) {
    // User messages are uncommon in large session files. Avoid parsing tool output,
    // assistant responses, and other entries that cannot contribute to history.
    const prompt = promptFromLine(line);
    if (prompt) prompts.push(prompt);
  }

  return prompts;
}

export async function loadPromptHistoryWithRipgrep(
  sessionsDir: string,
  excludedPath?: string,
): Promise<PromptHistoryEntry[]> {
  return new Promise((resolve, reject) => {
    const child = spawn("rg", ["-0", "-H", "--fixed-strings", '"role":"user"', sessionsDir], {
      stdio: ["ignore", "pipe", "ignore"],
    });
    const prompts: PromptHistoryEntry[] = [];
    const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });

    lines.on("line", (line) => {
      const separator = line.indexOf("\0");
      if (separator < 0 || line.slice(0, separator) === excludedPath) return;
      const prompt = promptFromLine(line.slice(separator + 1));
      if (prompt) prompts.push(prompt);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0 || code === 1) resolve(mergePromptHistories([prompts]));
      else reject(new Error(`ripgrep exited with status ${code}`));
    });
  });
}

export async function listPromptHistoryFiles(sessionsDir: string): Promise<string[]> {
  const files: string[] = [];
  let projectDirs;
  try {
    projectDirs = await readdir(sessionsDir, { withFileTypes: true });
  } catch {
    return files;
  }

  for (const projectDir of projectDirs) {
    if (!projectDir.isDirectory() && !projectDir.isSymbolicLink()) continue;
    const dir = join(sessionsDir, projectDir.name);
    try {
      for (const name of await readdir(dir)) {
        if (name.endsWith(".jsonl")) files.push(join(dir, name));
      }
    } catch {
      // A disappearing or unreadable project directory does not invalidate the rest.
    }
  }
  return files;
}

export async function loadPromptHistoryFiles(
  paths: readonly string[],
  excludedPath?: string,
  concurrency = 8,
): Promise<PromptHistoryEntry[]> {
  const histories: PromptHistoryEntry[][] = [];
  let next = 0;

  async function worker(): Promise<void> {
    while (next < paths.length) {
      const path = paths[next++];
      if (path === excludedPath) continue;
      try {
        histories.push(await collectPromptHistoryFile(path));
      } catch {
        // Match Pi session discovery: unreadable files are skipped.
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, paths.length) }, worker));
  return mergePromptHistories(histories);
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
