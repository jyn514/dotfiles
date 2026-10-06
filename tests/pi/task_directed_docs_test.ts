import { describe, expect, test } from "bun:test";
import taskDirectedDocs from "../../config/pi-agent/pi-extensions/task-directed-docs";

const legacyRules = `- When working on pi topics, read the docs and examples, and follow .md cross-references before implementing
- Always read pi .md files completely and follow links to related docs (e.g., tui.md for TUI API details)`;

function hook() {
  let handler: (event: {
    systemPrompt: string;
    systemPromptOptions: { sections: Record<string, string> };
  }) => unknown;
  taskDirectedDocs({
    on(name: string, callback: typeof handler) {
      expect(name).toBe("before_agent_start");
      handler = callback;
    },
  } as never);
  return handler!;
}

describe("task-directed Pi documentation", () => {
  test("replaces only the reading policy without forcing the prompt, including repeated runs", () => {
    const before = "Pi documentation:\n- Main documentation: /host/pi/README.md\n- When asked about extensions: docs/extensions.md";
    const after = "\n- Unrelated documentation advice";
    const docs = `${before}\n${legacyRules}${after}`;
    const event = {
      systemPrompt: `Base instructions.\n\n<docs>\n${docs}\n</docs>\n\n<rules>\nUnrelated rules\n</rules>`,
      systemPromptOptions: { sections: { other: "unrelated custom section" } as Record<string, string> },
    };
    const handler = hook();
    const original = event.systemPrompt;
    expect(handler(event)).toBeUndefined();
    const updated = event.systemPromptOptions.sections.docs;
    expect(updated).toStartWith(`${before}\n- Before implementing Pi-specific behavior,`);
    expect(updated).toContain("read the relevant documentation sections");
    expect(updated).toContain("Follow references when they define an API or constraint needed for the task");
    expect(updated).toContain("Read whole files only when the task requires understanding them as a whole");
    expect(updated).toEndWith(after);
    expect(updated).not.toContain("Always read pi .md files completely");
    expect(updated).not.toContain("follow .md cross-references before implementing");
    expect(event.systemPrompt).toBe(original);
    expect(event.systemPromptOptions.sections.other).toBe("unrelated custom section");
    // A later invocation sees Pi's re-rendered section, not a cached original.
    event.systemPrompt = `<docs>\n${updated}\n</docs>`;
    expect(handler(event)).toBeUndefined();
    expect(event.systemPromptOptions.sections.docs).toBe(updated);
    expect(updated.split("Before implementing Pi-specific behavior")).toHaveLength(2);
  });

  test("leaves custom prompts and unrecognized documentation policies unchanged", () => {
    const handler = hook();
    for (const systemPrompt of [
      "A custom prompt without generated docs.",
      "<docs>\nUser-selected documentation policy.\n</docs>",
    ]) {
      const event = { systemPrompt, systemPromptOptions: { sections: { other: "untouched" } } };
      expect(handler(event)).toBeUndefined();
      expect(event.systemPrompt).toBe(systemPrompt);
      expect(event.systemPromptOptions.sections).toEqual({ other: "untouched" });
    }
  });
});
