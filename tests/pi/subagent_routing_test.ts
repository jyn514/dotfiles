import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import subagentConfig from "../../config/pi-agent/pi-codex-subagents/config.json";
import subagentRouting from "../../config/pi-agent/pi-extensions/subagent-routing";
import { classifySubagentRoute } from "../../config/pi-agent/pi-extensions/subagent-routing-core";

function routingHandler(templateExists = true) {
  let handler: ((event: any, ctx: any) => void) | undefined;
  const pi = {
    on(event: string, callback: (event: any, ctx: any) => void) {
      if (event === "tool_call") handler = callback;
    },
  } as unknown as ExtensionAPI;
  subagentRouting(pi, { templateExists: () => templateExists });
  expect(handler).toBeFunction();
  return handler!;
}

describe("automatic subagent routing", () => {
  test.each(["tighten-prose", "session-title-curation"])("routes %s to Luna", (skill) => {
    expect(classifySubagentRoute({ skills: [skill] })).toEqual({
      route: "luna",
      reason: `Luna-safe skill: ${skill}`,
    });
  });

  test("combines Luna-safe skills without requiring a particular set order", () => {
    expect(classifySubagentRoute({
      skills: ["tighten-prose", "session-title-curation"],
    }).route).toBe("luna");
  });

  test.each([
    {},
    { skills: [] },
    { skills: ["reviewer"] },
    { skills: ["technical-docs"] },
    { skills: ["tighten-docs"] },
    { skills: ["tighten-prose", "technical-docs"] },
    { skills: ["tighten-prose", "tighten-docs"] },
    { skills: [42] },
  ])("keeps absent, unknown, mixed, or malformed skills on the parent: %j", (input) => {
    expect(classifySubagentRoute(input).route).toBe("parent");
  });

  test("direct commands route only narrow skills, not holistic editing or the old name", () => {
    const routes: Record<string, unknown> = subagentConfig.directSkillRoutes;
    expect(routes["tighten-prose"]).toEqual({ agentType: "luna" });
    expect(routes["technical-docs"]).toBeUndefined();
    expect(routes["tighten-docs"]).toBeUndefined();
    expect(routes["session-title-curation"]).toEqual({ agentType: "luna", proposalOnly: true });
  });

  test.each([
    { agent_type: "parent" },
    { agent_type: "reviewer" },
  ])("preserves explicit agent overrides %j without replacing the template", (override) => {
    const input = { skills: ["tighten-prose"], ...override };
    expect(classifySubagentRoute(input).route).toBe("parent");
    routingHandler()({ toolName: "spawn_agent", input }, {});
    expect(input).toEqual({ skills: ["tighten-prose"], ...override });
  });

  test.each(["technical-docs", "tighten-docs"])("does not inject Luna for %s", (skill) => {
    const input = { skills: [skill] };
    routingHandler()({ toolName: "spawn_agent", input }, {});
    expect(input).toEqual({ skills: [skill] });
  });

  test("injects Luna only when the template, model, and auth are available", () => {
    const input = { skills: ["tighten-prose"] };
    const notifications: unknown[] = [];
    routingHandler()({ toolName: "spawn_agent", input }, {
      modelRegistry: {
        find: () => ({ id: "gpt-5.6-luna" }),
        hasConfiguredAuth: () => true,
      },
      ui: { notify: (...args: unknown[]) => notifications.push(args) },
    });

    expect(input).toEqual({ skills: ["tighten-prose"], agent_type: "luna" });
    expect(notifications).toEqual([[
      "Subagent routed to Luna: Luna-safe skill: tighten-prose",
      "info",
    ]]);
  });

  test("ignores unrelated tool calls", () => {
    const input = { skills: ["tighten-prose"] };
    routingHandler()({ toolName: "other_tool", input }, {});
    expect(input).toEqual({ skills: ["tighten-prose"] });
  });

  test.each([
    [false, true, true],
    [true, false, true],
    [true, true, false],
  ])("preserves inherited routing when template=%s model=%s auth=%s", (template, modelAvailable, auth) => {
    const input = { skills: ["tighten-prose"] };
    routingHandler(template)({ toolName: "spawn_agent", input }, {
      modelRegistry: {
        find: () => modelAvailable ? { id: "gpt-5.6-luna" } : undefined,
        hasConfiguredAuth: () => auth,
      },
      ui: { notify: () => {} },
    });
    expect(input).toEqual({ skills: ["tighten-prose"] });
  });
});
