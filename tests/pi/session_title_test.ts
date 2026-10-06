import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { SessionInfo } from "@earendil-works/pi-coding-agent";
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
      expect(readSessionTitle(firstPath)).toBe("New title");
      expect(readSessionTitle(secondPath)).toBeUndefined();
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
