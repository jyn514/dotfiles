import { describe, expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionContext, MarkdownTransformer, Theme } from "@earendil-works/pi-coding-agent";
import { type Component, getKeybindings, Markdown, type MarkdownTheme, visibleWidth } from "@earendil-works/pi-tui";
import { stripVTControlCharacters } from "node:util";
import askUser from "../../config/pi-agent/pi-extensions/ask-user";

const ESC = "\x1b";
const LEFT = "\x1b[1;3D";
const RIGHT = "\x1b[1;3C";
const DOWN = "\x1b[B";
const ENTER = "\r";
const theme = { fg: (_color: string, text: string) => text, bold: (text: string) => text } as Theme;

// Native registration/execute/custom-component boundary. Only host services are
// doubled: the component uses the installed real Editor, keybindings and schema.
// sendUserMessage deliberately returns void, matching Pi's extension API.
function host() {
  const tools = new Map<string, any>();
  let transformer: MarkdownTransformer;
  const handlers = new Map<string, Function>();
  const shortcuts = new Map<string, Function>();
  let component: Component | undefined;
  let closed = 0;
  let customCalls = 0;
  let renders = 0;
  let sessionId = "first";
  let entries: any[] = [];
  const messages: { content: string; options: unknown }[] = [];
  const notifications: string[] = [];
  let widget: string[] | undefined;
  const widgetCalls: { key: string; content: string[] | undefined; placement: string }[] = [];
  let failSend = false;
  let failPersist = false;
  let duringSend: (() => void) | undefined;
  const pi = {
    registerTool(value: any) { tools.set(value.name, value); },
    registerMarkdownTransformer(value: MarkdownTransformer) { transformer = value; },
    registerShortcut(key: string, value: any) { shortcuts.set(key, value.handler); },
    on(event: string, handler: Function) { handlers.set(event, handler); return () => {}; },
    appendEntry(customType: string, data: unknown) {
      if (failPersist) throw new Error("disk unavailable");
      entries.push({ type: "custom", customType, data: structuredClone(data) });
    },
    sendUserMessage(content: string, options: unknown): void {
      duringSend?.();
      if (failSend) throw new Error("dispatch unavailable");
      messages.push({ content, options });
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    mode: "tui", hasUI: true,
    sessionManager: { getSessionId: () => sessionId, getBranch: () => entries },
    ui: {
      notify(text: string) { notifications.push(text); },
      setWidget(key: string, content: string[] | undefined, options: { placement: string }) {
        widget = content;
        widgetCalls.push({ key, content, placement: options.placement });
        renders++;
      },
      getEditorText() { return "Untouched normal prompt"; },
      setEditorText() { throw new Error("ask_user must not change the normal editor"); },
      setEditorComponent() { throw new Error("ask_user must not replace the normal editor"); },
      custom(factory: Function) {
        customCalls++;
        return new Promise<void>((resolve) => {
          component = factory({ terminal: { rows: 40, columns: 140 }, requestRender() { renders++; } }, theme, getKeybindings(), () => { closed++; resolve(); });
          (component as any).focused = true;
        });
      },
    },
  } as unknown as ExtensionContext;
  askUser(pi);
  const emit = (event: string) => handlers.get(event)?.({}, ctx);
  emit("session_start");
  return {
    ctx, pi, tools, messages, notifications, emit,
    display(markdown: string, messageType: "user" | "assistant" | "assistant-thinking" = "user", availableWidth = 140, isStreaming = false) {
      return transformer(markdown, { messageType, availableWidth, isStreaming });
    },
    async ask(questions: any[], mode = "tui", signal?: AbortSignal) {
      return tools.get("ask_user").execute("call", { questions }, signal, undefined, { ...ctx, mode });
    },
    async cancel(question_ids: any, mode = "tui", signal?: AbortSignal) {
      return tools.get("cancel_ask_user").execute("cancel", { question_ids }, signal, undefined, { ...ctx, mode });
    },
    open() { return shortcuts.get("alt+a")!(ctx) as Promise<void>; },
    key(data: string) { component!.handleInput!(data); },
    text(width = 140) { return component!.render(width).map(stripVTControlCharacters).join("\n"); },
    get panel() { return component!; },
    get closed() { return closed; },
    get customCalls() { return customCalls; },
    get widget() { return widget; },
    widgetCalls,
    get renders() { return renders; },
    get entries() { return entries; },
    set entries(value: any[]) { entries = value; },
    set sessionId(value: string) { sessionId = value; },
    set failSend(value: boolean) { failSend = value; },
    set failPersist(value: boolean) { failPersist = value; },
    set duringSend(value: (() => void) | undefined) { duringSend = value; },
  };
}
const question = (title: string, options?: string[]) => ({ title, question: `Decide ${title}?`, ...(options ? { options } : {}) });

describe("asynchronous ask_user", () => {
  test("registers asynchronous steering, conditional review routing and cancellation guidance", () => {
    const h = host();
    const askTool = h.tools.get("ask_user");
    expect(askTool.description).toContain("user steering messages with question IDs");
    expect(askTool.description).toContain("Continue only independent work");
    expect(askTool.description).toContain("silence is not an answer or permission");
    expect(askTool.promptGuidelines).toEqual([
      "When asking for human judgment or approval, use the human-review-packets skill to frame the question. Routine requests for missing facts do not need it.",
      "Use cancel_ask_user to remove questions made obsolete by later work.",
    ]);
    expect(h.tools.get("cancel_ask_user").description).toContain("does not recall dispatched answers or grant permission");
  });
  test("returns unique IDs without opening UI; appends batches to an open panel without moving selection", async () => {
    const h = host();
    const first = await h.ask([question("scope"), question("format", ["JSON", "YAML"])]);
    expect(first.details.questions).toHaveLength(2);
    expect(h.customCalls).toBe(0);
    expect(h.ctx.ui.getEditorText()).toBe("Untouched normal prompt");
    expect(h.widgetCalls.at(-1)).toEqual({ key: "ask-user", content: ["2 pending question(s) · Alt+A to answer"], placement: "aboveEditor" });
    expect(first.content[0].text).toContain("silence is not permission");
    const open = h.open();
    expect(h.text()).toContain("Question 1 of 2 — scope");
    h.key(RIGHT);
    expect(h.text()).toContain("Question 2 of 2 — format");
    const before = h.renders;
    const second = await h.ask([question("priority")]);
    expect(new Set([...first.details.questions, ...second.details.questions].map((q: any) => q.id)).size).toBe(3);
    expect(h.renders).toBeGreaterThan(before);
    expect(h.text()).toContain("Question 2 of 3 — format");
    void h.open();
    expect(h.customCalls).toBe(1);
    h.key(RIGHT);
    expect(h.text()).toContain("Question 3 of 3 — priority");
    h.key(RIGHT);
    expect(h.text()).toContain("Question 1 of 3 — scope");
    h.key(LEFT);
    expect(h.text()).toContain("Question 3 of 3 — priority");
    h.key(ESC);
    await open;
    expect(h.messages).toHaveLength(0);
  });

  test("cancellation preserves unrelated selection and drafts, replaces a cancelled selection, and closes an empty panel", async () => {
    const h = host();
    const queued = await h.ask([question("obsolete"), question("keep"), question("also obsolete")]);
    const [obsolete, keep, alsoObsolete] = queued.details.questions.map((q: any) => q.id);
    const open = h.open();
    h.key("Discard this draft");
    h.key(RIGHT);
    h.key("Keep this draft");
    const before = h.renders;
    const result = await h.cancel([obsolete, obsolete, "unknown"]);
    expect(result.details).toEqual({ cancelled: [obsolete], notPending: ["unknown"] });
    expect(result.content[0].text).toContain("not an answer or permission");
    expect(h.renders).toBeGreaterThan(before);
    expect(h.text()).toContain("Question 1 of 2 — keep");
    expect(h.text()).toContain("Keep this draft");
    h.key(RIGHT);
    h.key("Another discarded draft");
    await h.cancel([alsoObsolete]);
    // Submit without rendering first: cancellation must switch the editor now.
    h.key(ENTER);
    await open;
    expect(h.messages).toHaveLength(1);
    expect(h.messages[0].content).toContain(keep);
    expect(h.messages[0].content).toEndWith("Keep this draft");
    expect(h.entries.at(-1).data.questions).toEqual([]);

    const last = await h.ask([question("last obsolete")]);
    const lastOpen = h.open();
    h.key("Never dispatch");
    const stale = h.panel;
    await h.cancel([last.details.questions[0].id]);
    expect(h.closed).toBe(2);
    await lastOpen;
    stale.handleInput!(ENTER);
    expect(h.messages).toHaveLength(1);
    expect(h.widget).toBeUndefined();
    expect(h.entries.at(-1).data.questions).toEqual([]);
  });

  test("cancelled questions stay absent after reload; retries and already answered IDs are harmless", async () => {
    const h = host();
    const queued = await h.ask([question("obsolete"), question("keep")]);
    const [obsolete, keep] = queued.details.questions.map((q: any) => q.id);
    await h.cancel([obsolete]);
    const snapshots = h.entries.length;
    expect((await h.cancel([obsolete])).details).toEqual({ cancelled: [], notPending: [obsolete] });
    expect(h.entries).toHaveLength(snapshots);
    h.emit("session_shutdown");
    h.emit("session_start");
    const open = h.open();
    expect(h.text()).toContain("Question 1 of 1 — keep");
    expect(h.text()).not.toContain("obsolete");
    h.key("Answered already");
    h.key(ENTER);
    await open;
    expect((await h.cancel([keep])).details).toEqual({ cancelled: [], notPending: [keep] });
    expect(h.messages).toHaveLength(1);
  });

  test("failed cancellation preserves the prompt and exact draft; invalid, aborted and stale-session calls remove nothing", async () => {
    const h = host();
    const queued = await h.ask([question("keep")]);
    const id = queued.details.questions[0].id;
    const open = h.open();
    h.key("Preserve this answer");
    const snapshots = h.entries.length;
    h.failPersist = true;
    await expect(h.cancel([id])).rejects.toThrow("disk unavailable");
    h.failPersist = false;
    for (const mode of ["rpc", "print", "json"]) {
      await expect(h.cancel([id], mode)).rejects.toThrow("requires interactive TUI");
    }
    for (const ids of [[], [" "], [id, 12], undefined]) {
      await expect(h.cancel(ids)).rejects.toThrow("requires non-empty question IDs");
    }
    await expect(h.cancel([id], "tui", AbortSignal.abort())).rejects.toThrow("aborted");
    h.sessionId = "replacement";
    await expect(h.cancel([id])).rejects.toThrow("session is not active");
    h.sessionId = "first";
    expect(h.entries).toHaveLength(snapshots);
    expect(h.text()).toContain("Question 1 of 1 — keep");
    expect(h.text()).toContain("Preserve this answer");
    expect(h.widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
    h.key(ENTER);
    await open;
    expect(h.messages[0].content).toEndWith("Preserve this answer");
  });

  test("separate free-text and option drafts survive cycling, Escape and reopening at last viewed", async () => {
    const h = host();
    await h.ask([question("scope"), question("format", ["JSON", "YAML"])]);
    let open = h.open();
    h.key("Small change");
    h.key(RIGHT);
    h.key(DOWN); // YAML selection is itself a draft.
    h.key(LEFT);
    expect(h.text()).toContain("Small change");
    h.key(RIGHT);
    expect(h.text()).toContain("› YAML");
    h.key("\t");
    h.key("Custom format");
    h.key(ESC);
    await open;
    expect(h.messages).toHaveLength(0);
    open = h.open();
    expect(h.text()).toContain("Question 2 of 2 — format");
    expect(h.text()).toContain("Custom format");
    h.key("\t");
    expect(h.text()).toContain("› YAML");
    h.key(LEFT);
    expect(h.text()).toContain("Small change");
    h.key(ESC);
    await open;
  });

  test("submits ID, question and answer via steering; removes after the void call returns, advances and closes empty", async () => {
    const h = host();
    const result = await h.ask([question("scope"), question("format", ["JSON", "YAML"]), question("priority")]);
    const open = h.open();
    h.key(RIGHT);
    h.key(DOWN);
    h.duringSend = () => {
      expect(h.text()).toContain("Question 2 of 3 — format");
      expect(h.entries.at(-1).data.questions).toHaveLength(3);
    };
    h.key(ENTER);
    h.duringSend = undefined;
    expect(h.messages[0]).toEqual({
      content: `Answer to ask_user ${result.details.questions[1].id}\nTitle: "format"\n\n> Decide format?\n\nYAML`,
      options: { deliverAs: "steer" },
    });
    expect(h.text()).toContain("Question 2 of 2 — priority");
    h.key("High");
    h.key(ENTER);
    expect(h.text()).toContain("Question 1 of 1 — scope");
    h.key("Only docs");
    h.key(ENTER);
    await open;
    expect(h.closed).toBe(1);
    expect(h.messages).toHaveLength(3);
    expect(h.entries.at(-1).data.questions).toEqual([]);
    expect(h.widget).toBeUndefined();
    await h.open();
    expect(h.notifications.at(-1)).toBe("No pending questions.");
  });

  test("steering metadata stays model-facing while the real Markdown renderer quotes only the original question", async () => {
    const h = host();
    const queued = await h.ask([question("Hidden title")]);
    const open = h.open();
    h.key("Only docs");
    h.key(ENTER);
    await open;
    const original = h.messages[0].content;
    const identity = (text: string) => text;
    const markdownTheme: MarkdownTheme = {
      heading: identity, link: identity, linkUrl: identity, code: identity,
      codeBlock: identity, codeBlockBorder: identity, quote: identity, quoteBorder: identity,
      hr: identity, listBullet: identity, bold: identity, italic: identity,
      strikethrough: identity, underline: identity,
    };
    const renderer = new Markdown(original, 0, 0, markdownTheme, undefined, {
      transform: (text, width) => h.display(text, "user", width),
    });
    expect(renderer.render(140).map(stripVTControlCharacters).map((line) => line.trimEnd())).toEqual([
      "│ Decide Hidden title?", "", "Only docs",
    ]);
    expect(original).toContain(queued.details.questions[0].id);
    expect(original).toContain('Title: "Hidden title"');
    expect(h.messages[0].options).toEqual({ deliverAs: "steer" });
    expect(h.display(original)).toBe("> Decide Hidden title?\n\nOnly docs");
    for (const width of [12, 30, 140, 12]) {
      renderer.invalidate();
      const lines = renderer.render(width).map(stripVTControlCharacters);
      expect(lines.some((line) => line.startsWith("│ "))).toBe(true);
      expect(lines.join("\n")).not.toContain("Title:");
      expect(lines.join("\n")).not.toContain("Answer to ask_user");
      expect(lines.join("\n")).not.toContain(queued.details.questions[0].id);
      for (const line of lines) expect(visibleWidth(line)).toBeLessThanOrEqual(width);
    }
    const reload = host(); // No pending queue or submitted-message memory.
    expect(reload.display(original)).toBe("> Decide Hidden title?\n\nOnly docs");
    expect(reload.display(h.display(original))).toBe(h.display(original));
    expect(h.messages[0].content).toBe(original);
  });

  test("multiline metadata, blank question lines and arbitrary marker text have no ambiguous body boundary", async () => {
    const h = host();
    const title = 'Hidden title\nQuestion: title\nAnswer: "quoted" \\';
    const text = "First line\n\nQuestion: literal question marker\nAnswer: literal answer marker\nAnswer to ask_user arbitrary\nTitle: arbitrary\n> quoted already\n";
    const answer = "Answer: literal answer\n\nQuestion: literal question\nTitle: arbitrary\nAnswer to ask_user arbitrary\n> ordinary answer Markdown\nlast line";
    const queued = await h.ask([{ title, question: text }]);
    const open = h.open();
    h.key(`\x1b[200~${answer}\x1b[201~`);
    h.key(ENTER);
    await open;
    const original = h.messages[0].content;
    const expected = "> First line\n> \n> Question: literal question marker\n> Answer: literal answer marker\n> Answer to ask_user arbitrary\n> Title: arbitrary\n> > quoted already\n> \n\n" + answer;
    expect(original).toBe(`Answer to ask_user ${queued.details.questions[0].id}\nTitle: ${JSON.stringify(title)}\n\n${expected}`);
    expect(h.display(original)).toBe(expected);
    h.emit("session_shutdown");
    h.emit("session_start");
    for (const width of [8, 140, 30]) expect(h.display(original, "user", width)).toBe(expected);
    expect(h.messages[0].content).toBe(original);
    for (const kind of ["assistant", "assistant-thinking"] as const) {
      for (const streaming of [false, true]) expect(h.display(original, kind, 30, streaming)).toBe(original);
    }
  });

  test("ordinary text, malformed metadata and ambiguous historical payloads remain untouched", () => {
    const h = host();
    const id = "12345678-1234-1234-1234-123456789abc";
    for (const text of [
      "Question: ordinary\nAnswer: plain user text",
      `Answer to ask_user ${id}\nTitle: scope\nQuestion: Decide scope?\nAnswer: Yes`,
      `Answer to ask_user ${id}\nTitle: "bad \\x"\n\n> Question\n\nAnswer`,
      `Answer to ask_user not-a-uuid\nTitle: "scope"\n\n> Question\n\nAnswer`,
      `Answer to ask_user ${id}\nTitle: "scope"\n> Question\n\nAnswer`,
    ]) {
      for (const kind of ["user", "assistant", "assistant-thinking"] as const) {
        expect(h.display(text, kind)).toBe(text);
      }
    }
  });

  test("synchronous rejection retains the exact answer for retry; empty submission also preserves the question", async () => {
    const h = host();
    const result = await h.ask([question("scope")]);
    const open = h.open();
    h.key(ENTER);
    expect(h.text()).toContain("Enter a non-empty answer");
    h.key("Keep my draft");
    h.failSend = true;
    h.key(ENTER);
    expect(h.messages).toHaveLength(0);
    expect(h.text()).toContain("Not submitted: dispatch unavailable");
    expect(h.text()).toContain("Keep my draft");
    expect(h.entries.at(-1).data.questions[0].id).toBe(result.details.questions[0].id);
    h.failSend = false;
    h.key(ENTER);
    await open;
    expect(h.messages[0].content).toEndWith("\n\nKeep my draft");
  });

  test("does not queue in print, JSON or RPC modes, nor on cancellation or invalid batches", async () => {
    const h = host();
    for (const mode of ["rpc", "print", "json"]) {
      await expect(h.ask([question("scope")], mode)).rejects.toThrow("requires interactive TUI");
    }
    await expect(h.ask([])).rejects.toThrow("requires non-empty");
    await expect(h.ask([question(" ")])).rejects.toThrow("requires non-empty");
    await expect(h.ask([question("scope", [" "])])).rejects.toThrow("requires non-empty");
    await expect(h.ask([question("scope")], "tui", AbortSignal.abort())).rejects.toThrow("cancelled");
    expect(h.entries).toEqual([]);
    expect(h.customCalls).toBe(0);
  });

  test("queue persistence failure does not publish; post-dispatch save failure does not encourage duplicate submission", async () => {
    const h = host();
    h.failPersist = true;
    await expect(h.ask([question("scope")])).rejects.toThrow("disk unavailable");
    await h.open();
    expect(h.customCalls).toBe(0);
    h.failPersist = false;
    await h.ask([question("scope")]);
    const open = h.open();
    h.key("Use the draft");
    h.failPersist = true;
    h.key(ENTER);
    await open;
    expect(h.messages).toHaveLength(1);
    expect(h.notifications.at(-1)).toContain("answer dispatched, but saving pending state failed");
    await h.open();
    expect(h.customCalls).toBe(1);
  });

  test("shutdown closes UI and prevents stale keystrokes; new session has no old pending or drafts", async () => {
    const h = host();
    await h.ask([question("old session")]);
    const open = h.open();
    h.key("Do not send elsewhere");
    const oldPanel = h.panel;
    h.emit("session_shutdown");
    await open;
    h.sessionId = "second";
    h.entries = [];
    h.emit("session_start");
    oldPanel.handleInput!(ENTER);
    await h.open();
    expect(h.customCalls).toBe(1);
    expect(h.messages).toEqual([]);
    await h.ask([question("new session")]);
    const next = h.open();
    expect(h.text()).toContain("new session");
    expect(h.text()).not.toContain("Do not send elsewhere");
    h.key(ESC);
    await next;
  });

  test("reload restores only unresolved questions from active branch snapshots, not memory drafts; tree resets active UI", async () => {
    const h = host();
    const queued = await h.ask([question("scope"), question("format")]);
    const queuedBranch = structuredClone(h.entries);
    let open = h.open();
    h.key("Memory only draft");
    h.key(RIGHT);
    h.key("JSON");
    h.key(ENTER);
    h.key(ESC);
    await open;
    h.emit("session_shutdown");
    h.emit("session_start");
    open = h.open();
    expect(h.text()).toContain("Question 1 of 1 — scope");
    expect(h.text()).not.toContain("Memory only draft");
    const stale = h.panel;
    h.entries = queuedBranch;
    h.emit("session_tree");
    await open;
    stale.handleInput!(ENTER);
    open = h.open();
    expect(h.text()).toContain("Question 1 of 2 — scope");
    h.key(RIGHT);
    h.key("YAML");
    h.key(ENTER);
    expect(h.messages.at(-1)!.content).toContain(queued.details.questions[1].id);
    h.key(ESC);
    await open;
  });

  test("an earlier panel's promise cleanup cannot clear a rapidly reopened panel", async () => {
    const h = host();
    await h.ask([question("scope")]);
    const first = h.open();
    h.key("Draft");
    h.key(ESC);
    const second = h.open(); // Reopen before the first handler's await resumes.
    await first;
    void h.open();
    expect(h.customCalls).toBe(2);
    await h.ask([question("format")]);
    expect(h.text()).toContain("Question 1 of 2 — scope");
    expect(h.text()).toContain("Draft");
    h.key(ESC);
    await second;
  });

  test("undo cannot copy a different question's draft", async () => {
    const h = host();
    await h.ask([question("scope"), question("format")]);
    const open = h.open();
    h.key("Scope draft must stay separate");
    h.key(RIGHT);
    h.key("Format draft");
    h.key("\x1f"); // Default ctrl+- undo.
    expect(h.text()).not.toContain("Scope draft must stay separate");
    h.key(LEFT);
    expect(h.text()).toContain("Scope draft must stay separate");
    h.key(ESC);
    await open;
  });

  test("malformed latest saved state is reported, not silently replaced with older pending questions", async () => {
    const h = host();
    await h.ask([question("scope")]);
    h.entries.push({ type: "custom", customType: "dotfiles-ask-user", data: { version: 1, questions: [{ id: "broken" }] } });
    h.emit("session_start");
    await h.open();
    expect(h.customCalls).toBe(0);
    expect(h.notifications).toContain("ask_user: invalid saved question state; not restoring questions.");
  });

  test("session identity change without lifecycle notification is fail-closed", async () => {
    const h = host();
    await h.ask([question("scope")]);
    const open = h.open();
    h.key("Old answer");
    h.sessionId = "unexpected replacement";
    h.key(ENTER);
    expect(h.messages).toEqual([]);
    expect(h.text()).toContain("Session changed");
    await expect(h.ask([question("wrong session")])).rejects.toThrow("session is not active");
    h.key(ESC);
    await open;
  });

  test("multiline Unicode drafts and narrow rendering remain usable", async () => {
    const h = host();
    await h.ask([{ title: "Long title 日本語", question: "A long wrapped question 🧭?", options: ["a long choice", "第二"] }]);
    const open = h.open();
    h.key("\t");
    h.key("\x1b[200~first 日本語\nsecond 🧭\x1b[201~");
    for (const width of [1, 8, 30, 140]) {
      for (const line of h.panel.render(width)) expect(visibleWidth(line)).toBeLessThanOrEqual(width);
    }
    h.key(ESC);
    await open;
    const reopened = h.open();
    h.key(ENTER);
    await reopened;
    expect(h.messages[0].content).toEndWith("\n\nfirst 日本語\nsecond 🧭");
  });
});
