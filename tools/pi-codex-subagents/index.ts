import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionFactory } from "@earendil-works/pi-coding-agent";

type ExtensionModule = { default: ExtensionFactory };
type Handler = (event: any, ctx: any) => unknown;

const LINK_DISCOVER = "pi-link:workers:v1";
const TOOL_NAMES = [
  "spawn_agent",
  "wait_agent",
  "wait_all_agents",
  "list_agents",
  "read_agent_response",
  "send_message",
  "interrupt_agent",
] as const;

const COMMANDS = {
  pause: "Save parent and subagents; --status, --discard, or --exit",
  unpause: "Restore saved parent and subagent work",
  subagents: "Browse subagents",
} as const;

function agentDirectory(): string {
  const configured = process.env.PI_CODING_AGENT_DIR;
  if (!configured) return join(homedir(), ".pi", "agent");
  if (configured === "~") return homedir();
  return configured.startsWith("~/") ? join(homedir(), configured.slice(2)) : configured;
}

function packageConfig(): Record<string, unknown> {
  try {
    return JSON.parse(readFileSync(join(agentDirectory(), "pi-codex-subagents", "config.json"), "utf8"));
  } catch {
    return {};
  }
}

function runsDirectory(config = packageConfig()): string {
  const packageDirectory = join(agentDirectory(), "pi-codex-subagents");
  const configured = typeof config.storageDir === "string" ? config.storageDir.trim() : "";
  if (!configured) return join(packageDirectory, "runs");
  const expanded = configured === "~" || configured.startsWith("~/")
    ? join(homedir(), configured.slice(2))
    : configured;
  return isAbsolute(expanded) ? expanded : resolve(packageDirectory, expanded);
}

function hasSuspendedGroup(ctx: any): boolean {
  const sessionId = ctx?.sessionManager?.getSessionId?.();
  if (!sessionId) return false;
  const scope = createHash("sha256").update(String(sessionId)).digest("hex").slice(0, 24);
  const file = join(runsDirectory(), scope, "group.json");
  if (!existsSync(file)) return false;
  try {
    const phase = JSON.parse(readFileSync(file, "utf8"))?.phase;
    return phase !== "consumed" && phase !== "discarded";
  } catch {
    // Malformed recovery state must still fail closed through the full coordinator.
    return true;
  }
}

function objectSchema(properties: Record<string, unknown> = {}): Record<string, unknown> {
  return { type: "object", properties, additionalProperties: true };
}

const PLACEHOLDER_SCHEMAS: Record<(typeof TOOL_NAMES)[number], Record<string, unknown>> = {
  spawn_agent: objectSchema({
    task_name: { type: "string" },
    message: { type: "string" },
    fork_from: { type: "object" },
    agent_type: { type: "string" },
    skills: { type: "array", items: { type: "string" } },
  }),
  wait_agent: objectSchema({ targets: { type: "array", items: { type: "string" } } }),
  wait_all_agents: objectSchema({ targets: { type: "array", items: { type: "string" } } }),
  list_agents: objectSchema({
    path_prefix: { type: "string" }, include_all: { type: "boolean" },
    limit: { type: "integer" }, offset: { type: "integer" },
  }),
  read_agent_response: objectSchema({ target: { type: "string" } }),
  send_message: objectSchema({ target: { type: "string" }, message: { type: "string" } }),
  interrupt_agent: objectSchema({ target: { type: "string" } }),
};

const TOOL_LABELS: Record<(typeof TOOL_NAMES)[number], string> = {
  spawn_agent: "Spawn Agent",
  wait_agent: "Wait Agent",
  wait_all_agents: "Wait All Agents",
  list_agents: "List Agents",
  read_agent_response: "Read Agent Response",
  send_message: "Send Message",
  interrupt_agent: "Interrupt Agent",
};

