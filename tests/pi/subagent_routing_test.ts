import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import subagentRouting from "../../config/pi-agent/pi-extensions/subagent-routing";
import {
  classifySubagentRoute,
  LUNA_SAFE_SKILLS,
} from "../../config/pi-agent/pi-extensions/subagent-routing-core";

describe("automatic subagent routing", () => {
  test("routes allowlisted skills to Luna", () => {
    expect([...LUNA_SAFE_SKILLS]).toEqual([
      "session-title-curation",
      "tighten-docs",
    ]);
    expect(classifySubagentRoute({ skills: ["tighten-docs"] })).toEqual({
      route: "luna",
      reason: "Luna-safe skill: tighten-docs",
    });
    expect(classifySubagentRoute({ skills: ["session-title-curation"] })).toEqual({
      route: "luna",
      reason: "Luna-safe skill: session-title-curation",
    });
  });

  test.each([
    {},
    { skills: [] },
    { skills: ["reviewer"] },
    { skills: ["tighten-docs", "technical-docs"] },
    { skills: [42] },
  ])("keeps absent, unknown, mixed, or malformed skills on the parent", (input) => {
    expect(classifySubagentRoute(input).route).toBe("parent");
  });

  test("preserves an explicit agent template", () => {
    expect(classifySubagentRoute({
      agent_type: "parent",
      skills: ["tighten-docs"],
    })).toEqual({ route: "parent", reason: "explicit agent template" });
  });

  test("injects Luna only when the template, model, and auth are available", () => {
    let handler: ((event: any, ctx: any) => void) | undefined;
    const pi = {
      on(event: string, callback: (event: any, ctx: any) => void) {
        if (event === "tool_call") handler = callback;
      },
    } as unknown as ExtensionAPI;
    subagentRouting(pi, { templateExists: () => true });

    const input = { skills: ["tighten-docs"] };
    const notifications: unknown[] = [];
    handler?.({ toolName: "spawn_agent", input }, {
      modelRegistry: {
        find: () => ({ id: "gpt-5.6-luna" }),
        hasConfiguredAuth: () => true,
      },
      ui: { notify: (...args: unknown[]) => notifications.push(args) },
    });

    expect(input).toEqual({ skills: ["tighten-docs"], agent_type: "luna" });
    expect(notifications).toEqual([[
      "Subagent routed to Luna: Luna-safe skill: tighten-docs",
      "info",
    ]]);
  });

  test("ignores unrelated tool calls", () => {
    let handler: ((event: any, ctx: any) => void) | undefined;
    const pi = {
      on(_event: string, callback: (event: any, ctx: any) => void) {
        handler = callback;
      },
    } as unknown as ExtensionAPI;
    subagentRouting(pi, { templateExists: () => true });

    const input = { skills: ["tighten-docs"] };
    handler?.({ toolName: "other_tool", input }, {});
    expect(input).toEqual({ skills: ["tighten-docs"] });
  });

  test.each([
    [false, true, true],
    [true, false, true],
    [true, true, false],
  ])("preserves inherited routing when template=%s model=%s auth=%s", (template, modelAvailable, auth) => {
    let handler: ((event: any, ctx: any) => void) | undefined;
    const pi = {
      on(_event: string, callback: (event: any, ctx: any) => void) {
        handler = callback;
      },
    } as unknown as ExtensionAPI;
    subagentRouting(pi, { templateExists: () => template });

    const input = { skills: ["tighten-docs"] };
    handler?.({ toolName: "spawn_agent", input }, {
      modelRegistry: {
        find: () => modelAvailable ? { id: "gpt-5.6-luna" } : undefined,
        hasConfiguredAuth: () => auth,
      },
      ui: { notify: () => {} },
    });
    expect(input).toEqual({ skills: ["tighten-docs"] });
  });
});
