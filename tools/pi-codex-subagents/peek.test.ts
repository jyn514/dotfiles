import { beforeAll, describe, expect, test } from "bun:test";
import { AssistantMessageComponent, getMarkdownTheme, initTheme, SessionManager, SettingsManager, UserMessageComponent, type Theme, type ToolExecutionComponent } from "@earendil-works/pi-coding-agent";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { ProcessTerminal, TuiMainScreen } from "@earendil-works/pi-tui";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { stripVTControlCharacters } from "node:util";
import { SubagentPeekOverlay } from "./peek.js";

beforeAll(() => initTheme("dark", false));

function createTool(name: string, args: Record<string, unknown>): ToolExecutionComponent {
  return SubagentPeekOverlay.prototype["createToolComponent"].call(
    { cwd: process.cwd(), tui: { requestRender() {} }, display: { settings: SettingsManager.inMemory(), toolsExpanded: false } } as any,
    name,
    "call-1",
    args,
  );
}

function renderTool(component: ToolExecutionComponent): string {
  return stripVTControlCharacters(component.render(100).join("\n"));
}

describe("peek tool rendering", () => {
  test.each(["bash", "edit", "find", "grep", "ls", "powershell", "read", "write"])(
    "passes an explicit built-in definition for %s",
    (name) => {
      const component = createTool(name, {});
      expect(component["toolDefinition"]?.name).toBe(name);
      expect(component["toolDefinition"]?.renderCall).toBeFunction();
      expect(component["toolDefinition"]?.renderResult).toBeFunction();
    },
  );

  test("read shows only its compact header instead of raw arguments and the full file", () => {
    const component = createTool("read", { path: "src/catalog.rs", offset: 100, limit: 45 });
    component.updateResult({
      content: [{ type: "text", text: Array.from({ length: 45 }, (_, i) => `file_line_${i + 1}`).join("\n") }],
      isError: false,
    });

    const text = renderTool(component);
    expect(text).toContain("src/catalog.rs");
    expect(text).not.toContain('"path":');
    expect(text).toContain("100-144");
    expect(text).not.toContain("file_line_");
  });

  test("bash output stays collapsed while streaming and after completion", () => {
    const component = createTool("bash", { command: "printf output" });
    const result = {
      content: [{ type: "text" as const, text: Array.from({ length: 30 }, (_, i) => `output_line_${i + 1}`).join("\n") }],
      isError: false,
    };

    for (const isPartial of [true, false]) {
      component.updateResult(result, isPartial);
      const text = renderTool(component);
      expect(text).toContain("printf output");
      expect(text).not.toContain('"command":');
      expect(text).not.toContain("output_line_1");
      expect(text).toContain("output_line_30");
      expect(text).toContain("25 earlier lines");
    }
  });
});

function displayFixture(settings: SettingsManager, toolsExpanded = false) {
  const root = mkdtempSync(join(tmpdir(), "peek-display-"));
  const session = SessionManager.create(root, root);
  const message: AssistantMessage = {
    role: "assistant",
    content: [
      { type: "thinking", thinking: "reasoning_marker" },
      { type: "text", text: "answer_marker\n\n```text\ncode_marker\n```" },
    ],
    api: "openai-responses", provider: "openai", model: "fixture",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "stop", timestamp: 1,
  };
  const userText = "user_marker\n\n```text\nuser_code_marker\n```";
  session.appendMessage({ role: "user", content: userText, timestamp: 1 });
  session.appendMessage(message);
  const tui = new TuiMainScreen(new ProcessTerminal());
  tui.requestRender = () => {};
  // Only the overlay frame uses this theme; message components use Pi's initialized theme.
  const frameTheme = { fg: (_color: string, text: string) => text } as Theme;
  const overlay = new SubagentPeekOverlay(tui, frameTheme, {
    id: "peek-display", taskName: "display", canonicalName: "display", parentSessionId: "parent",
    cwd: root, sessionFile: session.getSessionFile()!, provider: "openai", modelId: "fixture", model: "fixture",
    infoFile: join(root, "info.json"), logFile: join(root, "log"), createdAt: 1, updatedAt: 1,
    messageCount: 2, status: "suspended",
  }, () => {}, { settings, toolsExpanded });
  return { root, tui, overlay, message, userText, close() { overlay.dispose(); rmSync(root, { recursive: true, force: true }); } };
}

function plainLines(component: { render(width: number): string[] }): string[] {
  return component.render(100).map(stripVTControlCharacters);
}

