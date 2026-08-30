import { describe, expect, test } from "bun:test";
import systemPrompt, { showSystemPrompt } from "../../config/pi-extensions/system-prompt";

describe("system prompt viewer", () => {
  test("registers the system-prompt command", () => {
    const commands = new Map<string, { description: string }>();
    systemPrompt({
      registerCommand(name: string, command: { description: string }) {
        commands.set(name, command);
      },
    } as never);

    expect(commands.get("system-prompt")?.description).toBe(
      "Show the effective system prompt",
    );
  });

  test("shows the effective prompt and discards editor changes", async () => {
    const editorCalls: Array<[string, string]> = [];
    const ctx = {
      mode: "tui",
      getSystemPrompt: () => "loaded prompt",
      ui: {
        editor: async (title: string, content: string) => {
          editorCalls.push([title, content]);
          return "changed prompt";
        },
      },
    };

    await showSystemPrompt(ctx as never);

    expect(editorCalls).toEqual([[
      "Effective system prompt (edits are discarded)",
      "loaded prompt",
    ]]);
    expect(ctx.getSystemPrompt()).toBe("loaded prompt");
  });

  test("warns instead of opening a viewer outside interactive mode", async () => {
    const notifications: Array<[string, string]> = [];
    await showSystemPrompt({
      mode: "print",
      getSystemPrompt: () => "loaded prompt",
      ui: {
        editor: async () => { throw new Error("editor should not open"); },
        notify: (message: string, level: string) => notifications.push([message, level]),
      },
    } as never);

    expect(notifications).toEqual([[
      "The system prompt viewer is available only in interactive mode",
      "warning",
    ]]);
  });
});
