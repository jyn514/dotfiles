import {
  type ExtensionAPI,
  type ExtensionContext,
  getAgentDir,
  type Theme,
} from "@earendil-works/pi-coding-agent";
import { join } from "node:path";
import {
  type Component,
  type Focusable,
  Input,
  Key,
  matchesKey,
  SelectList,
  truncateToWidth,
} from "@earendil-works/pi-tui";
import {
  collectPromptHistory,
  listPromptHistoryFiles,
  loadPromptHistoryFiles,
  loadPromptHistoryWithRipgrep,
  mergePromptHistories,
  type PromptHistoryEntry,
  searchPromptHistory,
} from "./prompt-history-search-core.ts";

class PromptHistorySearch implements Component, Focusable {
  private readonly input = new Input();
  private list: SelectList;
  private loading = true;
  private _focused = false;

  constructor(
    private prompts: PromptHistoryEntry[],
    private readonly theme: Theme,
    initialQuery: string,
    done: (result: string | null) => void,
  ) {
    this.input.setValue(initialQuery);
    this.input.handleInput("\x1b[F");
    this.list = this.createList();
    this.input.onEscape = () => done(null);
    this.input.onSubmit = () => done(this.list.getSelectedItem()?.value ?? null);
  }

  get focused(): boolean {
    return this._focused;
  }

  set focused(value: boolean) {
    this._focused = value;
    this.input.focused = value;
  }

  handleInput(data: string): void {
    if (matchesKey(data, Key.up) || matchesKey(data, Key.down) || matchesKey(data, Key.ctrl("r"))) {
      this.list.handleInput(matchesKey(data, Key.ctrl("r")) ? "\x1b[B" : data);
      return;
    }

    const previousQuery = this.input.getValue();
    this.input.handleInput(data);
    if (this.input.getValue() !== previousQuery) {
      this.list = this.createList();
    }
  }

  setPrompts(prompts: PromptHistoryEntry[]): void {
    const selectedText = this.list.getSelectedItem()?.value;
    this.prompts = prompts;
    this.list = this.createList(selectedText);
  }

  finishLoading(): void {
    this.loading = false;
  }

  render(width: number): string[] {
    const lines = [
      truncateToWidth(this.theme.fg("accent", this.theme.bold("Search prompt history")), width),
      ...this.input.render(width),
    ];

    if (!this.list.getSelectedItem()) {
      const message = this.loading ? "Loading older prompts…" : "No matching prompts";
      lines.push(truncateToWidth(this.theme.fg(this.loading ? "dim" : "warning", message), width));
    } else {
      lines.push(...this.list.render(width));
    }

    const help = this.loading
      ? "loading older prompts… • type to filter • ↑↓/ctrl+r navigate • enter restore • esc cancel"
      : "type to filter • ↑↓/ctrl+r navigate • enter restore • esc cancel";
    lines.push(truncateToWidth(this.theme.fg("dim", help), width));
    return lines;
  }

  invalidate(): void {
    this.input.invalidate();
    this.list.invalidate();
  }

  private createList(selectedText?: string): SelectList {
    // Keep multi-term history search; SelectList's built-in filter is prefix-only.
    const prompts = searchPromptHistory(this.prompts, this.input.getValue());
    const list = new SelectList(prompts.map(({ text }) => ({
      value: text,
      label: text.replace(/\s+/g, " ").trim(),
    })), 10, {
      selectedPrefix: (text) => this.theme.fg("accent", text),
      selectedText: (text) => this.theme.fg("accent", text),
      description: (text) => this.theme.fg("dim", text),
      scrollInfo: (text) => this.theme.fg("dim", text),
      noMatch: (text) => this.theme.fg("warning", text),
    });
    list.setSelectedIndex(Math.max(0, prompts.findIndex(({ text }) => text === selectedText)));
    return list;
  }
}

const savedHistoryPromises = new Map<string | undefined, Promise<PromptHistoryEntry[]>>();

async function loadSavedPromptHistory(currentSessionFile?: string): Promise<PromptHistoryEntry[]> {
  let pending = savedHistoryPromises.get(currentSessionFile);
  if (!pending) {
    const sessionsDir = join(getAgentDir(), "sessions");
    pending = loadPromptHistoryWithRipgrep(sessionsDir, currentSessionFile)
      .catch(async () => loadPromptHistoryFiles(
        await listPromptHistoryFiles(sessionsDir),
        currentSessionFile,
      ))
      .catch((error) => {
        savedHistoryPromises.delete(currentSessionFile);
        throw error;
      });
    savedHistoryPromises.set(currentSessionFile, pending);
  }
  return pending;
}

async function searchHistory(ctx: ExtensionContext): Promise<void> {
  const current = collectPromptHistory(ctx.sessionManager.getBranch());
  let active = true;
  const result = await ctx.ui.custom<string | null>((tui, theme, _keybindings, done) => {
    const finish = (value: string | null) => {
      active = false;
      done(value);
    };
    const search = new PromptHistorySearch(current, theme, ctx.ui.getEditorText(), finish);
    void loadSavedPromptHistory(ctx.sessionManager.getSessionFile())
      .then((saved) => {
        if (!active) return;
        search.setPrompts(mergePromptHistories([current, saved]));
        search.finishLoading();
        tui.requestRender();
      })
      .catch(() => {
        if (!active) return;
        search.finishLoading();
        tui.requestRender();
      });
    return {
      get focused() { return search.focused; },
      set focused(value: boolean) { search.focused = value; },
      render: (width: number) => search.render(width),
      invalidate: () => search.invalidate(),
      handleInput(data: string) {
        search.handleInput(data);
        tui.requestRender();
      },
    };
  });

  if (typeof result === "string") {
    ctx.ui.setEditorText(result);
    // Closing custom UI requests a render before its promise resolves. Request one
    // afterward so the restored editor text is visible immediately.
    ctx.ui.setStatus("history-search", undefined);
  }
}

export default function promptHistorySearch(pi: ExtensionAPI): void {
  pi.registerShortcut(Key.ctrl("r"), {
    description: "Search previous prompts",
    handler: searchHistory,
  });

  pi.registerCommand("history-search", {
    description: "Search previous prompts",
    handler: async (_args, ctx) => searchHistory(ctx),
  });
}
