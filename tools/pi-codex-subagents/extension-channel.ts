import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export const EXTENSION_DISCOVER = "subagents:extension-channel:v1";
export const EXTENSION_COMMAND = "subagent-extension-channel";
export const EXTENSION_NOTIFY = "__subagent_extension_channel_v1__:";
export const EXTENSION_TIMEOUT_MS = 5_000;
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export interface WorkerOrigin { workerId: string; taskName: string; sessionId?: string }
export class ExtensionChannelError extends Error {
  constructor(public readonly code: string, message: string) { super(message); this.name = "ExtensionChannelError"; }
}
export type ChannelHandler = (payload: JsonValue, origin: WorkerOrigin) => JsonValue | Promise<JsonValue>;
export type ChannelReply = { ok: true; value: JsonValue } | { ok: false; code: string; message: string };
export type ChannelWire = { version: 1; requestId: string } & (
  { action: "request"; channel: string; payload: JsonValue } | { action: "result"; result: ChannelReply });
export interface ChildEndpoint {
  version: 1; role: "child";
  register(channel: string, handler: (payload: JsonValue) => JsonValue | Promise<JsonValue>): () => void;
  request(channel: string, payload: JsonValue): Promise<JsonValue>;
}
export interface ParentEndpoint {
  version: 1; role: "parent";
  register(channel: string, handler: ChannelHandler): () => void;
  request(workerId: string, channel: string, payload: JsonValue): Promise<JsonValue>;
}

/** Reject non-JSON rather than silently dropping undefined values or converting NaN. */
export function jsonValue(value: unknown): JsonValue {
  const seen = new Set<object>();
  const check = (item: unknown): void => {
    if (item === null || typeof item === "string" || typeof item === "boolean") return;
    if (typeof item === "number" && Number.isFinite(item)) return;
    if (typeof item !== "object" || !item || seen.has(item)) throw new ExtensionChannelError("invalid_payload", "Expected finite, acyclic JSON data.");
    if (!Array.isArray(item) && Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) {
      throw new ExtensionChannelError("invalid_payload", "Expected plain JSON data.");
    }
    seen.add(item);
    for (const child of Object.values(item)) check(child);
    seen.delete(item);
  };
  check(value);
  return JSON.parse(JSON.stringify(value));
}
export function channelName(channel: string): void {
  if (typeof channel !== "string" || !channel.trim()) throw new ExtensionChannelError("invalid_channel", "A nonempty channel name is required.");
}
export function channelFailure(error: unknown): ChannelReply {
  return { ok: false, code: error instanceof ExtensionChannelError ? error.code : "handler_error",
    message: error instanceof Error ? error.message : String(error) };
}
export function channelResult(result: ChannelReply): JsonValue {
  if (!result || typeof result.ok !== "boolean") throw new ExtensionChannelError("unknown", "Malformed channel response; admission is unknown.");
  if (!result.ok) throw new ExtensionChannelError(result.code, result.message);
  return jsonValue(result.value);
}
export function parseChannelWire(wire: string): ChannelWire {
  const value = JSON.parse(wire);
  if (value?.version !== 1 || typeof value.requestId !== "string" || !value.requestId) throw new Error("Malformed extension-channel message.");
  if (value.action === "request") { channelName(value.channel); value.payload = jsonValue(value.payload); }
  else if (value.action === "result" && value.result && typeof value.result.ok === "boolean") {
    if (value.result.ok) value.result.value = jsonValue(value.result.value);
    else if (typeof value.result.code !== "string" || !value.result.code || typeof value.result.message !== "string") throw new Error("Malformed extension-channel failure.");
  } else throw new Error("Malformed extension-channel message.");
  return value;
}
export function channelRegistry() {
  const handlers = new Map<string, ChannelHandler>();
  return {
    register(channel: string, handler: ChannelHandler): () => void {
      channelName(channel);
      if (handlers.has(channel)) throw new ExtensionChannelError("duplicate_channel", `Channel already registered: ${channel}`);
      handlers.set(channel, handler);
      return () => { if (handlers.get(channel) === handler) handlers.delete(channel); };
    },
    async receive(channel: string, payload: JsonValue, origin: WorkerOrigin): Promise<ChannelReply> {
      try {
        const handler = handlers.get(channel);
        if (!handler) throw new ExtensionChannelError("unavailable", `No handler for channel: ${channel}`);
        return { ok: true, value: jsonValue(await handler(jsonValue(payload), origin)) };
      } catch (error) { return channelFailure(error); }
    },
  };
}

