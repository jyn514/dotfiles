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
}, { additionalProperties: false });
const Parameters = Type.Object({ questions: Type.Array(QuestionSchema, { minItems: 1 }) });
export type AskUserInput = Static<typeof Parameters>;
const CancelParameters = Type.Object({
  question_ids: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
});
export type CancelAskUserInput = Static<typeof CancelParameters>;
const OriginSchema = Type.Object({
  workerId: Type.String({ minLength: 1 }),
  taskName: Type.String({ minLength: 1 }),
  sessionId: Type.Optional(Type.String({ minLength: 1 })),
});
type Origin = Static<typeof OriginSchema>;
const LocalQuestionSchema = Type.Object({ id: Type.String({ minLength: 1 }), ...QuestionSchema.properties }, { additionalProperties: false });
const PendingSchema = Type.Object({
  ...LocalQuestionSchema.properties,
  origin: Type.Optional(OriginSchema),
  remoteId: Type.Optional(Type.String({ minLength: 1 })),
});
type PendingQuestion = Static<typeof PendingSchema>;
const SnapshotSchema = Type.Union([
  Type.Object({ version: Type.Literal(1), questions: Type.Array(LocalQuestionSchema) }),
  Type.Object({ version: Type.Literal(2), questions: Type.Array(PendingSchema) }),
]);
const ENTRY = "dotfiles-ask-user";
const CHANNEL_EVENT = "subagents:extension-channel:v1";
const CHANNEL = "dotfiles-ask-user:v1";

// Structural extension-channel contract: no runtime import from the optional
// subagent package. The manager supplies origin identity, never the payload.
interface ChildEndpoint {
  version: 1;
  role: "child";
  register(channel: string, handler: (payload: unknown) => unknown | Promise<unknown>): () => void;
  request(channel: string, payload: unknown): Promise<unknown>;
}
interface ParentEndpoint {
  version: 1;
  role: "parent";
  register(channel: string, handler: (payload: unknown, origin: Origin) => unknown | Promise<unknown>): () => void;
  request(workerId: string, channel: string, payload: unknown): Promise<unknown>;
}
type Endpoint = ChildEndpoint | ParentEndpoint;
const SyncSchema = Type.Object({ kind: Type.Literal("sync"), questions: Type.Array(LocalQuestionSchema) }, { additionalProperties: false });
const AnswerSchema = Type.Object({
  kind: Type.Literal("answer"), id: Type.String({ minLength: 1 }), answer: Type.String({ minLength: 1 }),
}, { additionalProperties: false });

