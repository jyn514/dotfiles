import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import {
  type Component, type Focusable, Editor, Key, type KeybindingsManager,
  matchesKey, truncateToWidth, type TUI, wrapTextWithAnsi,
} from "@earendil-works/pi-tui";
import { Type, type Static } from "typebox";
import { Check } from "typebox/value";

const QuestionSchema = Type.Object({
  title: Type.String({ minLength: 1 }),
  question: Type.String({ minLength: 1 }),
  options: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
});
const Parameters = Type.Object({ questions: Type.Array(QuestionSchema, { minItems: 1 }) });
export type AskUserInput = Static<typeof Parameters>;
const PendingSchema = Type.Object({ id: Type.String({ minLength: 1 }), ...QuestionSchema.properties });
type PendingQuestion = Static<typeof PendingSchema>;
const SnapshotSchema = Type.Object({ version: Type.Literal(1), questions: Type.Array(PendingSchema) });
const ENTRY = "dotfiles-ask-user";

interface Draft { text: string; option: number; editing: boolean }
interface QuestionsState {
  pending: PendingQuestion[];
  viewed?: string;
  drafts: Map<string, Draft>;
}

/** A fresh component per opening; queue, selection and drafts belong to the extension. */
class QuestionsPanel implements Component, Focusable {
  private editor: Editor;
  private loaded?: string;
  private _focused = false;
  private closed = false;
  private error?: string;

  constructor(
    private readonly state: QuestionsState,
    private readonly theme: Theme,
    private readonly keys: KeybindingsManager,
    private readonly tui: TUI,
    private readonly refresh: () => void,
    private readonly finish: () => void,
    private readonly submitAnswer: (question: PendingQuestion, answer: string) => void,
  ) {
    this.editor = this.createEditor();
    this.load();
  }

  private createEditor(): Editor {
    const theme = this.theme;
    const editor = new Editor(this.tui, {
      borderColor: (s) => theme.fg("accent", s),
      selectList: {
        selectedPrefix: (s) => theme.fg("accent", s),
        selectedText: (s) => theme.fg("accent", s),
        description: (s) => theme.fg("muted", s),
        scrollInfo: (s) => theme.fg("dim", s),
        noMatch: (s) => theme.fg("warning", s),
      },
    });
    // Editor's native submit clears its buffer before onSubmit. Keep control of
    // submission so a synchronous dispatch error cannot destroy the draft.
    editor.disableSubmit = true;
    editor.onChange = () => { this.draft().text = editor.getExpandedText(); };
    return editor;
  }

  get focused(): boolean { return this._focused; }
  set focused(value: boolean) {
    this._focused = value;
    this.editor.focused = value && this.draft().editing;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.finish();
  }

  private current(): PendingQuestion {
    return this.state.pending.find((q) => q.id === this.state.viewed) ?? this.state.pending[0];
  }

  private draft(): Draft {
    const question = this.current();
    if (!question) return { text: "", option: 0, editing: true };
    let draft = this.state.drafts.get(question.id);
    if (!draft) {
      draft = { text: "", option: 0, editing: !question.options?.length };
      this.state.drafts.set(question.id, draft);
    }
    return draft;
  }

  private load(): void {
    const question = this.current();
    if (!question) { this.close(); return; }
    this.state.viewed = question.id;
    if (this.loaded !== question.id) {
      this.loaded = question.id;
      // setText preserves Editor undo history; use a fresh editor on question
      // changes so undo cannot copy another question's text into this draft.
      this.editor = this.createEditor();
      this.editor.setText(this.draft().text);
      this.error = undefined;
    }
    this.editor.focused = this._focused && this.draft().editing;
  }

  private cycle(direction: -1 | 1): void {
    const index = this.state.pending.findIndex((q) => q.id === this.current().id);
    this.state.viewed = this.state.pending[(index + direction + this.state.pending.length) % this.state.pending.length].id;
    this.load();
  }

  private submit(answer: string): void {
    if (!answer.trim()) { this.error = "Enter a non-empty answer."; return; }
    try {
      this.submitAnswer(this.current(), answer);
      this.load();
    } catch (error) {
      // sendUserMessage is void: only synchronous rejection is observable here.
      this.error = `Not submitted: ${error instanceof Error ? error.message : String(error)}. Retry with Enter.`;
    }
    this.refresh();
  }

