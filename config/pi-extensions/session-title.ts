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

export function readSessionTitle(
  sessionFile: string,
  sessionsRoot = sessionSearchRoot(),
): string | undefined {
  return SessionManager.open(resolveReadSessionPath(sessionFile, sessionsRoot))
    .getSessionName()?.trim() || undefined;
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

  pi.on("tool_result", async (event) => {
    if (event.toolName !== "read_session" || event.isError) return;
    const sessionFile = event.input.sessionFile;
    if (typeof sessionFile !== "string") return;

    const title = readSessionTitle(sessionFile);
    const details = event.details && typeof event.details === "object"
      ? { ...event.details, sessionTitle: title }
      : { sessionTitle: title };
    return {
      content: [
        sessionTitleContent(title),
        ...event.content,
      ],
      details,
    };
  });
}
