import { EventEmitter } from "node:events";
import { expect, test } from "bun:test";
import {
  registerChildExtensionChannel, EXTENSION_DISCOVER, EXTENSION_COMMAND, EXTENSION_NOTIFY,
  channelRegistry, jsonValue, parseChannelWire, type ChildEndpoint,
} from "./extension-channel.ts";

function child(before?: (events: EventEmitter) => void) {
  const events = new EventEmitter();
  const hooks = new Map<string, (...args: any[]) => any>();
  const commands = new Map<string, any>();
  const notifications: string[] = [];
  let endpoint: ChildEndpoint;
  before?.(events);
  const pi: any = {
    events, on(name: string, handler: any) { hooks.set(name, handler); },
    registerCommand(name: string, command: any) { commands.set(name, command); },
    getPauseState: () => "unpaused",
  };
  registerChildExtensionChannel(pi);
  events.emit(EXTENSION_DISCOVER, { version: 1, provide(value: ChildEndpoint) { endpoint = value; } });
  const ctx = { ui: { notify(message: string) { notifications.push(message); } }, sessionManager: { getSessionId: () => "child-native-id" } };
  return {
    pi, notifications, endpoint: endpoint!,
    start() { hooks.get("session_start")!({}, ctx); },
    close() { hooks.get("session_shutdown")!(); },
    command(value: unknown, commandContext = ctx) { return commands.get(EXTENSION_COMMAND).handler(JSON.stringify(value), commandContext); },
  };
}

test("offer reaches an early consumer and discovery reaches a late consumer", async () => {
  let offered: ChildEndpoint | undefined;
  const h = child(events => events.on(EXTENSION_DISCOVER, value => { if (value.endpoint) offered = value.endpoint; }));
  expect(offered).toBe(h.endpoint);
  const remove = h.endpoint.register("custom:data", payload => ({ echoed: payload }));
  h.start();
  await h.command({ version: 1, action: "request", requestId: "one", channel: "custom:data", payload: [null, true, "𐐀"] });
  expect(parseChannelWire(h.notifications[0].slice(EXTENSION_NOTIFY.length))).toEqual({ version: 1, action: "result", requestId: "one", result: { ok: true, value: { echoed: [null, true, "𐐀"] } } });
  remove();
  await h.command({ version: 1, action: "request", requestId: "two", channel: "custom:data", payload: null });
  expect(parseChannelWire(h.notifications[1].slice(EXTENSION_NOTIFY.length))).toMatchObject({ result: { ok: false, code: "unavailable" } });
});

test("each child handler receives its own current command context without a shared context slot", async () => {
  const h = child(); h.start();
  let release!: () => void;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  h.endpoint.register("context", async (payload, context) => {
    if (payload === "first") await blocked;
    return context!.sessionManager.getSessionId();
  });
  const context = (id: string) => ({ ui: { notify: (message: string) => h.notifications.push(message) }, sessionManager: { getSessionId: () => id } });
  const first = h.command({ version: 1, action: "request", requestId: "first", channel: "context", payload: "first" }, context("first-context"));
  await h.command({ version: 1, action: "request", requestId: "second", channel: "context", payload: "second" }, context("second-context"));
  release(); await first;
  expect(h.notifications.map(message => parseChannelWire(message.slice(EXTENSION_NOTIFY.length)))).toEqual([
    { version: 1, action: "result", requestId: "second", result: { ok: true, value: "second-context" } },
    { version: 1, action: "result", requestId: "first", result: { ok: true, value: "first-context" } },
  ]);
});

test("child correlates out-of-order results and closes calls without retrying late receipts", async () => {
  const old = process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION;
  process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION = "1";
  try {
    const h = child();
    await expect(h.endpoint.request("c", null)).rejects.toMatchObject({ code: "closed" });
    h.start();
    const first = h.endpoint.request("c", { one: 1 });
    const second = h.endpoint.request("c", { two: 2 });
    const requests = h.notifications.map(message => parseChannelWire(message.slice(EXTENSION_NOTIFY.length)));
    await h.command({ version: 1, action: "result", requestId: requests[1].requestId, result: { ok: true, value: "second" } });
    await h.command({ version: 1, action: "result", requestId: requests[0].requestId, result: { ok: true, value: "first" } });
    expect(await first).toBe("first"); expect(await second).toBe("second");
    const pending = h.endpoint.request("c", null);
    const closed = pending.catch(error => error);
    const last = parseChannelWire(h.notifications.at(-1)!.slice(EXTENSION_NOTIFY.length));
    h.close(); expect(await closed).toMatchObject({ code: "closed" });
    await h.command({ version: 1, action: "result", requestId: last.requestId, result: { ok: true, value: "too late" } });
    expect(h.notifications).toHaveLength(3);
    h.start(); h.pi.getPauseState = () => "paused";
    await expect(h.endpoint.request("c", null)).rejects.toMatchObject({ code: "inactive" });
  } finally {
    if (old === undefined) delete process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION;
    else process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION = old;
  }
});

test("registry reports failures and stale unsubscribes cannot remove a replacement", async () => {
  const registry = channelRegistry();
  const origin = { workerId: "worker", taskName: "task" };
  const remove = registry.register("c", () => null);
  expect(() => registry.register("c", () => true)).toThrow("already registered");
  remove(); registry.register("c", () => true); remove();
  expect(await registry.receive("c", null, origin)).toEqual({ ok: true, value: true });
  expect(await registry.receive("missing", null, origin)).toMatchObject({ ok: false, code: "unavailable" });
  registry.register("throw", () => { throw new Error("failed handler"); });
  expect(await registry.receive("throw", null, origin)).toEqual({ ok: false, code: "handler_error", message: "failed handler" });
  registry.register("undefined", (() => undefined) as any);
  expect(await registry.receive("undefined", null, origin)).toMatchObject({ ok: false, code: "invalid_payload" });
});

test("wire parser rejects malformed framing and non-JSON data", () => {
  for (const value of [undefined, NaN, Infinity, { bad: undefined }, { bad: () => 1 }, new Date()]) expect(() => jsonValue(value)).toThrow();
  const cycle: any = {}; cycle.self = cycle;
  expect(() => jsonValue(cycle)).toThrow();
  for (const wire of ["null", "[]", "{}", '{"version":2,"requestId":"id"}', '{"version":1,"action":"request","requestId":"id","channel":"x"}', '{"version":1,"action":"result","requestId":"id","result":{"ok":false}}']) expect(() => parseChannelWire(wire)).toThrow();
  expect(jsonValue({ x: [null, false, 2, "\u2028"] })).toEqual({ x: [null, false, 2, "\u2028"] });
});