  handleInput(data: string): void {
    if (this.closed) return;
    this.load();
    if (matchesKey(data, Key.escape) || this.keys.matches(data, "tui.select.cancel")) {
      this.close();
    } else if (matchesKey(data, Key.alt("left"))) {
      this.cycle(-1);
    } else if (matchesKey(data, Key.alt("right"))) {
      this.cycle(1);
    } else {
      const draft = this.draft();
      const options = this.current().options ?? [];
      if (matchesKey(data, Key.tab) && options.length) {
        draft.editing = !draft.editing;
      } else if (draft.editing && this.keys.matches(data, "tui.input.submit")) {
        this.submit(this.editor.getExpandedText());
      } else if (draft.editing) {
        this.editor.handleInput(data);
        draft.text = this.editor.getExpandedText();
      } else if (this.keys.matches(data, "tui.select.up")) {
        draft.option = Math.max(0, draft.option - 1);
      } else if (this.keys.matches(data, "tui.select.down")) {
        draft.option = Math.min(options.length, draft.option + 1);
      } else if (this.keys.matches(data, "tui.select.confirm")) {
        if (draft.option === options.length) draft.editing = true;
        else this.submit(options[draft.option]);
      } else if (!data.startsWith("\x1b") && data.length > 0 && data.charCodeAt(0) >= 32) {
        draft.editing = true;
        this.editor.handleInput(data);
        draft.text = this.editor.getExpandedText();
      }
      this.editor.focused = this._focused && this.draft().editing;
    }
    this.refresh();
  }

  render(width: number): string[] {
    if (this.closed) return [];
    this.load();
    const question = this.current();
    if (!question) return [];
    const draft = this.draft();
    const index = this.state.pending.findIndex((q) => q.id === question.id);
    const lines: string[] = [];
    const add = (text: string) => lines.push(...wrapTextWithAnsi(text, Math.max(1, width)));
    add(this.theme.fg("accent", this.theme.bold(`Question ${index + 1} of ${this.state.pending.length} — ${question.title}`)));
    add(question.question);
    for (const [i, option] of [...(question.options ?? []), "Type a free answer…"].entries()) {
      if (!question.options?.length) break;
      add(`${!draft.editing && i === draft.option ? "›" : " "} ${option}`);
    }
    // Editor cannot wrap a double-width grapheme into a one-column buffer.
    if (draft.editing) lines.push(...this.editor.render(Math.max(4, width)));
    if (this.error) add(this.theme.fg("error", this.error));
    add(this.theme.fg("dim", "Alt+←/→ questions • ↑↓ options • Tab options/text • Enter submit • Esc close (keeps drafts)"));
    return lines.map((line) => truncateToWidth(line, Math.max(1, width)));
  }

  invalidate(): void { this.editor.invalidate(); }
}

