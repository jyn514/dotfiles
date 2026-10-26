import { EventEmitter } from "node:events";
import { expect, test } from "bun:test";
import { createLazyExtension } from "./index.js";

function fixture(load: () => Promise<any>) {
  const handlers = new Map<string, Array<(event: any, ctx: any) => any>>();
  const tools = new Map<string, any>();
  const commands = new Map<string, any>();
  const pi = {
    events: new EventEmitter(),
    on(name: string, handler: (event: any, ctx: any) => any) {
      const entries = handlers.get(name) ?? [];
      entries.push(handler);
      handlers.set(name, entries);
    },
    registerTool(tool: any) { tools.set(tool.name, tool); },
    registerCommand(name: string, command: any) { commands.set(name, command); },
    registerShortcut() {},
    registerMessageRenderer() {},
  };
  createLazyExtension(load)(pi as any);
  const emit = async (name: string, event: any, ctx: any) => {
    let result: any;
    for (const handler of [...handlers.get(name) ?? []]) result = await handler(event, ctx);
    return result;
  };
  return { commands, emit, handlers, pi, tools };
}

test("defers implementation through ordinary startup and initializes once for concurrent tool use", async () => {
  let loads = 0;
  let starts = 0;
  let calls = 0;
  const f = fixture(async () => {
    loads++;
    await Promise.resolve();
    return { default(pi: any) {
      pi.on("session_start", () => { starts++; });
      pi.registerTool({
        name: "list_agents", label: "List Agents", description: "fixture",
        parameters: { type: "object", properties: {} },
        async execute() { calls++; return { content: [{ type: "text", text: "listed" }] }; },
      });
    } };
  });
  const ctx = { sessionManager: { getSessionId: () => "lazy-parent" } };
  await f.emit("session_start", { reason: "startup" }, ctx);
  expect({ loads, starts }).toEqual({ loads: 0, starts: 0 });

  const placeholder = f.tools.get("list_agents");
  const [first, second] = await Promise.all([
    placeholder.execute("one", {}, undefined, undefined, ctx),
    placeholder.execute("two", {}, undefined, undefined, ctx),
  ]);
  expect({ loads, starts, calls }).toEqual({ loads: 1, starts: 1, calls: 2 });
  expect(first.content[0].text).toBe("listed");
  expect(second.content[0].text).toBe("listed");
});

test("initializes before the first run and dispatches the current boundary once", async () => {
  let loads = 0;
  let starts = 0;
  let beforeStarts = 0;
  const f = fixture(async () => ({ default(pi: any) {
    loads++;
    pi.on("session_start", () => { starts++; });
    pi.on("before_agent_start", (event: any) => { beforeStarts++; event.initialized = true; });
  } }));
  const ctx = { sessionManager: { getSessionId: () => "lazy-run-parent" } };
  await f.emit("session_start", { reason: "startup" }, ctx);
  const event: any = {};
  await f.emit("before_agent_start", event, ctx);
  expect({ loads, starts, beforeStarts, initialized: event.initialized })
    .toEqual({ loads: 1, starts: 1, beforeStarts: 1, initialized: true });

  await f.emit("before_agent_start", {}, ctx);
  expect({ loads, starts, beforeStarts }).toEqual({ loads: 1, starts: 1, beforeStarts: 2 });
});

test("loads a command on first invocation and preserves its result", async () => {
  let loads = 0;
  const f = fixture(async () => ({ default(pi: any) {
    loads++;
    pi.registerCommand("subagents", {
      description: "Browse subagents",
      allowedWhilePaused: true,
      async handler(args: string, ctx: any) { ctx.seen = args; return "opened"; },
    });
  } }));
  const ctx: any = { sessionManager: { getSessionId: () => "lazy-command-parent" } };
  const result = await f.commands.get("subagents").handler("current", ctx);
  expect({ loads, result, seen: ctx.seen }).toEqual({ loads: 1, result: "opened", seen: "current" });
});