/** Register before consumers load. Offers and discovery support either factory order. */
export function provideExtensionEndpoint(pi: ExtensionAPI, endpoint: ChildEndpoint | ParentEndpoint): void {
  pi.events.on(EXTENSION_DISCOVER, (value: any) => {
    if (value?.version === 1 && typeof value.provide === "function") value.provide(endpoint);
  });
  pi.events.emit(EXTENSION_DISCOVER, { version: 1, endpoint });
}

/** Generic RPC plumbing only; named handlers own their data, authority, and input admission. */
export function registerChildExtensionChannel(pi: ExtensionAPI): void {
  let context: ExtensionContext | undefined;
  const registry = channelRegistry();
  const pending = new Map<string, (reply: ChannelReply) => void>();
  const close = () => {
    context = undefined;
    for (const finish of [...pending.values()]) finish({ ok: false, code: "closed", message: "Worker session closed." });
  };
  const endpoint: ChildEndpoint = {
    version: 1, role: "child",
    register(channel, handler) { return registry.register(channel, payload => handler(payload)); },
    async request(channel, payload) {
      channelName(channel); payload = jsonValue(payload);
      // The helper is loaded live, while its parent may retain older code.
      // Fail before notifying an old manager, rather than waiting on an orphan request.
      if (process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION !== "1") throw new ExtensionChannelError("unsupported", "Parent does not support extension channels; start a fresh parent Pi process.");
      const ctx = context;
      if (!ctx) throw new ExtensionChannelError("closed", "Worker session is not started.");
      if (typeof pi.getPauseState !== "function" || pi.getPauseState() !== "unpaused") throw new ExtensionChannelError("inactive", "Worker is paused or pause state is unavailable.");
      const requestId = randomUUID();
      const reply = await new Promise<ChannelReply>(resolve => {
        const timer = setTimeout(() => finish({ ok: false, code: "timeout", message: "Extension request timed out; outcome is unknown. Do not retry automatically." }), EXTENSION_TIMEOUT_MS);
        timer.unref?.();
        const finish = (result: ChannelReply) => { if (!pending.delete(requestId)) return; clearTimeout(timer); resolve(result); };
        pending.set(requestId, finish);
        try { ctx.ui.notify(EXTENSION_NOTIFY + JSON.stringify({ version: 1, action: "request", requestId, channel, payload }), "info"); }
        catch (error) { finish({ ok: false, code: "unknown", message: String(error) }); }
      });
      return channelResult(reply);
    },
  };
  provideExtensionEndpoint(pi, endpoint);
  pi.on("session_start", (_event, ctx) => { close(); context = ctx; });
  pi.on("session_shutdown", close);
  pi.registerCommand(EXTENSION_COMMAND, {
    description: "Internal named extension-channel transport",
    handler: async (args, ctx) => {
      const request = parseChannelWire(args);
      if (request.action === "result") { pending.get(request.requestId)?.(request.result); return; }
      const result = typeof pi.getPauseState !== "function" || pi.getPauseState() !== "unpaused"
        ? { ok: false as const, code: "inactive", message: "Worker is paused." }
        : await registry.receive(request.channel, request.payload, { workerId: process.env.PI_SUBAGENT_ID ?? "", taskName: process.env.PI_SUBAGENT_TASK_NAME ?? "", sessionId: ctx.sessionManager.getSessionId() });
      ctx.ui.notify(EXTENSION_NOTIFY + JSON.stringify({ version: 1, action: "result", requestId: request.requestId, result }), "info");
    },
  });
}
