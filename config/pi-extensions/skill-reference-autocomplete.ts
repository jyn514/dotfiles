import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type {
  AutocompleteItem,
  AutocompleteProvider,
} from "@earendil-works/pi-tui";

const INLINE_SKILL_PREFIX = /(?:^|[ \t])(#(?:[A-Za-z0-9._-]*))$/;

function inlineSkillPrefix(
  lines: string[],
  cursorLine: number,
  cursorCol: number,
): string | undefined {
  const beforeCursor = (lines[cursorLine] ?? "").slice(0, cursorCol);
  return beforeCursor.match(INLINE_SKILL_PREFIX)?.[1];
}

export function createSkillReferenceAutocompleteProvider(
  current: AutocompleteProvider,
): AutocompleteProvider {
  return {
    triggerCharacters: [...new Set([...(current.triggerCharacters ?? []), "#"])],

    async getSuggestions(lines, cursorLine, cursorCol, options) {
      const prefix = inlineSkillPrefix(lines, cursorLine, cursorCol);
      if (!prefix) {
        return current.getSuggestions(lines, cursorLine, cursorCol, options);
      }

      const skillPrefix = `/skill:${prefix.slice(1)}`;
      const suggestions = await current.getSuggestions(
        [skillPrefix],
        0,
        skillPrefix.length,
        { ...options, force: false },
      );
      const items = suggestions?.items.filter((item) => item.value.startsWith("skill:"));
      if (!items || items.length === 0) return null;

      return { items, prefix };
    },

    applyCompletion(lines, cursorLine, cursorCol, item: AutocompleteItem, prefix) {
      if (!prefix.startsWith("#") || !item.value.startsWith("skill:")) {
        return current.applyCompletion(lines, cursorLine, cursorCol, item, prefix);
      }

      const currentLine = lines[cursorLine] ?? "";
      const beforePrefix = currentLine.slice(0, cursorCol - prefix.length);
      const afterCursor = currentLine.slice(cursorCol);
      const suffix = /^\s/.test(afterCursor) ? "" : " ";
      const completion = `/${item.value}${suffix}`;
      const newLines = [...lines];
      newLines[cursorLine] = beforePrefix + completion + afterCursor;

      return {
        lines: newLines,
        cursorLine,
        cursorCol: beforePrefix.length + completion.length,
      };
    },

    shouldTriggerFileCompletion(lines, cursorLine, cursorCol) {
      return current.shouldTriggerFileCompletion?.(lines, cursorLine, cursorCol) ?? true;
    },
  };
}

export default function skillReferenceAutocomplete(pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    ctx.ui.addAutocompleteProvider(createSkillReferenceAutocompleteProvider);
  });
}
