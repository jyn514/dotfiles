import { randomUUID } from "node:crypto";
import { realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// Installed entrypoints are symlinks; resolve the source checkout, not ~/.pi.
export const COMPACTION_INSTRUCTIONS = resolve(
  dirname(realpathSync(fileURLToPath(import.meta.url))),
  "compaction.md",
);

export function checkpointText(entry: { summary: string; details?: unknown }): string {
  const length = (entry.details as { checkpointLength?: number } | undefined)?.checkpointLength;
  // The saved offset separates generated prose from caller-produced appendices.
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

const REPOSITORY_STATE_LIMIT = 1536;
type RepositoryState = {
  cwd: string;
  capturedAt: string;
  state: "observed" | "unknown";
} & (ExecResult | { error: string });

function repositoryStateView(state: RepositoryState) {
  if (JSON.stringify(state, null, 2).length <= REPOSITORY_STATE_LIMIT) return state;

  // Keep both ends (jj puts revision IDs last), without interpreting status lines.
  // Bound the serialized text too: JSON escaping can multiply output length.
  for (let limit = 1024; ; limit = Math.floor(limit / 2)) {
    const visible = Object.fromEntries(Object.entries(state).map(([key, value]) => {
      if (typeof value !== "string" || value.length <= limit) return [key, value];
      const half = Math.floor(limit / 2);
      return [key, `${value.slice(0, half)}\n[${value.length - 2 * half} characters omitted]\n${half ? value.slice(-half) : ""}`];
    }));
    const view = { ...visible, truncated: true };
    if (JSON.stringify(view, null, 2).length <= REPOSITORY_STATE_LIMIT) return view;
  }
}

export async function captureCheckpoint(
  pi: Pick<ExtensionAPI, "exec">,
  ctx: Pick<ExtensionContext, "cwd" | "sessionManager">,
  checkpoint: string,
  signal: AbortSignal,
  files: { readFiles?: string[]; modifiedFiles?: string[] } = {},
) {
  signal.throwIfAborted();
  // Pi has not assigned the compaction entry ID yet. Locate raw captures without
  // making recovery depend on summary prose or a generated timestamp.
  const captureId = randomUUID();
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
  const capturedContext = {
    repository: repositoryStateView(repositoryState),
    ...(files.modifiedFiles ? { recordedEditWriteTargets: files.modifiedFiles.length } : {}),
    recovery: {
      sessionId: ctx.sessionManager.getSessionId(),
      sessionFile: ctx.sessionManager.getSessionFile() ?? null,
      captureId,
    },
  };
  return {
    summary: `${checkpoint}\n\n## Captured context (caller-preserved)\n\nStatus is a snapshot; recorded targets include failed attempts and committed work.\nNeither establishes authorship, commit coverage, or completion.\nFor persisted sessions, recover full records from the raw compaction entry whose \`details.captureId\` matches \`recovery.captureId\`.\nIf the path differs here, find the JSONL filename containing \`recovery.sessionId\` under this environment's Pi session root.\n\`read_session\` omits these capture details.\n\n${JSON.stringify(capturedContext, null, 2)}`,
    details: { ...files, checkpointLength: checkpoint.length, repositoryState, captureId },
  };
}