export function createLazyExtension(
  load: () => Promise<ExtensionModule> = () => import("./implementation.js"),
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    const handlers = new Map<string, Handler[]>();
    const eventHandlers = new Map<string, Handler[]>();
    const tools = new Map<string, any>();
    const commands = new Map<string, any>();
    let start: { event: any; ctx: any } | undefined;
    let ready = false;
    let loading: Promise<void> | undefined;

    const remember = (map: Map<string, Handler[]>, name: string, handler: Handler) => {
      const entries = map.get(name) ?? [];
      entries.push(handler);
      map.set(name, entries);
    };

    const events = new Proxy(pi.events, {
      get(target, property) {
        if (property === "on") {
          return (name: string, handler: Handler) => {
            remember(eventHandlers, name, handler);
            return target.on(name, handler);
          };
        }
        const value = Reflect.get(target, property, target);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });

    const deferredPi = new Proxy(pi, {
      get(target, property) {
        if (property === "events") return events;
        if (property === "on") {
          return (name: string, handler: Handler) => {
            remember(handlers, name, handler);
            return target.on(name as any, handler as any);
          };
        }
        if (property === "registerTool") {
          return (tool: any) => { tools.set(tool.name, tool); target.registerTool(tool); };
        }
        if (property === "registerCommand") {
          return (name: string, command: any) => { commands.set(name, command); target.registerCommand(name, command); };
        }
        const value = Reflect.get(target, property, target);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });

    const invoke = async (map: Map<string, Handler[]>, name: string, event: any, ctx: any) => {
      let result: unknown;
      for (const handler of map.get(name) ?? []) result = await handler(event, ctx);
      return result;
    };

    const initialize = () => {
      if (loading) return loading;
      loading = (async () => {
        const extension = await load();
        extension.default(deferredPi);
        if (start) await invoke(handlers, "session_start", start.event, start.ctx);
        ready = true;
      })();
      return loading;
    };

    const initializeForEvent = async (name: string, event: any, ctx: any) => {
      const wasReady = ready;
      await initialize();
      return wasReady ? undefined : invoke(handlers, name, event, ctx);
    };

    pi.on("session_start", async (event, ctx) => {
      start = { event, ctx };
      if (hasSuspendedGroup(ctx)) await initialize();
    });
    pi.on("before_agent_start", (event, ctx) => initializeForEvent("before_agent_start", event, ctx));
    pi.on("input", (event, ctx) => initializeForEvent("input", event, ctx) as any);
    pi.on("session_shutdown", async (event, ctx) => {
      if (!loading) return;
      const wasReady = ready;
      await loading;
      // A handler registered during this event is absent from Pi's current snapshot.
      return wasReady ? undefined : invoke(handlers, "session_shutdown", event, ctx);
    });

    pi.events.on(LINK_DISCOVER, (request: any) => {
      if (ready || !request || typeof request.provide !== "function") return;
      request.provide({
        async broadcast(message: any) {
          await initialize();
          let integration: any;
          const replay = { ...request, provide(value: any) { integration = value; } };
          await invoke(eventHandlers, LINK_DISCOVER, replay, undefined);
          return integration ? integration.broadcast(message) : [];
        },
        async reply(worker: any, message: any) {
          await initialize();
          let integration: any;
          const replay = { ...request, provide(value: any) { integration = value; } };
          await invoke(eventHandlers, LINK_DISCOVER, replay, undefined);
          return integration
            ? integration.reply(worker, message)
            : { status: "unsupported", reason: "link_integration_unavailable" };
        },
      });
    });

    for (const name of TOOL_NAMES) {
      pi.registerTool({
        name,
        label: TOOL_LABELS[name],
        description: `Load the subagent runtime and run ${name}.`,
        parameters: PLACEHOLDER_SCHEMAS[name],
        async execute(...args: any[]) {
          await initialize();
          const tool = tools.get(name);
          if (!tool) throw new Error(`${name} is unavailable after subagent initialization.`);
          return tool.execute(...args);
        },
      } as any);
    }

    for (const [name, description] of Object.entries(COMMANDS)) {
      pi.registerCommand(name, {
        description,
        allowedWhilePaused: true,
        async handler(args, ctx) {
          await initialize();
          const command = commands.get(name);
          if (!command) throw new Error(`/${name} is unavailable after subagent initialization.`);
          return command.handler(args, ctx);
        },
      });
    }

    const shortcut = packageConfig().shortcut;
    if (typeof shortcut === "string" && shortcut.trim()) {
      pi.registerShortcut(shortcut.trim() as any, {
        description: "Browse subagents",
        async handler(ctx) {
          await initialize();
          const command = commands.get("subagents");
          if (!command) throw new Error("/subagents is unavailable after subagent initialization.");
          return command.handler("", ctx);
        },
      });
    }
  };
}

export default createLazyExtension();
