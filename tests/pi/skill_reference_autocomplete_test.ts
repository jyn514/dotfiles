import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type {
  AutocompleteItem,
  AutocompleteProvider,
  AutocompleteSuggestions,
} from "@earendil-works/pi-tui";
import skillReferenceAutocomplete, {
  createSkillReferenceAutocompleteProvider,
} from "../../config/pi-extensions/skill-reference-autocomplete";

const signal = new AbortController().signal;

function fakeProvider(
  suggestions: AutocompleteSuggestions | null = null,
): AutocompleteProvider & { calls: Array<{ lines: string[]; line: number; col: number; force?: boolean }> } {
  const calls: Array<{ lines: string[]; line: number; col: number; force?: boolean }> = [];
  return {
    calls,
    triggerCharacters: ["@"],
    async getSuggestions(lines, line, col, options) {
      calls.push({ lines, line, col, force: options.force });
      return suggestions;
    },
    applyCompletion(lines, cursorLine, cursorCol, item, prefix) {
      return {
        lines: [`delegated:${lines.join("|")}:${item.value}:${prefix}`],
        cursorLine,
        cursorCol,
      };
    },
  };
}

const skillSuggestions: AutocompleteSuggestions = {
  prefix: "/skill:arch",
  items: [
    { value: "skill:architecture-design", label: "skill:architecture-design" },
    { value: "model", label: "model" },
  ],
};

describe("inline skill autocomplete", () => {
  test("reuses built-in skill suggestions after prose", async () => {
    const current = fakeProvider(skillSuggestions);
    const provider = createSkillReferenceAutocompleteProvider(current);
    const text = "please use #arch";

    expect(await provider.getSuggestions([text], 0, text.length, { signal, force: true })).toEqual({
      prefix: "#arch",
      items: [skillSuggestions.items[0]],
    });
    expect(current.calls).toEqual([
      { lines: ["/skill:arch"], line: 0, col: 11, force: false },
    ]);
    expect(provider.triggerCharacters).toEqual(["@", "#"]);
  });

  test("works at the start of a later line", async () => {
    const provider = createSkillReferenceAutocompleteProvider(fakeProvider(skillSuggestions));
    const lines = ["first line", "#arch"];

    expect(await provider.getSuggestions(lines, 1, lines[1]!.length, { signal }))
      .toEqual({ prefix: "#arch", items: [skillSuggestions.items[0]] });
  });

  test("delegates unrelated and non-boundary contexts unchanged", async () => {
    const current = fakeProvider({ prefix: "fallback", items: [] });
    const provider = createSkillReferenceAutocompleteProvider(current);

    await provider.getSuggestions(["please /model"], 0, 13, { signal });
    await provider.getSuggestions(["word#arch"], 0, 9, { signal });

    expect(current.calls).toEqual([
      { lines: ["please /model"], line: 0, col: 13, force: undefined },
      { lines: ["word#arch"], line: 0, col: 9, force: undefined },
    ]);
  });

  test("returns no inline suggestions when no loaded skill matches", async () => {
    const provider = createSkillReferenceAutocompleteProvider(fakeProvider({
      prefix: "/skill:missing",
      items: [{ value: "model", label: "model" }],
    }));
    const text = "use #missing";

    expect(await provider.getSuggestions([text], 0, text.length, { signal })).toBeNull();
  });

  test("replaces only the inline token and adds required spacing", () => {
    const provider = createSkillReferenceAutocompleteProvider(fakeProvider());
    const item: AutocompleteItem = {
      value: "skill:architecture-design",
      label: "skill:architecture-design",
    };
    const text = "please use #arch";

    expect(provider.applyCompletion([text], 0, text.length, item, "#arch")).toEqual({
      lines: ["please use /skill:architecture-design "],
      cursorLine: 0,
      cursorCol: 38,
    });
  });

  test("does not duplicate existing whitespace after the cursor", () => {
    const provider = createSkillReferenceAutocompleteProvider(fakeProvider());
    const item = { value: "skill:architecture-design", label: "skill:architecture-design" };
    const text = "use #arch for this";
    const cursorCol = "use #arch".length;

    expect(provider.applyCompletion([text], 0, cursorCol, item, "#arch")).toEqual({
      lines: ["use /skill:architecture-design for this"],
      cursorLine: 0,
      cursorCol: 30,
    });
  });

  test("registers the provider wrapper at session start", () => {
    let sessionStart: ((event: unknown, ctx: unknown) => void) | undefined;
    const pi = {
      on(event: string, handler: (event: unknown, ctx: unknown) => void) {
        if (event === "session_start") sessionStart = handler;
      },
    } as unknown as ExtensionAPI;
    skillReferenceAutocomplete(pi);

    let registered: unknown;
    sessionStart?.({}, {
      ui: {
        addAutocompleteProvider(factory: unknown) {
          registered = factory;
        },
      },
    });

    expect(registered).toBe(createSkillReferenceAutocompleteProvider);
  });
});
