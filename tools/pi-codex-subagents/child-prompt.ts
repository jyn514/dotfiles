import * as fs from "node:fs";
import * as path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

export const PACKAGE_BASENAME = "pi-codex-subagents";
export const SUBAGENT_DIR = path.join(getAgentDir(), PACKAGE_BASENAME);
const CHILD_PROMPT_PATH = path.join(SUBAGENT_DIR, "SYSTEM.md");
const DEFAULT_SUBAGENT_SYSTEM_PROMPT = "You are a subagent working for a main agent. Work only on the assigned task and follow its scope precisely.";

export function ensureChildPromptFile(): void {
  if (fs.existsSync(CHILD_PROMPT_PATH)) return;
  fs.mkdirSync(SUBAGENT_DIR, { recursive: true });
  try {
    fs.writeFileSync(CHILD_PROMPT_PATH, DEFAULT_SUBAGENT_SYSTEM_PROMPT, { flag: "wx", mode: 0o600 });
  } catch (error: any) {
    if (error?.code !== "EEXIST") throw error;
  }
}

/** Validate before task admission and helper startup; existing role files are never overwritten. */
export function readChildPrompt(): { path: string; content: string } {
  ensureChildPromptFile();
  const content = fs.readFileSync(CHILD_PROMPT_PATH, "utf8");
  if (!content.trim()) throw new Error(`Subagent system prompt is empty: ${CHILD_PROMPT_PATH}`);
  return { path: CHILD_PROMPT_PATH, content };
}