describe("peek parent display settings", () => {
  for (const compact of [false, true]) {
    test.each(["saved", "stream", "reconnect", "delta"])(
      `assistant settings match the parent: compact=${compact}, source=%s`,
      (source) => {
        const settings = SettingsManager.inMemory({
          outputPad: compact ? 0 : 1, outputPadY: compact ? 0 : 1,
          hideThinkingBlock: !compact, markdown: { codeBlockIndent: "     " },
        });
        const f = displayFixture(settings);
        try {
          if (source === "stream") f.overlay["handleEvent"]({ type: "message_start", message: f.message });
          if (source === "reconnect") f.overlay["handleEvent"]({ type: "sync", partialMessage: f.message, status: "streaming" });
          if (source === "delta") f.overlay["handleEvent"]({ type: "message_update", message: f.message });
          const assistants = f.overlay["chatContainer"].children.filter(child => child instanceof AssistantMessageComponent);
          const actual = plainLines(assistants.at(-1)!);
          const parent = new AssistantMessageComponent(f.message, !compact,
            { ...getMarkdownTheme(), codeBlockIndent: "     " }, undefined, compact ? 0 : 1, [], compact ? 0 : 1);
          expect(actual).toEqual(plainLines(parent));
          expect(actual.some(line => line.includes("reasoning_marker"))).toBe(compact);
          expect(actual.some(line => line.startsWith(compact ? "answer_marker" : " answer_marker"))).toBe(true);
          expect(actual.some(line => line.includes("     code_marker"))).toBe(true);
          expect(actual[0]?.trim() === "").toBe(!compact);
        } finally { f.close(); }
      },
    );
  }

  test.each(["saved", "stream", "reconnect"])("user messages inherit padding and code indentation: %s", source => {
    const f = displayFixture(SettingsManager.inMemory({ outputPad: 0, outputPadY: 0, markdown: { codeBlockIndent: "     " } }));
    try {
      if (source === "stream") f.overlay["handleEvent"]({ type: "message_start", message: { role: "user", content: f.userText } });
      if (source === "reconnect") f.overlay["handleEvent"]({ type: "sync", userMessage: { role: "user", content: f.userText } });
      const users = f.overlay["chatContainer"].children.filter(child => child instanceof UserMessageComponent);
      const actual = plainLines(users.at(-1)!);
      expect(actual).toEqual(plainLines(new UserMessageComponent(f.userText,
        { ...getMarkdownTheme(), codeBlockIndent: "     " }, 0, [], 0)));
      expect(actual.some(line => line.startsWith("user_marker"))).toBe(true);
      expect(actual.some(line => line.includes("     user_code_marker"))).toBe(true);
    } finally { f.close(); }
  });

  test.each([false, true])("tools inherit preview limits and expansion: expanded=%p", expanded => {
    const f = displayFixture(SettingsManager.inMemory({ outputPad: 0, outputPadY: 0, toolPreviewLines: 2,
      terminal: { showImages: false, imageWidthCells: 23 } }), expanded);
    try {
      const component = f.overlay["createToolComponent"]("custom_tool", "call", {});
      component.updateResult({ content: [{ type: "text", text: "first_marker\nsecond_marker\nthird_marker\nfourth_marker" }], isError: false });
      const text = renderTool(component);
      expect(text).toContain("first_marker");
      expect(text).toContain("second_marker");
      expect(text.includes("third_marker")).toBe(expanded);
      expect(text.includes("fourth_marker")).toBe(expanded);
      expect(plainLines(component)[0]?.trim()).not.toBe("");
      expect(component["showImages"]).toBe(false);
      expect(component["imageWidthCells"]).toBe(23);
    } finally { f.close(); }
  });

  test.each([0, 2])("edit previews inherit context lines: %i", async contextLines => {
    const f = displayFixture(SettingsManager.inMemory({ editContextLines: contextLines }));
    try {
      writeFileSync(join(f.root, "edit.txt"), "before_marker\ntarget_marker\nafter_marker\n");
      const component = f.overlay["createToolComponent"]("edit", "edit-call", {
        path: "edit.txt", edits: [{ oldText: "target_marker", newText: "changed_marker" }],
      });
      component.setArgsComplete();
      const redraw = Promise.withResolvers<void>();
      f.tui.requestRender = () => { redraw.resolve(); };
      await redraw.promise;
      const text = renderTool(component);
      expect(text).toContain("changed_marker");
      expect(text.includes("before_marker")).toBe(contextLines > 0);
      expect(text.includes("after_marker")).toBe(contextLines > 0);
    } finally { f.close(); }
  });
});
