import { EventEmitter } from "node:events";
import { expect, test } from "bun:test";
import { createDeferredStartupExtension, type StartupSession } from "./index.js";

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
  createDeferredStartupExtension(load)(pi as any);
  const emit = async (name: string, event: any, ctx: any) => {
    let result: any;
    for (const handler of [...handlers.get(name) ?? []]) result = await handler(event, ctx);
    return result;
  };
  return { commands, emit, handlers, pi, tools };
}

function implementation(record: { loads: number; starts: string[]; beforeStarts: number }) {
  return async (pi: any, startup?: StartupSession) => {
    record.loads++;
    const start = (event: any) => { record.starts.push(event.reason); };
    pi.on("session_start", start);
    pi.on("before_agent_start", () => { record.beforeStarts++; });
    pi.registerTool({ name: "list_agents", async execute() { return "listed"; } });
    pi.registerCommand("subagents", { async handler() { return "opened"; } });
    if (startup) start(startup.event);
  };
}

test("loads during awaited session startup and registers the implementation normally", async () => {
  const record = { loads: 0, starts: [] as string[], beforeStarts: 0 };
  const f = fixture(async () => ({ default: implementation(record) }));

  expect(f.tools.size).toBe(0);
  expect(f.commands.size).toBe(0);

  await f.emit("session_start", { reason: "startup" }, { session: "first" });

  expect(record).toEqual({ loads: 1, starts: ["startup"], beforeStarts: 0 });
  expect(await f.tools.get("list_agents").execute()).toBe("listed");
  expect(await f.commands.get("subagents").handler()).toBe("opened");
});

test("replays the startup session once and leaves later lifecycle events to the implementation", async () => {
  const record = { loads: 0, starts: [] as string[], beforeStarts: 0 };
  const f = fixture(async () => ({ default: implementation(record) }));

  await f.emit("session_start", { reason: "startup" }, {});
  await f.emit("before_agent_start", {}, {});
  await f.emit("session_start", { reason: "reload" }, {});
  await f.emit("before_agent_start", {}, {});

  expect(record).toEqual({ loads: 1, starts: ["startup", "reload"], beforeStarts: 2 });
});

test("shares one initialization when startup delivery is repeated before loading finishes", async () => {
  const record = { loads: 0, starts: [] as string[], beforeStarts: 0 };
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const f = fixture(async () => {
    await held;
    return { default: implementation(record) };
  });

  const first = f.emit("session_start", { reason: "startup" }, {});
  const second = f.emit("session_start", { reason: "startup" }, {});
  release();
  await Promise.all([first, second]);

  expect(record).toEqual({ loads: 1, starts: ["startup"], beforeStarts: 0 });
});