// Structural seam only: Dashboard is optional and never imported at runtime.
interface BrowserResponse { id: string; answer?: string; cancelled?: boolean; source: string }
interface BrowserRequest {
  id: string;
  pipeline: string;
  type: string;
  question: string;
  options?: string[];
  metadata?: Record<string, unknown>;
}
type RequestBrowser = (request: Omit<BrowserRequest, "id">) => Promise<BrowserResponse>;

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
    private readonly submitAnswer: (question: PendingQuestion, answer: string) => void | Promise<void>,
    private readonly submitting: ReadonlySet<string>,
    private readonly reportAsyncError: (error: unknown) => void,
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

  update(): void {
    if (this.closed) return;
    this.load();
    this.refresh();
  }

  private available(): PendingQuestion[] {
    return this.state.pending.filter(q => !q.origin || !this.submitting.has(q.id));
  }

  private current(): PendingQuestion {
    const available = this.available();
    return available.find((q) => q.id === this.state.viewed) ?? available[0];
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
    const available = this.available();
    const index = available.findIndex((q) => q.id === this.current().id);
    this.state.viewed = available[(index + direction + available.length) % available.length].id;
    this.load();
  }

  private submit(answer: string): void {
    if (!answer.trim()) { this.error = "Enter a non-empty answer."; return; }
    try {
      const question = this.current();
      const result = this.submitAnswer(question, answer);
      if (result) void result.then(() => {
        if (!this.closed) { this.load(); this.refresh(); }
      }).catch((error) => { this.reportAsyncError(error); });
      // In-flight answers stay authoritative in the queue, but no longer block
      // the panel. Advance now, or close if every remaining answer is sending.
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
    if (this.closed) return;
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
    const available = this.available();
    const index = available.findIndex((q) => q.id === question.id);
    const lines: string[] = [];
    const add = (text: string) => lines.push(...wrapTextWithAnsi(text, Math.max(1, width)));
    add(this.theme.fg("accent", this.theme.bold(`Question ${index + 1} of ${available.length} — ${question.origin ? `${question.origin.taskName} — ` : ""}${question.title}`)));
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
  let activeContext: ExtensionContext | undefined;
  let requestBrowser: RequestBrowser | undefined;
  let browserEpoch = 0;
  let cancelBrowser: ((id: string) => void) | undefined;
  const browserIds = new Map<string, string>(); // queue ID -> disposable bus ID
  const submitting = new Set<string>();
  let endpoint: Endpoint | undefined;
  let unregisterChannel: (() => void) | undefined;
  let publishing = Promise.resolve();

  const dismissBrowser = (id: string) => {
    const promptId = browserIds.get(id);
    browserIds.delete(id);
    if (promptId) cancelBrowser?.(promptId);
  };
  const detachBrowser = () => {
    browserEpoch++;
    for (const id of browserIds.keys()) dismissBrowser(id);
    cancelBrowser = undefined;
    requestBrowser = undefined;
  };

  const publishBrowser = () => {
    if (!requestBrowser || !activeContext || activeContext.mode !== "tui" ||
        sessionId !== activeContext.sessionManager.getSessionId()) return;
    const epoch = browserEpoch;
    const currentGeneration = generation;
    const ctx = activeContext;
    for (const question of state.pending) {
      if (browserIds.has(question.id) || submitting.has(question.id)) continue;
      try {
        // onRequest synchronously captures the bus-minted ID. No component claim:
        // Dashboard's native SelectRenderer owns browser rendering.
        const result = requestBrowser({
          pipeline: ENTRY, type: "select", question: question.origin ? `${question.origin.taskName} — ${question.title}` : question.title,
          options: question.options ?? [],
          metadata: { kind: "queue-question", questionId: question.id, message: question.question },
        });
        void result.then(async (response) => {
          if (epoch !== browserEpoch || currentGeneration !== generation) return;
          if (browserIds.get(question.id) !== response.id) return;
          browserIds.delete(question.id);
          // Dismissal is not cancellation of the authoritative queue.
          if (response.cancelled) return;
          const answer = response.answer ?? "";
          if (question.origin && answer.trim()) {
            state.drafts.set(question.id, { text: answer, option: 0, editing: true });
          }
          try { await submitAnswer(question, answer, ctx, currentGeneration); }
          catch (error) {
            ctx.ui.notify(`ask_user: not submitted: ${String(error)}. Retry in the question panel or browser.`, "error");
          }
          // A consumed browser prompt must be recreated after rejected dispatch.
          publishBrowser();
        }).catch((error) => {
          if (epoch !== browserEpoch || currentGeneration !== generation) return;
          dismissBrowser(question.id);
          ctx.ui.notify(`ask_user: browser question failed: ${String(error)}`, "error");
        });
      } catch (error) {
        dismissBrowser(question.id);
        ctx.ui.notify(`ask_user: browser question failed: ${String(error)}`, "error");
      }
    }
  };

  pi.events.on("prompt:set-bus-request", (payload: unknown) => {
    const request = (payload as { request?: RequestBrowser } | undefined)?.request;
    if (typeof request !== "function" || !activeContext) return;
    detachBrowser();
    requestBrowser = request;
    const epoch = browserEpoch;
    const currentGeneration = generation;
    pi.events.emit("prompt:register-adapter", {
      name: ENTRY,
      setRespond(_respond: (response: BrowserResponse) => void) { /* Promise is the single response path. */ },
      setCancel(cancel: (id: string) => void) {
        if (epoch === browserEpoch) cancelBrowser = cancel;
      },
      onRequest(prompt: BrowserRequest) {
        if (epoch !== browserEpoch || currentGeneration !== generation ||
            prompt.pipeline !== ENTRY || prompt.metadata?.kind !== "queue-question") return;
        const id = prompt.metadata.questionId;
        if (typeof id !== "string" || !state.pending.some((q) => q.id === id)) return;
        browserIds.set(id, prompt.id);
        return {};
      },
      onResponse(_response: BrowserResponse) { /* request promise owns submission. */ },
      onCancel(_id: string) { /* request promise handles non-authoritative dismissal. */ },
    });
    publishBrowser();
  });

  const status = (ctx: ExtensionContext) => {
    if (ctx.mode !== "tui") return;
    const pending = state.pending.filter(q => !submitting.has(q.id)).length;
    const parts: string[] = [];
    if (submitting.size) parts.push(`${submitting.size} answer(s) sending…`);
    if (pending) parts.push(`${pending} pending question(s) · Alt+A to answer`);
    ctx.ui.setWidget("ask-user", parts.length ? [parts.join(" · ")] : undefined, { placement: "aboveEditor" });
  };
  // Older readers treat every v1 question as local user input. Mark snapshots
  // containing remote projections v2 so they refuse rather than misroute answers.
  const persist = (questions: PendingQuestion[]) => pi.appendEntry(ENTRY, {
    version: questions.some(q => q.origin) ? 2 : 1, questions,
  });
  const reset = () => {
    generation++;
    unregisterChannel?.();
    unregisterChannel = undefined;
    publishing = Promise.resolve();
    submitting.clear();
    detachBrowser();
    activeContext = undefined;
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
    activeContext = ctx;
    status(ctx);
    pi.events.emit("prompt:request-bus", undefined);
    connectChannel();
    pi.events.emit(CHANNEL_EVENT, { version: 1, provide: useEndpoint });
  };
  const refreshQueue = () => {
    if (activeContext) status(activeContext);
    panel?.update();
    publishBrowser();
  };
  // Publish immutable snapshots in order. The child transcript owns the queue;
  // the parent's persisted copy is presentation only and cannot answer itself.
  const publishQueue = (): Promise<void> => {
    const connection = endpoint;
    if (connection?.role !== "child") return Promise.resolve();
    const currentGeneration = generation;
    const payload = { kind: "sync", questions: state.pending.filter(q => !q.origin).map(q => structuredClone(q)) };
    const operation = publishing.catch(() => {}).then(async () => {
      if (generation !== currentGeneration || endpoint !== connection) throw new Error("Question session changed before publication");
      const result = await connection.request(CHANNEL, payload);
      if (!result || typeof result !== "object" || (result as { status?: unknown }).status !== "presented") {
        throw new Error("Parent did not confirm question presentation");
      }
    });
    publishing = operation;
    return operation;
  };
  const connectChannel = () => {
    unregisterChannel?.();
    unregisterChannel = undefined;
    const connection = endpoint;
    if (!connection || !activeContext) return;
    const ctx = activeContext;
    const currentGeneration = generation;
    const current = () => generation === currentGeneration && activeContext === ctx
      && sessionId === ctx.sessionManager.getSessionId();
    if (connection.role === "parent") {
      if (ctx.mode !== "tui") return;
      unregisterChannel = connection.register(CHANNEL, (payload, origin) => {
        if (!current()) throw new Error("Question presentation session is not active");
        if (!Check(SyncSchema, payload) || !Check(OriginSchema, origin)
          || payload.questions.some(q => !q.title.trim() || !q.question.trim() || q.options?.some(o => !o.trim()))
          || new Set(payload.questions.map(q => q.id)).size !== payload.questions.length) {
          throw new Error("Invalid remote question snapshot");
        }
        // Forks can retain question IDs. Namespace presentation IDs by worker,
        // while answers retain the original ID in the child's transcript.
        const incoming = payload.questions.map(q => ({ ...structuredClone(q),
          id: `${origin.workerId}/${q.id}`, remoteId: q.id, origin: structuredClone(origin) }));
        const pending = [...state.pending.filter(q => q.origin?.workerId !== origin.workerId), ...incoming];
        persist(pending);
        const kept = new Set(pending.map(q => q.id));
        for (const q of state.pending) if (!kept.has(q.id)) { state.drafts.delete(q.id); dismissBrowser(q.id); }
        const viewedIndex = state.pending.findIndex(q => q.id === state.viewed);
        state.pending = pending;
        if (state.viewed && !kept.has(state.viewed)) state.viewed = pending[Math.max(0, viewedIndex) % Math.max(1, pending.length)]?.id;
        refreshQueue();
        return { status: "presented" };
      });
    } else {
      unregisterChannel = connection.register(CHANNEL, async payload => {
        if (!current()) throw new Error("Question session is not active");
        if (!Check(AnswerSchema, payload) || !payload.answer.trim()) throw new Error("Invalid question answer");
        const question = state.pending.find(q => !q.origin && q.id === payload.id);
        if (!question) return { status: "not-pending" };
        submitAnswer(question, payload.answer, ctx, currentGeneration);
        // Dispatch already happened. A failed presentation update must not make
        // the caller offer duplicate submission of an accepted user answer.
        void publishQueue().catch(error => ctx.ui.notify(`ask_user: answer dispatched; presentation update failed: ${String(error)}`, "error"));
        return { status: "dispatched" };
      });
      // Never await a human answer or require the child process to stay alive.
      void publishQueue().catch(error => ctx.ui.notify(`ask_user: pending questions not presented: ${String(error)}`, "error"));
    }
  };
  const useEndpoint = (value: Endpoint) => {
    if (value?.version !== 1 || !["child", "parent"].includes(value.role)
      || typeof value.register !== "function" || typeof value.request !== "function") return;
    // A child can itself load the manager extension. Its questions still go up
    // to its owning UI, not to a headless parent endpoint in the same process.
    if (activeContext?.mode === "rpc" && value.role !== "child") return;
    if (endpoint === value && unregisterChannel) return;
    endpoint = value;
    connectChannel();
  };
  pi.events.on(CHANNEL_EVENT, (event: { version?: number; endpoint?: Endpoint }) => {
    if (event?.version === 1 && event.endpoint) useEndpoint(event.endpoint);
  });
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
    description: "Queue questions and return IDs immediately. Answers arrive later as user steering messages with question IDs. Continue only independent work; silence is not an answer or permission.",
    promptSnippet: "Ask questions asynchronously; returns IDs, not answers",
    promptGuidelines: [
      "Use the human-review-packets skill for consequential approvals or questions that require substantial context to judge. Ask simple preference questions, routine confirmations, and requests for missing facts directly.",
      "Use cancel_ask_user to remove questions made obsolete by later work.",
    ],
    parameters: Parameters,
    async execute(_callId, params, signal, _onUpdate, ctx) {
      if (ctx.mode !== "tui" && !(ctx.mode === "rpc" && endpoint?.role === "child")) {
        throw new Error("ask_user requires interactive TUI mode or a connected subagent question channel; no questions were queued.");
      }
      if (signal?.aborted) throw new Error("ask_user cancelled; no questions were queued.");
      if (sessionId !== ctx.sessionManager.getSessionId()) throw new Error("ask_user session is not active; no questions were queued.");
      // Parse again because tool_call handlers can mutate arguments after Pi validation.
      if (!Check(Parameters, params) || params.questions.some((q) => !q.title.trim() || !q.question.trim() || q.options?.some((o) => !o.trim()))) {
        throw new Error("ask_user requires non-empty titles, questions and option strings, with no extra question properties.");
      }
      const questions = params.questions.map((q) => ({ ...structuredClone(q), id: randomUUID() }));
      const pending = [...state.pending, ...questions];
      persist(pending); // Do not publish questions if persistence rejects synchronously.
      state.pending = pending;
      status(ctx);
      panel?.invalidate();
      publishBrowser();
      if (ctx.mode === "rpc") {
        try { await publishQueue(); }
        catch (error) { throw new Error(`ask_user saved pending questions ${questions.map(q => q.id).join(", ")}, but presentation was not confirmed: ${String(error)}`); }
      }
      // setWidget requests a host render, including an already open custom panel.
      return {
        content: [{ type: "text", text: `Queued questions: ${questions.map((q) => q.id).join(", ")}. Answers will arrive later as user messages. Continue only independent work; silence is not permission.` }],
        details: { questions },
      };
    },
  });

  pi.registerTool({
    name: "cancel_ask_user",
    label: "Cancel pending questions",
    description: "Cancel pending ask_user questions by ID in the active session. Removes their prompts and drafts; does not recall dispatched answers or grant permission. Returns cancelled and not-pending IDs.",
    promptSnippet: "Cancel obsolete pending ask_user questions by ID",
    parameters: CancelParameters,
    async execute(_callId, params, signal, _onUpdate, ctx) {
      if (ctx.mode !== "tui" && !(ctx.mode === "rpc" && endpoint?.role === "child")) {
        throw new Error("cancel_ask_user requires interactive TUI mode or a connected subagent question channel; no questions were cancelled.");
      }
      if (signal?.aborted) throw new Error("cancel_ask_user aborted; no questions were cancelled.");
      if (sessionId !== ctx.sessionManager.getSessionId()) throw new Error("cancel_ask_user session is not active; no questions were cancelled.");
      if (!Check(CancelParameters, params) || params.question_ids.some((id) => !id.trim())) {
        throw new Error("cancel_ask_user requires non-empty question IDs.");
      }
      const ids = [...new Set(params.question_ids)];
      const pendingIds = new Set(state.pending.filter(q => !q.origin).map((q) => q.id));
      const cancelled = ids.filter((id) => pendingIds.has(id));
      const notPending = ids.filter((id) => !pendingIds.has(id));
      if (cancelled.length) {
        const removed = new Set(cancelled);
        const pending = state.pending.filter((q) => !removed.has(q.id));
        persist(pending); // Keep prompts and drafts intact if saving fails.
        state.pending = pending;
        for (const id of cancelled) { state.drafts.delete(id); dismissBrowser(id); }
        if (state.viewed && removed.has(state.viewed)) state.viewed = undefined;
        panel?.update(); // Switch a cancelled selection, or close an empty panel now.
        status(ctx);
        if (ctx.mode === "rpc") {
          try { await publishQueue(); }
          catch (error) { throw new Error(`cancel_ask_user saved cancellation, but presentation was not confirmed: ${String(error)}`); }
        }
      }
      return {
        content: [{ type: "text", text: `Cancelled questions: ${cancelled.join(", ") || "none"}. Not pending: ${notPending.join(", ") || "none"}. Cancellation is not an answer or permission; dispatched answers cannot be recalled.` }],
        details: { cancelled, notPending },
      };
    },
  });

  const submitAnswer = (question: PendingQuestion, answer: string, ctx: ExtensionContext, expectedGeneration: number): void | Promise<void> => {
    if (expectedGeneration !== generation || sessionId !== ctx.sessionManager.getSessionId()) {
      throw new Error("Session changed");
    }
    if (!answer.trim()) throw new Error("Enter a non-empty answer");
    if (submitting.has(question.id)) throw new Error("Question submission in progress");
    if (!state.pending.some((q) => q.id === question.id)) throw new Error("Question is no longer pending");
    if (question.origin) {
      const connection = endpoint;
      if (connection?.role !== "parent" || !question.remoteId) throw new Error("Subagent question channel is unavailable");
      submitting.add(question.id);
      if (state.viewed === question.id) {
        const index = state.pending.findIndex(q => q.id === question.id);
        state.viewed = [...state.pending.slice(index + 1), ...state.pending.slice(0, index)]
          .find(q => !submitting.has(q.id))?.id;
      }
      dismissBrowser(question.id);
      refreshQueue();
      return connection.request(question.origin.workerId, CHANNEL, {
        kind: "answer", id: question.remoteId, answer,
      }).then(result => {
        if (!result || typeof result !== "object" || !["dispatched", "not-pending"].includes((result as { status: string }).status)) {
          throw new Error("Subagent did not confirm question answer");
        }
        if (expectedGeneration !== generation || sessionId !== ctx.sessionManager.getSessionId()) return;
        // The child owns acceptance. Never send this answer to the parent model.
        if ((result as { status: string }).status === "not-pending") {
          ctx.ui.notify(`ask_user: ${question.origin!.taskName}'s question is no longer pending; this answer was not sent.`, "info");
        }
        removeQuestion(question, ctx);
      }).finally(() => {
        if (expectedGeneration !== generation) return;
        submitting.delete(question.id);
        if (sessionId === ctx.sessionManager.getSessionId()) refreshQueue();
      });
    }
    // The void API accepts dispatch synchronously, not delivery. Pi reports
    // asynchronous failures; never await or invent an acknowledgement.
    const body = `${question.question.split("\n").map((line) => `> ${line}`).join("\n")}\n\n${answer}`;
    submitting.add(question.id);
    try { pi.sendUserMessage(`Answer to ask_user ${question.id}\nTitle: ${JSON.stringify(question.title)}\n\n${body}`, { deliverAs: "steer" }); }
    finally { submitting.delete(question.id); }
    if (expectedGeneration !== generation) return;
    removeQuestion(question, ctx);
  };

  const removeQuestion = (question: PendingQuestion, ctx: ExtensionContext) => {
    const index = state.pending.findIndex((q) => q.id === question.id);
    if (index < 0) return; // A child snapshot may already remove its projection.
    state.pending = state.pending.filter((q) => q.id !== question.id);
    state.drafts.delete(question.id);
    dismissBrowser(question.id);
    state.viewed = state.pending[index % Math.max(1, state.pending.length)]?.id;
    try { persist(state.pending); }
    catch (error) {
      // Dispatch already happened: do not offer duplicate submission.
      ctx.ui.notify(`ask_user: answer dispatched, but saving pending state failed: ${String(error)}. Reload may restore this question.`, "error");
    }
    panel?.update();
    status(ctx);
  };

  pi.registerShortcut(Key.alt("a"), {
    description: "Answer pending questions",
    handler: async (ctx) => {
      if (ctx.mode !== "tui" || sessionId !== ctx.sessionManager.getSessionId()) return;
      if (opening) return;
      if (!state.pending.some(q => !submitting.has(q.id))) {
        ctx.ui.notify(submitting.size ? "Answers are still sending." : "No pending questions.", "info");
        return;
      }
      const openedGeneration = generation;
      const openedId = ++openingId;
      opening = true;
      try {
        await ctx.ui.custom<void>((tui, theme, keys, done) => {
          const currentPanel = new QuestionsPanel(state, theme, keys, tui, () => tui.requestRender(), () => {
            if (openedGeneration === generation && openedId === openingId) { panel = undefined; opening = false; }
            done();
          }, (question, answer) => submitAnswer(question, answer, ctx, openedGeneration), submitting, error => {
            if (openedGeneration !== generation || sessionId !== ctx.sessionManager.getSessionId()) return;
            ctx.ui.notify(`ask_user: not submitted: ${String(error)}. Answer preserved; reopen Alt+A to retry.`, "error");
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
