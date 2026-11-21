import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { EventEmitter } from "node:events";
import { join } from "node:path";
import type { SessionInfo } from "@earendil-works/pi-coding-agent";
import sessionTools, { readSessionWorker } from "../../config/pi-agent/pi-extensions/session-tools.ts";
import sessionTitle, {
  editHistoricSessionTitles,
  normalizeSessionTitle,
  readSessionTitle,
  resolveReadSessionPath,
  resolveSession,
  sessionTitleContent,
} from "../../config/pi-agent/pi-extensions/session-title";

function session(path: string, id: string, name?: string): SessionInfo {
  return {
    path,
    id,
    cwd: "/project",
    name,
    created: new Date(0),
    modified: new Date(0),
    messageCount: 0,
    firstMessage: "(no messages)",
    allMessagesText: "",
  };
}

describe("historic session title editing", () => {
  test("resolves exact edit references and relative read_session paths", () => {
    const sessions = [session("/sessions/project/one.jsonl", "one", "One title")];
    expect(resolveSession(sessions, "one").path).toBe("/sessions/project/one.jsonl");
    expect(resolveSession(sessions, "/sessions/project/one.jsonl").id).toBe("one");
    expect(resolveReadSessionPath("project/one.jsonl", "/sessions"))
      .toBe("/sessions/project/one.jsonl");
    expect(normalizeSessionTitle(" New\ntitle ")).toBe("New title");
    expect(normalizeSessionTitle(" \n ")).toBeUndefined();
    expect(sessionTitleContent("One title").text).toBe("Session title: One title");
    expect(sessionTitleContent(undefined).text).toBe("Session title: (untitled)");
    expect(() => resolveSession(sessions, "missing")).toThrow("No saved session");
  });

  test("validates and appends a sanitized batch that can clear titles", async () => {
    const root = await mkdtemp(join(tmpdir(), "session-title-"));
    const firstPath = join(root, "first.jsonl");
    const secondPath = join(root, "second.jsonl");
    try {
      const header = (id: string) => `${JSON.stringify({
        type: "session",
        version: 3,
        id,
        timestamp: "2026-09-01T00:00:00.000Z",
        cwd: "/project",
      })}\n`;
      await writeFile(firstPath, header("first-id"));
      await writeFile(secondPath, header("second-id"));
      const sessions = [
        session(firstPath, "first-id", "Old title"),
        session(secondPath, "second-id", "Second title"),
      ];

      const result = await editHistoricSessionTitles(
        [
          { session: "first-id", title: " New\ntitle " },
          { session: secondPath, title: "" },
        ],
        undefined,
        async () => sessions,
      );
      expect(result).toEqual({
        edits: [
          { session: "first-id", path: firstPath, previousTitle: "Old title", title: "New title" },
          { session: secondPath, path: secondPath, previousTitle: "Second title", title: undefined },
        ],
        unchanged: [],
      });

      const firstEntries = (await readFile(firstPath, "utf8")).trim().split("\n").map(JSON.parse);
      const secondEntries = (await readFile(secondPath, "utf8")).trim().split("\n").map(JSON.parse);
      expect(firstEntries.at(-1).name).toBe("New title");
      expect(secondEntries.at(-1).name).toBe("");
      expect(await readSessionTitle(firstPath)).toEqual({ found: true, title: "New title" });
      expect(await readSessionTitle(secondPath)).toEqual({ found: true, title: undefined });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("skips titles that already match", async () => {
    const saved = session("/sessions/saved.jsonl", "saved", "Same title");
    const writes: string[] = [];
    const result = await editHistoricSessionTitles(
      [{ session: "saved", title: " Same title " }],
      undefined,
      async () => [saved],
      (path) => writes.push(path),
    );

    expect(writes).toEqual([]);
    expect(result).toEqual({
      edits: [],
      unchanged: [{
        session: "saved",
        path: saved.path,
        previousTitle: "Same title",
        title: "Same title",
      }],
    });
  });

  test("rejects an invalid batch before writing", async () => {
    const saved = session("/sessions/current.jsonl", "current");
    const writes: string[] = [];
    await expect(editHistoricSessionTitles(
      [
        { session: "current", title: "new" },
        { session: "current", title: "again" },
      ],
      undefined,
      async () => [saved],
      (path) => writes.push(path),
    )).rejects.toThrow("duplicate session");
    expect(writes).toEqual([]);

    await expect(editHistoricSessionTitles(
      [{ session: "current", title: "new" }],
      saved.path,
      async () => [saved],
      (path) => writes.push(path),
    )).rejects.toThrow("session is active");
    expect(writes).toEqual([]);
  });

  test("reports the first write failure after preceding edits", async () => {
    const sessions = [
      session("/sessions/one.jsonl", "one"),
      session("/sessions/two.jsonl", "two"),
      session("/sessions/three.jsonl", "three"),
    ];
    const writes: string[] = [];
    const result = await editHistoricSessionTitles(
      sessions.map(({ id }) => ({ session: id, title: `Title ${id}` })),
      undefined,
      async () => sessions,
      (path) => {
        if (path.endsWith("two.jsonl")) throw new Error("disk full");
        writes.push(path);
      },
    );

    expect(writes).toEqual(["/sessions/one.jsonl"]);
    expect(result.edits.map(({ session }) => session)).toEqual(["one"]);
    expect(result.unchanged).toEqual([]);
    expect(result.failure).toEqual({
      session: "two",
      path: "/sessions/two.jsonl",
      error: "disk full",
    });
  });

  test("the configured session adapter registers both tools and routes the reader", async () => {
    const tools = new Map<string, any>();
    const pi = { events: new EventEmitter(), on() {}, getSettings: () => ({}),
      registerTool: (tool: any) => tools.set(tool.name, tool), registerCommand() {} };
    sessionTools(pi as never);
    expect([...tools.keys()].sort()).toEqual(["read_session", "search_sessions"]);
    const root = await mkdtemp(join(tmpdir(), "host-reader-"));
    try {
      const file = join(root, "session.jsonl");
      await writeFile(file, [JSON.stringify({ type: "session", id: "host", cwd: root, timestamp: "2026-01-01T00:00:00Z" }),
        JSON.stringify({ type: "message", timestamp: "2026-01-01T00:00:01Z", message: { role: "user", content: "host content" } })].join("\n") + "\n");
      const result = await tools.get("read_session").execute("host", { sessionFile: file }, undefined, undefined, { cwd: root });
      expect(result.content[0].text).toContain("host content");
      expect(result.details.toolExecution).toEqual({ target: "host", source: "default" });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("guest reader supplies title metadata alongside the normal result", async () => {
    const root = await mkdtemp(join(tmpdir(), "guest-reader-"));
    try {
      const file = join(root, "session.jsonl");
      const sdk = join(root, "sdk.mjs");
      await writeFile(file, [JSON.stringify({ type: "session", id: "guest", cwd: root, timestamp: "2026-01-01T00:00:00Z" }),
        JSON.stringify({ type: "message", timestamp: "2026-01-01T00:00:01Z", message: { role: "user", content: "guest content" } })].join("\n") + "\n");
      await writeFile(sdk, `export const SessionManager = { open: () => ({ getSessionName: () => 'Guest title' }) };`);
      const ctx = { cwd: root, agentDir: root, piModule: sdk, model: null, session: null,
        signal: new AbortController().signal, onUpdate() {} };
      const result = await readSessionWorker({ sessionFile: file }, ctx);
      expect(result.content[0].text).toContain("guest content");
      expect(result.structuredContent).toBe(result.content[0].text);
      expect(result.details).toMatchObject({ sessionTitleFound: true, sessionTitle: "Guest title" });
      const missing = await readSessionWorker({ sessionFile: join(root, "missing") }, ctx);
      expect(missing.isError).toBe(true);
      expect(missing.content[0].text).toContain("read_session failed in guest:");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("guest title results use supplied metadata without reading host paths", async () => {
    let hook: ((event: any, ctx: any) => Promise<any>) | undefined;
    const warnings: string[] = [];
    sessionTitle({
      registerTool() {},
      on(name: string, handler: typeof hook) { if (name === "tool_result") hook = handler; },
    } as never);
    const ctx = { ui: { notify: (message: string) => warnings.push(message) } };
    const event = {
      toolName: "read_session", input: { sessionFile: "/guest-only/missing.jsonl" },
      content: [{ type: "text", text: "transcript" }], structuredContent: "transcript", isError: false,
      details: { sessionFile: "/guest-only/missing.jsonl", toolExecution: { target: "guest", source: "settings" }, sessionTitleFound: true, sessionTitle: "Guest title" },
    };
    const result = await hook!(event, ctx);
    expect(result.content[0].text).toBe("Session title: Guest title");
    expect(result.structuredContent).toBe("transcript");
    expect(warnings).toEqual([]);
    const warned = await hook!({ ...event, details: { ...event.details, sessionTitleFound: false, sessionTitleWarning: "guest warning" } }, ctx);
    expect(warned.content[0].text).toBe("Warning: guest warning");
    expect(warnings).toEqual(["guest warning"]);
    expect(await hook!({ ...event, details: { ...event.details, versions: [{}] } }, ctx)).toBeUndefined();
  });

  test("registers current and historic title tools", async () => {
    type RegisteredTool = {
      description: string;
      promptGuidelines?: string[];
      parameters: unknown;
      execute: (...args: never[]) => Promise<{
        content: Array<{ text: string }>;
        details: { previousTitle?: string; title?: string; changed: boolean };
      }>;
    };
    const tools = new Map<string, RegisteredTool>();
    const events: string[] = [];
    let currentTitle: string | undefined = "Old title";
    sessionTitle({
      registerTool(tool: RegisteredTool & { name: string }) {
        tools.set(tool.name, tool);
      },
      getSessionName() {
        return currentTitle;
      },
      setSessionName(title: string | undefined) {
        currentTitle = title;
      },
      on(event: string) {
        events.push(event);
      },
    } as never);

    const currentTool = tools.get("set_current_session_title");
    expect(currentTool?.description).toContain("authoritative session API");
    expect(currentTool?.description).toContain("current Pi session");
    expect(currentTool?.description).toContain("Newlines are replaced with spaces");
    expect(currentTool?.description).toContain("an empty title clears it");
    expect(currentTool?.promptGuidelines).toBeUndefined();
    const changed = await currentTool?.execute(undefined as never, {
      title: " New\ntitle ",
    } as never);
    expect(currentTitle).toBe("New title");
    expect(changed?.details).toEqual({
      previousTitle: "Old title",
      title: "New title",
      changed: true,
    });

    const unchanged = await currentTool?.execute(undefined as never, {
      title: "New title",
    } as never);
    expect(unchanged?.content[0].text).toBe("Session title unchanged");
    const historicTool = tools.get("edit_session_title");
    expect(historicTool?.description).toContain("validated batch");
    expect(historicTool?.description).toContain("exact session ID or absolute JSONL path");
    expect(historicTool?.description).toContain("Use set_current_session_title for the active session");
    expect(historicTool?.description).toContain("An empty title clears it");
    expect(historicTool?.description).toContain("refuses active or duplicate sessions");
    expect(historicTool?.description).toContain("validates all targets before writing");
    expect(historicTool?.description).toContain("reports partial application if a write fails");
    expect(historicTool?.promptGuidelines).toBeUndefined();
    expect(historicTool?.parameters).toBeDefined();
    expect(events).toContain("tool_result");
  });
});