export default function askUser(pi: ExtensionAPI): void {
  // Display-only: keep correlation metadata in the persisted steering message.
  // JSON keeps arbitrary multiline titles inside one unambiguous header line.
  pi.registerMarkdownTransformer((markdown, { messageType }) => {
    if (messageType !== "user") return markdown;
    const header = /^Answer to ask_user [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\nTitle: ("[^\n]*")\n\n(?=> )/.exec(markdown);
    if (!header) return markdown;
    try {
      if (typeof JSON.parse(header[1]) === "string") return markdown.slice(header[0].length);
    } catch { /* Not our encoded header. */ }
    return markdown;
  });

  const state: QuestionsState = { pending: [], drafts: new Map() };
  let panel: QuestionsPanel | undefined;
  let opening = false;
  let openingId = 0;
  let generation = 0;
  let sessionId: string | undefined;

  const status = (ctx: ExtensionContext) => {
    if (ctx.mode === "tui") ctx.ui.setWidget("ask-user", state.pending.length ? [`${state.pending.length} pending question(s) · Alt+A to answer`] : undefined, { placement: "aboveEditor" });
  };
  const persist = (questions: PendingQuestion[]) => pi.appendEntry(ENTRY, { version: 1, questions });
  const reset = () => {
    generation++;
    panel?.close();
    panel = undefined;
    opening = false;
    state.pending = [];
    state.viewed = undefined;
    state.drafts.clear();
  };
  const restore = (ctx: ExtensionContext) => {
    reset();
    sessionId = ctx.sessionManager.getSessionId();
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type !== "custom" || entry.customType !== ENTRY) continue;
      if (!Check(SnapshotSchema, entry.data)) {
        ctx.ui.notify("ask_user: invalid saved question state; not restoring questions.", "error");
        state.pending = [];
        continue;
      }
      state.pending = structuredClone(entry.data.questions);
    }
    status(ctx);
  };
  pi.on("session_start", (_event, ctx) => restore(ctx));
  pi.on("session_tree", (_event, ctx) => restore(ctx));
  pi.on("session_shutdown", (_event, ctx) => {
    reset();
    sessionId = undefined;
    status(ctx);
  });

  pi.registerTool({
    name: "ask_user",
    label: "Ask user asynchronously",
    description: "Queue questions and return IDs immediately. Answers arrive later as user steering messages. Continue only independent work; silence is not an answer or permission.",
    promptSnippet: "Ask questions asynchronously; returns IDs, not answers",
    promptGuidelines: ["After ask_user, continue only independent work; do not assume an answer or permission from silence. Answers arrive later as user steering messages with question IDs."],
    parameters: Parameters,
    async execute(_callId, params, signal, _onUpdate, ctx) {
      if (ctx.mode !== "tui") throw new Error("ask_user requires interactive TUI mode; no questions were queued.");
      if (signal?.aborted) throw new Error("ask_user cancelled; no questions were queued.");
      if (sessionId !== ctx.sessionManager.getSessionId()) throw new Error("ask_user session is not active; no questions were queued.");
      // Parse again because tool_call handlers can mutate arguments after Pi validation.
      if (!Check(Parameters, params) || params.questions.some((q) => !q.title.trim() || !q.question.trim() || q.options?.some((o) => !o.trim()))) {
        throw new Error("ask_user requires non-empty titles, questions and option strings.");
      }
      const questions = params.questions.map((q) => ({ ...structuredClone(q), id: randomUUID() }));
      const pending = [...state.pending, ...questions];
      persist(pending); // Do not publish questions if persistence rejects synchronously.
      state.pending = pending;
      status(ctx);
      panel?.invalidate();
      // setWidget requests a host render, including an already open custom panel.
      return {
        content: [{ type: "text", text: `Queued questions: ${questions.map((q) => q.id).join(", ")}. Answers will arrive later as user messages. Continue only independent work; silence is not permission.` }],
        details: { questions },
      };
    },
  });

  pi.registerShortcut(Key.alt("a"), {
    description: "Answer pending questions",
    handler: async (ctx) => {
      if (ctx.mode !== "tui" || sessionId !== ctx.sessionManager.getSessionId()) return;
      if (opening) return;
      if (!state.pending.length) { ctx.ui.notify("No pending questions.", "info"); return; }
      const openedGeneration = generation;
      const openedId = ++openingId;
      opening = true;
      try {
        await ctx.ui.custom<void>((tui, theme, keys, done) => {
          const currentPanel = new QuestionsPanel(state, theme, keys, tui, () => tui.requestRender(), () => {
            if (openedGeneration === generation && openedId === openingId) { panel = undefined; opening = false; }
            done();
          }, (question, answer) => {
            if (openedGeneration !== generation || sessionId !== ctx.sessionManager.getSessionId()) {
              throw new Error("Session changed");
            }
            // The void API accepts dispatch synchronously, not delivery. Pi reports
            // asynchronous failures; never await or invent an acknowledgement.
            const body = `${question.question.split("\n").map((line) => `> ${line}`).join("\n")}\n\n${answer}`;
            pi.sendUserMessage(`Answer to ask_user ${question.id}\nTitle: ${JSON.stringify(question.title)}\n\n${body}`, { deliverAs: "steer" });
            const index = state.pending.findIndex((q) => q.id === question.id);
            state.pending = state.pending.filter((q) => q.id !== question.id);
            state.drafts.delete(question.id);
            state.viewed = state.pending[index % Math.max(1, state.pending.length)]?.id;
            try { persist(state.pending); }
            catch (error) {
              // Dispatch already happened: do not offer duplicate submission.
              ctx.ui.notify(`ask_user: answer dispatched, but saving pending state failed: ${String(error)}. Reload may restore this question.`, "error");
            }
            status(ctx);
          });
          panel = currentPanel;
          return currentPanel;
        });
      } finally {
        if (openedGeneration === generation && openedId === openingId) { panel = undefined; opening = false; }
      }
    },
  });
}
