import { describe, expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionContext, MarkdownTransformer, Theme } from "@earendil-works/pi-coding-agent";
import { type Component, getKeybindings, Markdown, type MarkdownTheme, visibleWidth } from "@earendil-works/pi-tui";
import { stripVTControlCharacters } from "node:util";
import askUser from "../../config/pi-agent/pi-extensions/ask-user";
import { Type } from "typebox";
import { Check } from "typebox/value";

const ESC = "\x1b";
const LEFT = "\x1b[1;3D";
const RIGHT = "\x1b[1;3C";
const DOWN = "\x1b[B";
const ENTER = "\r";
const theme = { fg: (_color: string, text: string) => text, bold: (text: string) => text } as Theme;

// Native registration/execute/custom-component boundary. Only host services are
// doubled: the component uses the installed real Editor, keybindings and schema.
// sendUserMessage deliberately returns void, matching Pi's extension API.
function eventBus() {
  const listeners = new Map<string, Set<(payload: any) => void>>();
  return {
    on(name: string, listener: (payload: any) => void) {
      let group = listeners.get(name);
      if (!group) listeners.set(name, group = new Set());
      group.add(listener);
      return () => { group.delete(listener); };
    },
    emit(name: string, payload?: unknown) {
      for (const listener of [...(listeners.get(name) ?? [])]) listener(payload);
    },
  };
}

// Model only the documented event/PromptBus boundary, not native rendering.
function dashboard(events: ReturnType<typeof eventBus>) {
  const adapters = new Map<string, any>();
  const pending = new Map<string, { prompt: any; resolve: (value: any) => void }>();
  const history: any[] = [];
  let nextId = 0;
  const respond = (response: any) => {
    const entry = pending.get(response.id);
    if (!entry || response.cancelled || !response.answer?.trim()) return;
    pending.delete(response.id);
    for (const adapter of adapters.values()) adapter.onResponse(response);
    entry.resolve(response);
  };
  const cancel = (id: string) => {
    const entry = pending.get(id);
    if (!entry) return;
    pending.delete(id);
    for (const adapter of adapters.values()) adapter.onCancel(id);
    entry.resolve({ id, cancelled: true, source: "cancel" });
  };
  const request = (options: any) => new Promise<any>((resolve) => {
    const prompt = { ...options, id: `browser-${++nextId}` };
    history.push(prompt);
    for (const adapter of adapters.values()) {
      const claim = adapter.onRequest(prompt);
      if (prompt.pipeline === "dotfiles-ask-user") expect(claim).toEqual({});
    }
    pending.set(prompt.id, { prompt, resolve });
  });
  const unregister = events.on("prompt:register-adapter", (adapter) => {
    adapters.set(adapter.name, adapter);
    adapter.setRespond(respond);
    adapter.setCancel(cancel);
  });
  const ready = () => events.emit("prompt:set-bus-request", { request });
  const undiscover = events.on("prompt:request-bus", ready);
  ready();
  return { pending, history, adapters, ready, respond, cancel,
    stop() { unregister(); undiscover(); },
  };
}

