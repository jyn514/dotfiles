import { expect, test } from "bun:test";
import { initializeToolExecution, isRoutedTool, registerRoutedTool, toolExecutionMetadata } from "../../libexec/pi-tool-execution.ts";

// Separate extension API objects share the runtime event bus, as in Pi.
function runtime(settings: any = {}) {
  const listeners = new Map<string, Function[]>();
  const hooks = new Map<string, Function[]>();
  const definitions = new Map<string, any>();
  let active: string[] = [];
  const events = {
    on(name: string, fn: Function) { listeners.set(name, [...listeners.get(name) ?? [], fn]); },
    emit(name: string, value: unknown) { for (const fn of listeners.get(name) ?? []) fn(value); },
  };
  const api = () => ({
    events,
    on(name: string, fn: Function) { hooks.set(name, [...hooks.get(name) ?? [], fn]); },
    getSettings: () => settings,
    registerTool(tool: any) { definitions.set(tool.name, tool); if (!active.includes(tool.name)) active.push(tool.name); },
    getAllTools: () => Array.from(definitions.values()),
    getActiveTools: () => [...active],
    setActiveTools(tools: string[]) { active = tools; },
  });
  return { api, definitions, hooks, settings };
}
const tool = (name: string) => ({ name, label: name, description: "example", parameters: {},
  execute: async () => ({ content: [{ type: "text", text: "host result" }], details: {} }) });

test("settings change placement descriptions, not activation, across extension APIs", async () => {
  const previous = process.env.CODEX_SANDBOX_TOOL_CONTAINER;
  process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
  try {
    const rt = runtime({ sandbox: { toolExecution: { portable: "host" } } });
    const first = rt.api(), second = rt.api();
    initializeToolExecution(first as any);
    registerRoutedTool(second as any, tool("portable") as any, { guest: "builtin", sandboxDefault: "guest" });
    expect(isRoutedTool(first as any, "portable")).toBe(true);
    first.setActiveTools([]);
    await rt.hooks.get("session_start")![0]({}, { ui: { notify() {} } });
    expect(first.getActiveTools()).toEqual([]);
    expect(rt.definitions.get("portable").description).toContain("host (settings)");
    const result = await rt.definitions.get("portable").execute("id", {}, undefined, undefined, {});
    expect(toolExecutionMetadata(result.details)).toEqual({ target: "host", source: "settings" });
    rt.settings.sandbox.toolExecution.portable = "guest";
    await rt.hooks.get("session_start")![0]({}, { ui: { notify() {} } });
    expect(first.getActiveTools()).toEqual([]);
    expect(rt.definitions.get("portable").description).toContain("guest (settings)");
    expect(toolExecutionMetadata(result.details)).toEqual({ target: "host", source: "settings" });
  } finally {
    if (previous === undefined) delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
    else process.env.CODEX_SANDBOX_TOOL_CONTAINER = previous;
  }
});

test("explicit guest without attachment does not run the host operation", async () => {
  const previous = process.env.CODEX_SANDBOX_TOOL_CONTAINER;
  delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
  try {
    const rt = runtime({ sandbox: { toolExecution: { portable: "guest" } } });
    let hostCalls = 0;
    registerRoutedTool(rt.api() as any, { ...tool("portable"), execute: async () => { hostCalls++; } } as any,
      { guest: "builtin", sandboxDefault: "host" });
    await expect(rt.definitions.get("portable").execute("id", {}, undefined, undefined, {})).rejects.toThrow(/portable execution: guest \(settings\).*no guest/i);
    expect(hostCalls).toBe(0);
  } finally {
    if (previous === undefined) delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
    else process.env.CODEX_SANDBOX_TOOL_CONTAINER = previous;
  }
});

test("invalid values and guest placement of unadapted tools are rejected", async () => {
  const rt = runtime({ sandbox: { toolExecution: { ordinary: "guest" } } });
  const pi = rt.api();
  pi.registerTool(tool("ordinary"));
  initializeToolExecution(pi as any);
  expect(() => rt.hooks.get("session_start")![0]({}, { ui: { notify() {} } })).toThrow(/ordinary.*no guest entry point/);
  rt.settings.sandbox.toolExecution.ordinary = "elsewhere";
  expect(() => rt.hooks.get("session_start")![0]({}, { ui: { notify() {} } })).toThrow(/ordinary.*host.*guest/);
});

test("sandboxed built-ins reject host override and retain guest default", async () => {
  const previous = process.env.CODEX_SANDBOX_TOOL_CONTAINER;
  process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
  try {
    const rt = runtime({ sandbox: { toolExecution: { bash: "host" } } });
    const pi = rt.api();
    let hostCalls = 0;
    registerRoutedTool(pi as any, { ...tool("bash"), execute: async () => { hostCalls++; } } as any,
      { guest: "builtin", sandboxDefault: "guest", hostInSandbox: false });
    await expect(rt.definitions.get("bash").execute("id", {}, undefined, undefined, {})).rejects.toThrow(/bash execution: host \(settings\).*policy/i);
    expect(hostCalls).toBe(0);
    delete rt.settings.sandbox.toolExecution.bash;
    await rt.hooks.get("session_start")![0]({}, { ui: { notify() {} } });
    expect(rt.definitions.get("bash").description).toContain("guest (default)");
  } finally {
    if (previous === undefined) delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
    else process.env.CODEX_SANDBOX_TOOL_CONTAINER = previous;
  }
});
