import { describe, expect, test } from "bun:test";
import { formatSkillsForPrompt } from "@earendil-works/pi-coding-agent";
import contextBreakdown, {
  buildContextBreakdown,
  formatContextBreakdown,
  showContextBreakdown,
} from "../../config/pi-agent/pi-extensions/context-breakdown";

const timestamp = Date.now();

function user(text: string) {
  return { role: "user" as const, content: text, timestamp };
}

function usage(tokens: number | null = 100) {
  return { tokens, contextWindow: 1_000, percent: tokens == null ? null : tokens / 10 };
}

describe("context breakdown", () => {
  test("registers the context-breakdown command", () => {
    const commands = new Map<string, { description: string }>();
    contextBreakdown({
      registerCommand(name: string, command: { description: string }) {
        commands.set(name, command);
      },
    } as never);

    expect(commands.get("context-breakdown")?.description).toBe(
      "Estimate current context usage by source",
    );
  });

  test("attributes prompt inputs without exposing their contents", () => {
    const breakdown = buildContextBreakdown(
      "base secret appended context one context two skill metadata",
      {
        cwd: "/work",
        appendSystemPrompt: "appended",
        contextFiles: [
          { path: "/one/AGENTS.md", content: "context one" },
          { path: "/two/AGENTS.md", content: "context two" },
        ],
        skills: [{
          name: "review",
          description: "skill metadata",
          filePath: "/skills/review/SKILL.md",
          baseDir: "/skills/review",
          sourceInfo: {} as never,
          disableModelInvocation: false,
        }],
      },
      [user("hello")],
      [],
      usage(),
    );
    const output = formatContextBreakdown(breakdown);

    expect(output).toContain("Context: /one/AGENTS.md");
    expect(output).toContain("Context: /two/AGENTS.md");
    expect(output).toContain("Skills catalog metadata");
    expect(output).not.toContain("context one");
    expect(output).not.toContain("skill metadata");
  });

  test("follows Pi prompt inclusion rules", () => {
    const skill = {
      name: "review",
      description: "description",
      filePath: "/skills/review/SKILL.md",
      baseDir: "/skills/review",
      sourceInfo: {} as never,
      disableModelInvocation: false,
    };

    // Pi appends the catalog even to a custom prompt when read is available.
    // Feed the actual catalog text into the accounting boundary, not a prompt
    // that claims skills were included while containing only six characters.
    const custom = buildContextBreakdown(`custom${formatSkillsForPrompt([skill])}`, {
      cwd: "/work",
      customPrompt: "custom",
      selectedTools: ["read"],
      toolSnippets: { read: "read snippet" },
      promptGuidelines: ["read guideline"],
      skills: [skill],
    }, [], [], usage());
    expect(custom.promptRows.some((row) => row.label === "Skills catalog metadata")).toBe(true);
    expect(custom.promptRows.some((row) => row.label === "Tool prompt metadata")).toBe(false);

    const noRead = buildContextBreakdown("base", {
      cwd: "/work",
      selectedTools: ["bash"],
      toolSnippets: { read: "read snippet", bash: "bash snippet" },
      skills: [skill],
    }, [], [], usage());
    expect(noRead.promptRows.some((row) => row.label === "Skills catalog metadata")).toBe(false);
    expect(noRead.promptRows.some((row) => row.label === "Tool prompt metadata")).toBe(true);
    expect(noRead.promptRows.reduce((sum, row) => sum + row.tokens, 0)).toBe(noRead.promptTotal);
    expect(noRead.promptRows.every((row) => row.tokens >= 0)).toBe(true);
  });

  test("classifies persisted conversation content", () => {
    const breakdown = buildContextBreakdown("prompt", { cwd: "/work" }, [
      user("question"),
      {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "reasoning", thinkingSignature: undefined },
          { type: "text", text: "answer", textSignature: undefined },
          { type: "toolCall", id: "call", name: "read", arguments: { path: "x" } },
        ],
        api: "openai-responses",
        provider: "openai",
        model: "test",
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "toolUse",
        timestamp,
      },
      {
        role: "toolResult",
        toolCallId: "call",
        toolName: "read",
        content: [{ type: "text", text: "result" }],
        isError: false,
        timestamp,
      },
      { role: "compactionSummary", summary: "summary", tokensBefore: 20, timestamp },
      { role: "custom", customType: "notice", content: "extension", display: true, timestamp },
    ] as never, [], usage(150));

    const labels = breakdown.conversationRows.map((row) => row.label);
    expect(labels).toContain("User messages");
    expect(labels).toContain("Assistant text");
    expect(labels).toContain("Assistant reasoning");
    expect(labels).toContain("Tool calls");
    expect(labels).toContain("Tool results");
    expect(labels).toContain("Compaction summaries");
    expect(labels).toContain("Extension messages");
    expect(breakdown.conversationRows.reduce((sum, row) => sum + row.tokens, 0)).toBe(
      breakdown.conversationTotal,
    );
    expect(breakdown.conversationRows.every((row) => row.tokens >= 0)).toBe(true);
  });

  test("attributes active tool schemas and reconciles them against Pi usage", () => {
    const breakdown = buildContextBreakdown(
      "1234",
      { cwd: "/work" },
      [user("1234")],
      [{ name: "read", description: "Read a file", parameters: { type: "object" } }],
      usage(30),
    );
    const output = formatContextBreakdown(breakdown);

    expect(output).toContain("Tool schema: read");
    expect(output).toContain(`Estimated active tool schemas: ${breakdown.toolTotal}`);
    expect(breakdown.toolTotal).toBeGreaterThan(0);
    expect(breakdown.accountingDifference).toBe(
      30 - breakdown.promptTotal - breakdown.conversationTotal - breakdown.toolTotal,
    );
  });

  test("reports signed accounting differences and unavailable usage", () => {
    const positive = buildContextBreakdown(
      "1234",
      { cwd: "/work" },
      [user("1234")],
      [],
      usage(10),
    );
    expect(positive.accountingDifference).toBe(8);
    expect(formatContextBreakdown(positive)).toContain("Estimated system prompt: 1");
    expect(formatContextBreakdown(positive)).toContain("Estimated persisted conversation: 1");
    expect(formatContextBreakdown(positive)).toContain("Accounting/rewrite difference: 8");

    const negative = buildContextBreakdown(
      "12345678",
      { cwd: "/work" },
      [user("12345678")],
      [],
      usage(1),
    );
    expect(negative.accountingDifference).toBe(-3);
    expect(formatContextBreakdown(negative)).toContain("Accounting/rewrite difference: -3");

    const unavailable = buildContextBreakdown("1234", { cwd: "/work" }, [], [], usage(null));
    expect(unavailable.accountingDifference).toBeNull();
    expect(formatContextBreakdown(unavailable)).toContain("Pi context total: unavailable");
  });

  test("uses only compaction-aware entries supplied by the session manager", async () => {
    const editorCalls: Array<[string, string]> = [];
    await showContextBreakdown({
      mode: "tui",
      getSystemPrompt: () => "prompt",
      getSystemPromptOptions: () => ({ cwd: "/work" }),
      getContextUsage: () => usage(20),
      sessionManager: {
        buildContextEntries: () => [{
          type: "compaction",
          id: "compact",
          parentId: null,
          timestamp: new Date(timestamp).toISOString(),
          summary: "kept summary",
          firstKeptEntryId: "next",
          tokensBefore: 200,
        }],
      },
      ui: {
        editor: async (title: string, content: string) => {
          editorCalls.push([title, content]);
          return content;
        },
      },
    } as never, []);

    expect(editorCalls).toHaveLength(1);
    expect(editorCalls[0][1]).toContain("Compaction summaries");
  });

  test("warns outside interactive mode", async () => {
    const notifications: Array<[string, string]> = [];
    await showContextBreakdown({
      mode: "print",
      ui: {
        notify: (message: string, level: string) => notifications.push([message, level]),
      },
    } as never, []);

    expect(notifications).toEqual([[
      "The context breakdown is available only in interactive mode",
      "warning",
    ]]);
  });
});
