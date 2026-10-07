import { describe, expect, test } from "bun:test";
import systemPrompt, { showSystemPrompt } from "../../config/pi-agent/pi-extensions/system-prompt";
import { observeSystemPrompt, type SystemPromptSnapshot } from "../../config/pi-agent/pi-extensions/system-prompt-core";

const snapshot: SystemPromptSnapshot = {
  prompt: "prepared prompt",
  model: { provider: "fixture", id: "model" },
  capturedAt: "2026-10-07T12:00:00.000Z",
};

describe("system prompt viewer", () => {
  test("registers the system-prompt command", () => {
    const commands = new Map<string, { description: string }>();
    systemPrompt({
      on() {},
      registerCommand(name: string, command: { description: string }) {
        commands.set(name, command);
      },
    } as never);
    expect(commands.get("system-prompt")?.description).toBe("Show the last prepared system prompt");
  });

  test("shows the captured prompt, not the idle getter, and discards edits", async () => {
    const editorCalls: Array<[string, string]> = [];
    await showSystemPrompt({
      mode: "tui",
      getSystemPrompt: () => { throw new Error("idle getter must not be used"); },
      ui: {
        editor: async (title: string, content: string) => {
          editorCalls.push([title, content]);
          return "changed prompt";
        },
      },
    } as never, snapshot);
    expect(editorCalls).toEqual([[
      "Last prepared system prompt (edits are discarded)",
      "Selected model: fixture/model\nCaptured at: 2026-10-07T12:00:00.000Z\n" +
        "Pi prompt snapshot; excludes context-message and provider-payload rewrites.\n\nprepared prompt",
    ]]);
    expect(snapshot.prompt).toBe("prepared prompt");
  });

  test("reports no capture rather than presenting a base prompt", async () => {
    const notifications: Array<[string, string]> = [];
    await showSystemPrompt({
      mode: "tui",
      getSystemPrompt: () => { throw new Error("base prompt must not be used"); },
      ui: {
        editor: async () => { throw new Error("editor should not open"); },
        notify: (message: string, level: string) => notifications.push([message, level]),
      },
    } as never, undefined);
    expect(notifications).toEqual([[
      "No system prompt captured since session start or reload. Send a prompt first.", "info",
    ]]);
  });

  test("warns instead of opening a viewer outside interactive mode", async () => {
    const notifications: Array<[string, string]> = [];
    await showSystemPrompt({
      mode: "print",
      ui: {
        editor: async () => { throw new Error("editor should not open"); },
        notify: (message: string, level: string) => notifications.push([message, level]),
      },
    } as never, snapshot);
    expect(notifications).toEqual([[
      "The system prompt viewer is available only in interactive mode", "warning",
    ]]);
  });

  test("shares one observer per API, replaces captures, and clears session state", () => {
    const handlers = new Map<string, Function>();
    const pi = { on(event: string, handler: Function) {
      expect(handlers.has(event)).toBe(false);
      handlers.set(event, handler);
    } };
    const capture = observeSystemPrompt(pi as never);
    expect(observeSystemPrompt(pi as never)).toBe(capture);
    expect(capture()).toBeUndefined();
    let prompt = "first";
    const model = { provider: "fixture", id: "first-model" };
    const ctx = { getSystemPrompt: () => prompt, model };
    handlers.get("before_provider_request")!({}, ctx);
    expect(capture()?.prompt).toBe("first");
    expect(capture()?.model).toEqual(model);
    expect(Number.isNaN(Date.parse(capture()!.capturedAt))).toBe(false);
    model.id = "second-model";
    prompt = "idle base";
    expect(capture()?.model?.id).toBe("first-model");
    expect(capture()?.prompt).toBe("first");
    prompt = "";
    handlers.get("before_provider_request")!({}, { ...ctx, model: undefined });
    expect(capture()?.prompt).toBe("");
    expect(capture()?.model).toBeUndefined();
    handlers.get("session_start")!({ reason: "reload" });
    expect(capture()).toBeUndefined();
    expect(observeSystemPrompt({ on() {} } as never)()).toBeUndefined();
  });
});
