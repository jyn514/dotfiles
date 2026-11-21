import { EventEmitter } from "node:events";
import { expect, test } from "bun:test";
import { createDeferredStartupExtension, type StartupSession } from "./index.js";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import { stripVTControlCharacters } from "node:util";

function fixture(load: () => Promise<any>) {
  const handlers = new Map<string, Array<(event: any, ctx: any) => any>>();
  const tools = new Map<string, any>();
  const commands = new Map<string, any>();
  const renderers = new Map<string, any>();
  const historicalRenderers = new Map<string, any>();
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
    registerMessageRenderer(name: string, renderer: any, options?: { renderHistorical?: any }) {
      renderers.set(name, renderer);
      historicalRenderers.set(name, options?.renderHistorical);
    },
  };
  createDeferredStartupExtension(load)(pi as any);
  const emit = async (name: string, event: any, ctx: any) => {
    let result: any;
    for (const handler of [...handlers.get(name) ?? []]) result = await handler(event, ctx);
    return result;
  };
  return { commands, emit, handlers, pi, tools, renderers, historicalRenderers };
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

test("renders commentary as attributed Markdown when collapsed and raw notification when expanded", async () => {
  const { default: register } = await import("./implementation.js");
  const f = fixture(async () => ({ default: register }));
  await register(f.pi as any);
  const render = f.renderers.get("pi-codex-subagent-commentary");
  const historical = f.historicalRenderers.get("pi-codex-subagent-commentary");
  expect(render).toBeFunction();
  expect(historical).toBeFunction();
  const commentary = "**Found the cause.**\n\n- Preserve `src/界.ts`.\n- Keep the parent payload.\n\n```ts\nconst ok = true;\n```\n\nLast detail.";
  const content = `<subagent_notification>\n${JSON.stringify({ agent_name: "/review/api", status: "running", commentary, informational: true }, null, 2)}\n</subagent_notification>`;
  const message = { role: "custom", content, details: { agent_name: "/review/api" }, display: true, timestamp: 0 };
  const options = { expanded: false, outputPad: 0, outputPadY: 0, keyHint: () => "ctrl+o to expand" };
  const theme = { fg: (_color: string, text: string) => text };
  for (const appearance of ["dark", "light"]) {
    initTheme(appearance, false);
    for (const width of [24, 80]) {
      // Both existing saved messages and newly delivered details use the same presentation.
      for (const details of [message.details, { ...message.details, commentary }]) {
        const saved = { ...message, details };
        const collapsed = render(saved, options, theme).render(width);
        const preview = stripVTControlCharacters(collapsed.join("\n"));
        expect(preview).toContain("◌ /review/api · update");
        expect(preview).toContain("Found the cause.");
        expect(preview).not.toContain("**");
        expect(preview).not.toContain("subagent_notification");
        expect(preview).not.toContain("informational");
        expect(preview).not.toContain("Last detail.");
        expect(preview).toContain("…");
        expect(collapsed.every((line: string) => visibleWidth(line) <= width)).toBe(true);
        const expanded = render(saved, { ...options, expanded: true }, theme).render(width);
        const raw = stripVTControlCharacters(expanded.join("\n"));
        expect(raw).toContain("detail.");
        expect(raw).toContain("<subagent_notification>");
        expect(raw).toContain('"commentary":');
        expect(raw).toContain('"informational": true');
        expect(expanded.every((line: string) => visibleWidth(line) <= width)).toBe(true);
      }
    }
    const heading = historical({ ...message, get content() { throw new Error("Historical headings must stay cheap"); } }, options, theme);
    expect(stripVTControlCharacters(heading.render(80).join("\n")).trimEnd()).toBe("◌ /review/api · update");
  }
  const shortMessage = { ...message, content: '<subagent_notification>\n{"commentary":"**Short update.**","informational":true}\n</subagent_notification>', details: { ...message.details, commentary: "**Short update.**" } };
  const shortPreview = stripVTControlCharacters(render(shortMessage, options, theme).render(80).join("\n"));
  expect(shortPreview).toContain("Short update.");
  expect(shortPreview).not.toContain("subagent_notification");
  const shortExpanded = render(shortMessage, { ...options, expanded: true }, theme).render(80);
  expect(stripVTControlCharacters(shortExpanded.join("\n")).split("\n").map(line => line.trimEnd()).slice(1).join("\n"))
    .toBe(shortMessage.content);
  const truncated = { ...message, content: "<subagent_notification>\n{partial", details: { ...message.details, commentary: "Readable prefix", fullOutputPath: "/tmp/full-output" } };
  expect(stripVTControlCharacters(render(truncated, options, theme).render(80).join("\n"))).toContain("Full output: /tmp/full-output");
  expect(render({ ...message, content: "<subagent_notification>\n{partial\n</subagent_notification>" }, options, theme)).toBeUndefined();
  expect(message.content).toBe(content);
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