function host(before?: (events: ReturnType<typeof eventBus>) => void, mode = "tui") {
  const events = eventBus();
  before?.(events);
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
    events,
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
    mode, hasUI: true,
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
    ctx, pi, events, tools, messages, notifications, emit,
    display(markdown: string, messageType: "user" | "assistant" | "assistant-thinking" = "user", availableWidth = 140, isStreaming = false) {
      return transformer(markdown, { messageType, availableWidth, isStreaming });
    },
    async ask(questions: any[], selectedMode = mode, signal?: AbortSignal) {
      return tools.get("ask_user").execute("call", { questions }, signal, undefined, { ...ctx, mode: selectedMode });
    },
    async cancel(question_ids: any, selectedMode = mode, signal?: AbortSignal) {
      return tools.get("cancel_ask_user").execute("cancel", { question_ids }, signal, undefined, { ...ctx, mode: selectedMode });
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
  test("reserves review-packet routing for consequential approvals or substantial context", () => {
    const h = host();
    const askTool = h.tools.get("ask_user");
    expect(askTool.description).toContain("user steering messages with question IDs");
    expect(askTool.description).toContain("Continue only independent work");
    expect(askTool.description).toContain("silence is not an answer or permission");
    expect(askTool.promptGuidelines).toEqual([
      "Use the human-review-packets skill for consequential approvals or questions that require substantial context to judge. Ask simple preference questions, routine confirmations, and requests for missing facts directly.",
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


const flushBrowser = async () => { await Promise.resolve(); await Promise.resolve(); };
const flushChannel = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

// In-memory implementation of the documented structural channel interface.
// Production subprocess transport is exercised separately by native RPC tests.
function questionNetwork() {
  const event = "subagents:extension-channel:v1";
  const parentHandlers = new Map<string, Function>();
  const workers = new Map<string, { origin: any; handlers: Map<string, Function> }>();
  const register = (handlers: Map<string, Function>, channel: string, handler: Function) => {
    handlers.set(channel, handler);
    return () => { if (handlers.get(channel) === handler) handlers.delete(channel); };
  };
  let publishError = false;
  let answerError = false;
  let holdAnswer: (() => Promise<void>) | undefined;
  let requests = 0;
  const parentEndpoint = {
    version: 1, role: "parent",
    register: (channel: string, handler: Function) => register(parentHandlers, channel, handler),
    async request(workerId: string, channel: string, payload: unknown) {
      requests++;
      await holdAnswer?.();
      if (answerError) throw new Error("worker paused");
      const handler = workers.get(workerId)?.handlers.get(channel);
      if (!handler) throw new Error("worker unavailable");
      return handler(payload);
    },
  };
  const install = (events: ReturnType<typeof eventBus>, endpoint: any) => {
    events.on(event, value => { if (value?.version === 1 && typeof value.provide === "function") value.provide(endpoint); });
    events.emit(event, { version: 1, endpoint });
  };
  const parent = host(events => install(events, parentEndpoint));
  return {
    parent,
    child(workerId = "worker-a", early = true) {
      const record = { origin: { workerId, taskName: `/${workerId}`, sessionId: `session-${workerId}` }, handlers: new Map<string, Function>() };
      workers.set(workerId, record);
      const endpoint = { version: 1, role: "child",
        register: (channel: string, handler: Function) => register(record.handlers, channel, handler),
        async request(channel: string, payload: unknown) {
          if (publishError) throw new Error("presentation unavailable");
          const handler = parentHandlers.get(channel);
          if (!handler) throw new Error("parent unavailable");
          return handler(payload, record.origin);
        },
      };
      const child = host(early ? events => install(events, endpoint) : undefined, "rpc");
      if (!early) install(child.events, endpoint);
      return child;
    },
    get requests() { return requests; },
    set publishError(value: boolean) { publishError = value; },
    set answerError(value: boolean) { answerError = value; },
    set holdAnswer(value: (() => Promise<void>) | undefined) { holdAnswer = value; },
    parentHandlers,
  };
}

describe("subagent question presentation", () => {
  test("both load orders present questions and deliver one actual user answer only to the originating child", async () => {
    for (const early of [true, false]) {
      const n = questionNetwork();
      const child = n.child("desktop", early);
      const queued = await child.ask([question("Plover launch command", ["AppImage", "distro"])]);
      expect(n.parent.widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
      expect(child.customCalls).toBe(0);
      const open = n.parent.open();
      expect(n.parent.text()).toContain("/desktop — Plover launch command");
      n.parent.key(DOWN); n.parent.key(ENTER);
      await flushChannel(); await open;
      expect(child.messages).toEqual([{
        content: `Answer to ask_user ${queued.details.questions[0].id}\nTitle: "Plover launch command"\n\n> Decide Plover launch command?\n\ndistro`,
        options: { deliverAs: "steer" },
      }]);
      expect(n.parent.messages).toEqual([]);
      expect(child.entries.at(-1).data.questions).toEqual([]);
      expect(n.parent.widget).toBeUndefined();
    }
  });

  test("parent and sibling drafts stay separate even for forked same-ID questions", async () => {
    const n = questionNetwork();
    await n.parent.ask([question("parent")]);
    const a = n.child("a"); const b = n.child("b");
    const saved = { type: "custom", customType: "dotfiles-ask-user", data: {
      version: 1, questions: [{ id: "retained-id", ...question("forked") }],
    } };
    for (const child of [a, b]) { child.entries = [structuredClone(saved)]; child.emit("session_tree"); }
    await flushChannel();
    expect(n.parent.entries.at(-1).data.questions.map((q: any) => q.id)).toEqual([
      n.parent.entries[0].data.questions[0].id, "a/retained-id", "b/retained-id",
    ]);
    const open = n.parent.open(); n.parent.key("parent draft"); n.parent.key(RIGHT);
    n.parent.key("a answer"); n.parent.key(ENTER);
    await flushChannel();
    expect(a.messages).toHaveLength(1); expect(b.messages).toHaveLength(0);
    expect(n.parent.messages).toHaveLength(0);
    n.parent.key(LEFT); expect(n.parent.text()).toContain("parent draft");
    n.parent.key(ESC); await open;
  });

  test("older queue readers reject remote projections instead of treating child answers as parent input", async () => {
    const n = questionNetwork(); const child = n.child();
    await child.ask([question("child")]);
    // The pre-channel reader's actual persisted schema, including its permissive
    // question objects: adding origin fields under v1 would NOT protect routing.
    const legacyReader = Type.Object({ version: Type.Literal(1), questions: Type.Array(Type.Object({
      id: Type.String({ minLength: 1 }), title: Type.String({ minLength: 1 }),
      question: Type.String({ minLength: 1 }), options: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
    })) });
    const projection = n.parent.entries.at(-1).data;
    expect(Check(legacyReader, projection)).toBe(false);
    expect(Check(legacyReader, child.entries.at(-1).data)).toBe(true);
    n.parent.emit("session_tree");
    const open = n.parent.open(); expect(n.parent.text()).toContain("/worker-a — child");
    n.parent.key(ESC); await open;
    expect(n.parent.messages).toEqual([]);
  });

  test("child cancellation removes both surfaces, preserves other drafts and survives parent reload", async () => {
    const n = questionNetwork(); const browser = dashboard(n.parent.events);
    const child = n.child();
    const queued = await child.ask([question("obsolete"), question("keep")]);
    const open = n.parent.open(); n.parent.key(RIGHT); n.parent.key("keep draft");
    await child.cancel([queued.details.questions[0].id]);
    await flushChannel();
    expect(n.parent.text()).toContain("keep draft");
    expect(browser.pending.size).toBe(1);
    // Parent tools cannot cancel another session's authoritative question.
    const projectedId = n.parent.entries.at(-1).data.questions[0].id;
    expect((await n.parent.cancel([projectedId])).details.notPending).toEqual([projectedId]);
    n.parent.emit("session_tree"); await open;
    const reopened = n.parent.open();
    expect(n.parent.text()).toContain("keep"); expect(n.parent.text()).not.toContain("obsolete");
    await child.cancel([queued.details.questions[1].id]);
    await flushChannel(); await reopened;
    expect(browser.pending.size).toBe(0); expect(child.messages).toEqual([]);
  });

  test("rejected routing preserves the answer draft; concurrent submit does not send twice", async () => {
    const n = questionNetwork(); const child = n.child();
    await child.ask([question("scope")]);
    const open = n.parent.open(); n.parent.key("draft to child");
    n.answerError = true; n.parent.key(ENTER);
    expect(n.parent.closed).toBe(1); // Close before a transport acknowledgement, not after startup.
    expect(n.parent.widget?.join(" ")).toContain("sending");
    await open; await flushChannel();
    expect(n.parent.widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
    expect(n.parent.notifications.join(" ")).toContain("worker paused");
    expect(child.messages).toEqual([]);
    const retry = n.parent.open();
    expect(n.parent.text()).toContain("draft to child");
    n.answerError = false;
    let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    n.holdAnswer = () => barrier;
    const before = n.requests;
    n.parent.key(ENTER); n.parent.key(ENTER);
    expect(n.requests - before).toBe(1);
    expect(n.parent.closed).toBe(2);
    await n.parent.open(); // Cannot reopen and submit the same in-flight answer.
    expect(n.parent.customCalls).toBe(2);
    release(); await flushChannel(); await retry;
    expect(child.messages).toHaveLength(1); expect(n.parent.messages).toEqual([]);
    expect(n.parent.widget).toBeUndefined();
  });

  test("sending advances immediately to other questions and failure preserves the exact browser answer", async () => {
    const n = questionNetwork(); const browser = dashboard(n.parent.events);
    const child = n.child();
    await child.ask([question("slow"), question("independent")]);
    let release!: () => void;
    n.holdAnswer = () => new Promise<void>(resolve => { release = resolve; });
    const open = n.parent.open();
    n.parent.key("slow answer"); n.parent.key(ENTER);
    expect(n.parent.text()).toContain("independent");
    expect(n.parent.text()).not.toContain("Decide slow?");
    expect(n.parent.widget?.join(" ")).toContain("sending");
    // An unrelated queue refresh must not re-offer the in-flight question.
    await n.parent.ask([question("unrelated")]);
    expect([...browser.pending.values()].some(({ prompt }) => prompt.question === "/worker-a — slow")).toBe(false);
    n.answerError = true; release(); await flushChannel();
    expect(n.parent.text()).toContain("independent");
    expect(n.parent.notifications.join(" ")).toContain("worker paused");
    n.parent.key(ESC); await open;
    const prompt = [...browser.pending.values()].find(({ prompt }) => prompt.question === "/worker-a — slow")!.prompt;
    const exact = "browser answer\nwith multiple lines";
    browser.respond({ id: prompt.id, answer: exact, source: "dashboard" });
    await flushChannel();
    expect(n.parent.widget?.join(" ")).toContain("sending");
    release(); await flushChannel();
    const retry = n.parent.open(); n.parent.key(LEFT);
    expect(n.parent.text()).toContain("browser answer");
    expect(n.parent.text()).toContain("with multiple lines");
    expect(child.messages).toEqual([]); expect(n.parent.messages).toEqual([]);
    n.answerError = false; n.holdAnswer = undefined;
    n.parent.key(ENTER); await flushChannel();
    expect(child.messages).toHaveLength(1);
    expect(child.messages[0].content).toEndWith(`\n\n${exact}`);
    n.parent.key(ESC); await retry;
  });

  test("browser submits multiline child answer without consuming a sibling or parent question", async () => {
    const n = questionNetwork(); const browser = dashboard(n.parent.events);
    const child = n.child(); const sibling = n.child("other");
    await n.parent.ask([question("parent")]);
    await child.ask([question("child")]); await sibling.ask([question("other")]);
    const prompt = [...browser.pending.values()].find(({ prompt }) => prompt.question === "/worker-a — child")!.prompt;
    browser.respond({ id: prompt.id, answer: "line one\nline two", source: "dashboard" });
    await flushChannel();
    expect(child.messages).toHaveLength(1);
    expect(child.messages[0].content).toEndWith("line one\nline two");
    expect(sibling.messages).toEqual([]); expect(n.parent.messages).toEqual([]);
    expect(browser.pending.size).toBe(2);
  });

  test("presentation failures retain authoritative questions, while failed persistence publishes nothing", async () => {
    const n = questionNetwork(); const child = n.child();
    await flushChannel();
    child.failPersist = true;
    await expect(child.ask([question("not saved")])).rejects.toThrow("disk unavailable");
    expect(n.parent.widget).toBeUndefined();
    child.failPersist = false; n.publishError = true;
    await expect(child.ask([question("saved but unseen")])).rejects.toThrow("saved pending questions");
    expect(child.entries.at(-1).data.questions[0].title).toBe("saved but unseen");
    expect(n.parent.widget).toBeUndefined();
    n.publishError = false; child.emit("session_tree"); await flushChannel();
    expect(n.parent.widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
    n.parent.failPersist = true;
    await expect(child.ask([question("not confirmed")])).rejects.toThrow("presentation was not confirmed");
    expect(n.parent.entries.at(-1).data.questions).toHaveLength(1);
  });

  test("stale or cancelled child questions never become parent user input", async () => {
    const n = questionNetwork(); const child = n.child();
    const queued = await child.ask([question("scope")]);
    const cache = structuredClone(n.parent.entries);
    await child.cancel([queued.details.questions[0].id]);
    n.parent.entries = cache; n.parent.emit("session_tree");
    const open = n.parent.open(); n.parent.key("stale answer"); n.parent.key(ENTER);
    await flushChannel(); await open;
    expect(child.messages).toEqual([]); expect(n.parent.messages).toEqual([]);
    expect(n.parent.widget).toBeUndefined();
  });

  test("malformed snapshots and manager-less RPC never queue invisible questions", async () => {
    const n = questionNetwork(); n.child(); await flushChannel();
    const handler = n.parentHandlers.get("dotfiles-ask-user:v1")!;
    expect(() => handler({ kind: "sync", questions: [{ id: "x", title: "bad" }] }, {
      workerId: "x", taskName: "/x",
    })).toThrow("Invalid remote");
    // Only the manager can bind origin; tool input and child payloads cannot
    // smuggle another worker's destination through extra question properties.
    const origin = { workerId: "victim", taskName: "/victim" };
    expect(() => handler({ kind: "sync", questions: [{ id: "x", ...question("forged"), origin }] }, {
      workerId: "x", taskName: "/x",
    })).toThrow("Invalid remote");
    await expect(n.parent.ask([{ ...question("forged"), origin }])).rejects.toThrow("requires non-empty");
    const child = host(undefined, "rpc");
    await expect(child.ask([question("invisible")])).rejects.toThrow("requires interactive TUI");
    expect(child.entries).toEqual([]);
  });
});

describe("Dashboard question queue adapter", () => {
  test("event bus permits multiple listeners and unsubscribe", () => {
    const events = eventBus();
    const calls: string[] = [];
    const off = events.on("test", () => calls.push("a"));
    events.on("test", () => calls.push("b"));
    events.emit("test"); off(); events.emit("test");
    expect(calls).toEqual(["a", "b", "b"]);
  });

  test("both load orders discover and project persisted queues without awaiting answers", async () => {
    for (const dashboardFirst of [false, true]) {
      let browser: ReturnType<typeof dashboard>;
      const h = host(dashboardFirst ? (events) => { browser = dashboard(events); } : undefined);
      const queued = await h.ask([question("scope", ["Cancel", "Yes"]), question("format")]);
      if (!dashboardFirst) browser = dashboard(h.events);
      expect(browser!.pending.size).toBe(2);
      const prompt = [...browser!.pending.values()][0].prompt;
      expect(prompt).toMatchObject({
        pipeline: "dotfiles-ask-user", type: "select", question: "scope", options: ["Cancel", "Yes"],
        metadata: { kind: "queue-question", questionId: queued.details.questions[0].id, message: "Decide scope?" },
      });
      expect([...browser!.pending.values()][1].prompt.options).toEqual([]);
      browser!.ready();
      await flushBrowser();
      expect(browser!.pending.size).toBe(2);
      expect(browser!.adapters.size).toBe(1);
      h.emit("session_tree");
      await flushBrowser();
      expect(browser!.pending.size).toBe(2);
      expect(h.messages).toHaveLength(0);
      expect(h.customCalls).toBe(0);
    }
  });

  test("browser preserves literal Cancel and multiline steering; blank/navigation do not consume", async () => {
    const h = host(); const browser = dashboard(h.events);
    await h.ask([question("scope", ["Cancel"]), question("format")]);
    let id = [...browser.pending.keys()][0];
    browser.respond({ id, answer: "   ", source: "dashboard" });
    browser.respond({ id, cancelled: true, source: "dashboard" });
    await flushBrowser();
    expect(browser.pending.size).toBe(2);
    browser.respond({ id, answer: "Cancel", source: "dashboard" });
    await flushBrowser();
    expect(h.messages[0].content).toEndWith("Cancel");
    id = [...browser.pending.keys()][0];
    browser.respond({ id, answer: "line one\nline two", source: "dashboard" });
    await flushBrowser();
    expect(h.messages[1].content).toContain('Title: "format"\n\n> Decide format?\n\nline one\nline two');
    expect(browser.pending.size).toBe(0);
    expect(h.entries.at(-1).data.questions).toEqual([]);
  });

  test("either surface wins once, updates open panel, and preserves unrelated drafts", async () => {
    const h = host(); const browser = dashboard(h.events);
    await h.ask([question("scope"), question("format")]);
    const open = h.open(); h.key("terminal draft"); h.key(RIGHT); h.key("keep draft"); h.key(LEFT);
    const first = [...browser.pending.keys()][0];
    browser.respond({ id: first, answer: "browser answer", source: "dashboard" });
    // Terminal wins before the resolved Promise continuation runs.
    h.key(ENTER);
    await flushBrowser();
    expect(h.messages).toHaveLength(1);
    expect(h.messages[0].content).toEndWith("terminal draft");
    expect(h.text()).toContain("keep draft");
    expect(browser.pending.size).toBe(1);
    const second = [...browser.pending.keys()][0];
    browser.respond({ id: second, answer: "browser wins", source: "dashboard" });
    await flushBrowser(); await open;
    h.key(ENTER);
    expect(h.messages).toHaveLength(2);
    expect(browser.pending.size).toBe(0);
    expect(h.closed).toBe(1);
  });

  test("failed persistence leaves browser projection and cancellation state intact", async () => {
    const h = host(); const browser = dashboard(h.events);
    h.failPersist = true;
    await expect(h.ask([question("not published")])).rejects.toThrow("disk unavailable");
    expect(browser.pending.size).toBe(0);
    h.failPersist = false;
    const result = await h.ask([question("keep"), question("remove")]);
    const ids = result.details.questions.map((q: any) => q.id);
    h.failPersist = true;
    await expect(h.cancel([ids[1]])).rejects.toThrow("disk unavailable");
    expect(browser.pending.size).toBe(2);
    h.failPersist = false;
    await h.cancel([ids[1]]);
    await flushBrowser();
    expect(browser.pending.size).toBe(1);
    expect(h.messages).toHaveLength(0);
    expect([...browser.pending.values()][0].prompt.metadata.questionId).toBe(ids[0]);
  });

  test("dispatch rejection republishes for retry; post-dispatch save failure never offers duplicate", async () => {
    const h = host(); const browser = dashboard(h.events);
    await h.ask([question("scope")]);
    const first = [...browser.pending.keys()][0];
    h.failSend = true;
    browser.respond({ id: first, answer: "retry", source: "dashboard" });
    await flushBrowser();
    expect(h.messages).toHaveLength(0);
    expect(h.notifications.at(-1)).toContain("dispatch unavailable");
    expect(browser.pending.size).toBe(1);
    const retry = [...browser.pending.keys()][0];
    expect(retry).not.toBe(first);
    h.failSend = false; h.failPersist = true;
    browser.respond({ id: retry, answer: "accepted", source: "dashboard" });
    await flushBrowser();
    expect(h.messages).toHaveLength(1);
    expect(h.notifications.at(-1)).toContain("answer dispatched, but saving pending state failed");
    expect(browser.pending.size).toBe(0);
    await h.open();
    expect(h.notifications.at(-1)).toBe("No pending questions.");
  });

  test("branch replacement projects only selected snapshots and stale setters stay detached", async () => {
    const h = host(); const browser = dashboard(h.events);
    await h.ask([question("old branch")]);
    const oldId = [...browser.pending.keys()][0];
    const oldAdapter = browser.adapters.get("dotfiles-ask-user");
    browser.respond({ id: oldId, answer: "old answer", source: "dashboard" });
    h.entries = [{ type: "custom", customType: "dotfiles-ask-user", data: {
      version: 1, questions: [{ id: "selected-branch-question", ...question("selected branch") }],
    } }];
    h.emit("session_tree");
    let staleCancelled = 0;
    oldAdapter.setCancel(() => { staleCancelled++; });
    await flushBrowser();
    expect(h.messages).toHaveLength(0);
    expect(browser.pending.size).toBe(1);
    expect([...browser.pending.values()][0].prompt.metadata.questionId).toBe("selected-branch-question");
    await h.cancel(["selected-branch-question"]);
    expect(browser.pending.size).toBe(0);
    expect(staleCancelled).toBe(0);
  });

  test("bus-only cancellation leaves queue authoritative and discovery reconstructs presentation", async () => {
    const h = host(); const browser = dashboard(h.events);
    const result = await h.ask([question("scope")]);
    browser.cancel([...browser.pending.keys()][0]);
    await flushBrowser();
    expect(h.entries.at(-1).data.questions[0].id).toBe(result.details.questions[0].id);
    expect(h.widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
    browser.ready();
    expect(browser.pending.size).toBe(1);
    expect(h.messages).toHaveLength(0);
  });

  test("late replies and adapters cannot touch a restored same-ID incarnation or shutdown", async () => {
    const h = host(); const browser = dashboard(h.events);
    await h.ask([question("scope")]);
    const first = [...browser.pending.keys()][0];
    const oldAdapter = browser.adapters.get("dotfiles-ask-user");
    browser.respond({ id: first, answer: "stale", source: "dashboard" });
    h.emit("session_tree");
    await flushBrowser();
    expect(h.messages).toHaveLength(0);
    expect(browser.pending.size).toBe(1);
    expect(oldAdapter.onRequest({ id: "forged", pipeline: "dotfiles-ask-user", metadata: {
      kind: "queue-question", questionId: h.entries.at(-1).data.questions[0].id,
    } })).toBeUndefined();
    browser.respond({ id: [...browser.pending.keys()][0], answer: "shutdown stale", source: "dashboard" });
    h.emit("session_shutdown");
    await flushBrowser();
    expect(h.messages).toHaveLength(0);
    expect(browser.pending.size).toBe(0);
    h.emit("session_start");
    expect(browser.pending.size).toBe(1);
    browser.respond({ id: [...browser.pending.keys()][0], answer: "fresh", source: "dashboard" });
    await flushBrowser();
    expect(h.messages).toHaveLength(1);
  });
});
