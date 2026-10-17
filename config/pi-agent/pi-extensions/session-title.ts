import { open, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import {
  SessionManager,
  type ExtensionAPI,
  type SessionInfo,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export interface SessionTitleRequest {
  session: string;
  title: string;
}

export interface SessionTitleEdit {
  session: string;
  path: string;
  previousTitle?: string;
  title?: string;
}

export interface SessionTitleFailure {
  session: string;
  path: string;
  error: string;
}

export interface SessionTitleBatchResult {
  edits: SessionTitleEdit[];
  unchanged: SessionTitleEdit[];
  failure?: SessionTitleFailure;
}

export type SessionTitleLookup =
  | { found: true; title: string | undefined }
  | { found: false };

export function resolveSession(
  sessions: readonly SessionInfo[],
  reference: string,
): SessionInfo {
  const normalizedReference = resolve(reference);
  const matches = sessions.filter(
    (session) => session.id === reference || resolve(session.path) === normalizedReference,
  );

  if (matches.length === 0) {
    throw new Error(`No saved session has ID or path: ${reference}`);
  }
  if (matches.length > 1) {
    throw new Error(`Session reference is ambiguous: ${reference}`);
  }
  return matches[0];
}

export function sessionSearchRoot(): string {
  return process.env.PI_SESSION_SEARCH_ROOT ?? join(homedir(), ".pi/agent/sessions");
}

export function resolveReadSessionPath(
  sessionFile: string,
  sessionsRoot = sessionSearchRoot(),
): string {
  return isAbsolute(sessionFile) ? resolve(sessionFile) : resolve(sessionsRoot, sessionFile);
}

// Inspect only the first bounded JSONL record to select its owning reader.
// Pi remains responsible for Pi's format; Codex names are not in its rollout.
const MAX_SESSION_HEADER_BYTES = 5 * 1024 * 1024;

async function readSessionHeader(path: string): Promise<unknown> {
  if (!(await stat(path)).isFile()) throw new Error("Session path is not a regular file");
  const file = await open(path, "r");
  try {
    const parts: Buffer[] = [];
    let size = 0;
    while (size <= MAX_SESSION_HEADER_BYTES) {
      const buffer = Buffer.allocUnsafe(Math.min(64 * 1024, MAX_SESSION_HEADER_BYTES + 1 - size));
      const { bytesRead } = await file.read(buffer, 0, buffer.length, null);
      if (!bytesRead) break;
      const bytes = buffer.subarray(0, bytesRead);
      const newline = bytes.indexOf(10);
      const part = newline < 0 ? bytes : bytes.subarray(0, newline);
      parts.push(part);
      size += part.length;
      if (size > MAX_SESSION_HEADER_BYTES) throw new Error("Session header exceeds 5 MiB");
      if (newline >= 0) break;
    }
    try {
      return JSON.parse(Buffer.concat(parts, size).toString("utf8"));
    } catch {
      throw new Error("Cannot parse session header as JSON");
    }
  } finally {
    await file.close();
  }
}

async function readCodexSessionTitle(threadId: string): Promise<SessionTitleLookup> {
  // Private Codex schema, intentionally isolated here. Do not discover a newer
  // database or migrate it: schema/version changes must warn and leave reads usable.
  const databasePath = join(process.env.CODEX_HOME || join(homedir(), ".codex"), "state_5.sqlite");
  // Lazy import keeps the Pi-only path usable on runtimes without node:sqlite.
  const { DatabaseSync } = await import("node:sqlite");
  let database: InstanceType<typeof DatabaseSync> | undefined;
  try {
    database = new DatabaseSync(databasePath, { readOnly: true });
    // This connection-local setting also works on Node 22, which lacks the
    // constructor's timeout option. Never use immutable=1 on Codex's live WAL DB.
    database.exec("PRAGMA busy_timeout = 100");
    const row = database.prepare("SELECT name FROM threads WHERE id = ?").get(threadId);
    if (!row) return { found: false };
    if (row.name === null) return { found: true, title: undefined };
    if (typeof row.name !== "string") throw new Error("Codex thread name is not text or null");
    return { found: true, title: row.name.trim() || undefined };
  } catch (error) {
    throw new Error(`Codex title database ${databasePath}: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    database?.close();
  }
}

export async function readSessionTitle(
  sessionFile: string,
  sessionsRoot = sessionSearchRoot(),
): Promise<SessionTitleLookup> {
  const path = resolveReadSessionPath(sessionFile, sessionsRoot);
  const header = await readSessionHeader(path);
  if (!header || typeof header !== "object" || !("type" in header)) {
    throw new Error("Session header has no format type");
  }
  if (header.type === "session") {
    return { found: true, title: SessionManager.open(path).getSessionName()?.trim() || undefined };
  }
  if (header.type !== "session_meta") throw new Error("Unrecognized session format");
  const payload = "payload" in header ? header.payload : undefined;
  if (!payload || typeof payload !== "object" || !("id" in payload) ||
      typeof payload.id !== "string" || !payload.id.trim()) {
    throw new Error("Codex session header has no thread ID");
  }
  return readCodexSessionTitle(payload.id);
}

export function normalizeSessionTitle(title: string): string | undefined {
  return title.replace(/[\r\n]+/g, " ").trim() || undefined;
}

export function sessionTitleContent(title: string | undefined) {
  return { type: "text" as const, text: `Session title: ${title ?? "(untitled)"}` };
}

export async function editHistoricSessionTitles(
  requests: readonly SessionTitleRequest[],
  currentSessionPath?: string,
  listSessions: () => Promise<SessionInfo[]> = () => SessionManager.listAll(),
  appendTitle: (path: string, title: string) => void = (path, title) => {
    SessionManager.open(path).appendSessionInfo(title);
  },
): Promise<SessionTitleBatchResult> {
  if (requests.length === 0) {
    throw new Error("At least one session title edit is required");
  }

  const sessions = await listSessions();
  const resolved = requests.map((request) => ({
    request,
    session: resolveSession(sessions, request.session),
    title: normalizeSessionTitle(request.title),
  }));
  const seenPaths = new Set<string>();

  for (const edit of resolved) {
    const normalizedPath = resolve(edit.session.path);
    if (currentSessionPath && normalizedPath === resolve(currentSessionPath)) {
      throw new Error("The selected session is active; use /name for the current session");
    }
    if (seenPaths.has(normalizedPath)) {
      throw new Error(`The batch contains duplicate session: ${edit.request.session}`);
    }
    seenPaths.add(normalizedPath);
  }

  const edits: SessionTitleEdit[] = [];
  const unchanged: SessionTitleEdit[] = [];
  for (const edit of resolved) {
    const result = {
      session: edit.request.session,
      path: edit.session.path,
      previousTitle: edit.session.name,
      title: edit.title,
    };
    if ((edit.session.name?.trim() || undefined) === edit.title) {
      unchanged.push(result);
      continue;
    }
    try {
      appendTitle(edit.session.path, edit.title ?? "");
    } catch (error) {
      return {
        edits,
        unchanged,
        failure: {
          session: edit.request.session,
          path: edit.session.path,
          error: error instanceof Error ? error.message : String(error),
        },
      };
    }
    edits.push(result);
  }
  return { edits, unchanged };
}

export default function sessionTitle(pi: ExtensionAPI) {
  pi.registerTool({
    name: "set_current_session_title",
    label: "Set Current Session Title",
    description:
      "Set or clear the current Pi session title through Pi's authoritative session API. Newlines are replaced with spaces and an empty title clears it.",
    parameters: Type.Object({
      title: Type.String({ description: "New title, or an empty string to clear the title" }),
    }),
    async execute(_toolCallId, params) {
      const previousTitle = pi.getSessionName();
      const title = normalizeSessionTitle(params.title);
      if (previousTitle?.trim() === title) {
        return {
          content: [{ type: "text", text: "Session title unchanged" }],
          details: { previousTitle, title, changed: false },
        };
      }

      pi.setSessionName(title);
      return {
        content: [{ type: "text", text: `Session title ${title ? "updated" : "cleared"}` }],
        details: { previousTitle, title, changed: true },
      };
    },
  });

  pi.registerTool({
    name: "edit_session_title",
    label: "Edit Session Title",
    description:
      "Set or clear titles for saved historic Pi sessions in one validated batch. Identify each session by its exact session ID or absolute JSONL path. Use set_current_session_title for the active session. An empty title clears it. The tool refuses active or duplicate sessions, validates all targets before writing, and reports partial application if a write fails.",
    parameters: Type.Object({
      edits: Type.Array(Type.Object({
        session: Type.String({ description: "Exact saved session ID or absolute JSONL path" }),
        title: Type.String({ description: "New title, or an empty string to clear the title" }),
      }), { minItems: 1, description: "Session title edits to validate and apply sequentially" }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const result = await editHistoricSessionTitles(
        params.edits,
        ctx.sessionManager.getSessionFile(),
      );
      const lines = [
        `Updated ${result.edits.length} session title(s)`,
        `Unchanged ${result.unchanged.length} session title(s)`,
      ];
      if (result.failure) {
        lines.push(
          `Stopped at ${result.failure.path}`,
          `Error: ${result.failure.error}`,
        );
      }
      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: result,
      };
    },
  });

  pi.on("tool_result", async (event, ctx) => {
    if (event.toolName !== "read_session" || event.isError) return;
    const details: Record<string, unknown> = event.details && typeof event.details === "object" ? { ...event.details } : {};
    if (Array.isArray(details.versions)) return;
    const sessionFile = typeof details.sessionFile === "string" ? details.sessionFile : event.input.sessionFile;
    if (typeof sessionFile !== "string" || !sessionFile.trim()) return;
    try {
      const lookup = await readSessionTitle(sessionFile);
      if (!lookup.found) return;
      const title = lookup.title;
      return {
        content: [sessionTitleContent(title), ...event.content],
        structuredContent: event.structuredContent,
        details: { ...details, sessionTitle: title },
      };
    } catch (error) {
      const warning = `Could not read session title for ${sessionFile}: ${error instanceof Error ? error.message : String(error)}`;
      ctx.ui.notify(warning, "warning");
      return {
        content: [{ type: "text" as const, text: `Warning: ${warning}` }, ...event.content],
        structuredContent: event.structuredContent,
        details: { ...details, sessionTitleWarning: warning },
      };
    }
  });
}
