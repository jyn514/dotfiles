import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
  type Theme,
} from "@earendil-works/pi-coding-agent";
import {
  type Component,
  type Focusable,
  Input,
  Key,
  matchesKey,
  truncateToWidth,
} from "@earendil-works/pi-tui";
import {
  collectPromptHistory,
  mergePromptHistories,
  type PromptHistoryEntry,
  searchPromptHistory,
} from "./prompt-history-search-core.ts";

class PromptHistorySearch implements Component, Focusable {
  private readonly input = new Input();
  private filtered: PromptHistoryEntry[];
  private selected = 0;
  private _focused = false;

  constructor(
    private readonly prompts: PromptHistoryEntry[],
    private readonly theme: Theme,
    initialQuery: string,
    private readonly done: (result: string | null) => void,
  ) {
    this.input.setValue(initialQuery);
    this.input.handleInput("\x1b[F");
    this.filtered = searchPromptHistory(prompts, initialQuery);
    this.input.onEscape = () => done(null);
    this.input.onSubmit = () => this.select();
  }

  get focused(): boolean {
    return this._focused;
  }

  set focused(value: boolean) {
    this._focused = value;
    this.input.focused = value;
  }

  handleInput(data: string): void {
    if (matchesKey(data, Key.up)) {
      this.move(-1);
      return;
    }
    if (matchesKey(data, Key.down) || matchesKey(data, Key.ctrl("r"))) {
      this.move(1);
      return;
    }

    const previousQuery = this.input.getValue();
    this.input.handleInput(data);
    if (this.input.getValue() !== previousQuery) {
      this.filtered = searchPromptHistory(this.prompts, this.input.getValue());
      this.selected = 0;
    }
  }

  render(width: number): string[] {
    const lines = [
      truncateToWidth(this.theme.fg("accent", this.theme.bold("Search prompt history")), width),
      ...this.input.render(width),
    ];

    if (this.filtered.length === 0) {
      lines.push(truncateToWidth(this.theme.fg("warning", "No matching prompts"), width));
    } else {
      const maxVisible = 10;
      const start = Math.max(0, Math.min(this.selected - Math.floor(maxVisible / 2), this.filtered.length - maxVisible));
      const end = Math.min(start + maxVisible, this.filtered.length);
      for (let index = start; index < end; index++) {
        const normalized = this.filtered[index].text.replace(/\s+/g, " ").trim();
        const prefix = index === this.selected ? "› " : "  ";
        const text = truncateToWidth(`${prefix}${normalized}`, width);
        lines.push(index === this.selected ? this.theme.fg("accent", text) : text);
      }
    }

    lines.push(truncateToWidth(
      this.theme.fg("dim", "type to filter • ↑↓/ctrl+r navigate • enter restore • esc cancel"),
      width,
    ));
    return lines;
  }

  invalidate(): void {
    this.input.invalidate();
  }

  private move(direction: -1 | 1): void {
    if (this.filtered.length === 0) return;
    this.selected = (this.selected + direction + this.filtered.length) % this.filtered.length;
  }

  private select(): void {
    this.done(this.filtered[this.selected]?.text ?? null);
  }
}

async function loadPromptHistory(ctx: ExtensionContext): Promise<PromptHistoryEntry[]> {
  const currentSessionFile = ctx.sessionManager.getSessionFile();
  const histories: PromptHistoryEntry[][] = [
    collectPromptHistory(ctx.sessionManager.getBranch()),
  ];

  const sessions = await SessionManager.listAll();
  for (const session of sessions) {
    if (session.path === currentSessionFile) continue;
    try {
      histories.push(collectPromptHistory(SessionManager.open(session.path).getEntries()));
    } catch {
      // Session listing already tolerates damaged files. Skip any that fail on full open too.
    }
  }

  return mergePromptHistories(histories);
}

async function searchHistory(ctx: ExtensionContext): Promise<void> {
  ctx.ui.setStatus("history-search", "loading prompt history…");
  let prompts: PromptHistoryEntry[];
  try {
    prompts = await loadPromptHistory(ctx);
  } finally {
    ctx.ui.setStatus("history-search", undefined);
  }
  if (prompts.length === 0) {
    ctx.ui.notify("No previous prompts found", "info");
    return;
  }

  const result = await ctx.ui.custom<string | null>((tui, theme, _keybindings, done) => {
    const search = new PromptHistorySearch(prompts, theme, ctx.ui.getEditorText(), done);
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
