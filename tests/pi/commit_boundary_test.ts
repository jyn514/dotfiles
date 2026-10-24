import { expect, spyOn, test } from "bun:test";
import { createBoundaryController, nativeBoundaryEnvironment } from "../../config/pi-agent/pi-extensions/commit-boundary.ts";

function harness(capture: (ctx: any, signal: AbortSignal) => Promise<any> = async () => ({ revision: "a".repeat(40) })) {
  const hooks = new Map<string, Function[]>();
  let captures = 0;
  let session = "session-a";
  const ctx = { cwd: "/repo", model: { id: "model-a" }, sessionManager: {
    getSessionId: () => session, getSessionFile: () => undefined,
  } } as any;
  const controller = createBoundaryController({
    // No checkpoint event-bus protocol is allowed, including on read-only turns.
    events: { on() { throw new Error("obsolete checkpoint listener"); }, emit() { throw new Error("obsolete checkpoint export"); } },
    on(name: string, handler: Function) { hooks.set(name, [...(hooks.get(name) ?? []), handler]); },
  } as any, async (ctx, signal) => { captures++; return capture(ctx, signal); });
  return {
    ctx, controller, captures: () => captures,
    session: (id: string) => { session = id; },
    async emit(name: string, event: unknown = {}) {
      for (const handler of hooks.get(name) ?? []) await handler(event, ctx);
    },
    succeed() { controller.finish(controller.begin(ctx), undefined, true); },
  };
}

test("only settled editing responses capture; iterations and read-only responses do not", async () => {
  const h = harness();
  await h.emit("session_start");
  await h.emit("agent_settled");
  expect(h.captures()).toBe(0);
  h.succeed();
  await h.emit("turn_end");
  await h.emit("agent_end");
  h.succeed();
  expect(h.captures()).toBe(0);
  await h.emit("agent_settled");
  expect(h.captures()).toBe(1);
  await h.emit("agent_settled");
  expect(h.captures()).toBe(1);
  expect(Object.keys(h.controller.begin(h.ctx))).toEqual(["lifetime"]);
});

test("failed calls never establish a boundary; abort discards only unfinished response tracking", async () => {
  const h = harness();
  h.controller.finish(h.controller.begin(h.ctx), undefined, false);
  await h.emit("agent_settled");
  expect(h.captures()).toBe(0);
  h.succeed();
  await h.emit("agent_settled", { aborted: true });
  await h.emit("agent_settled");
  expect(h.captures()).toBe(0);
  h.succeed();
  await h.emit("agent_settled");
  expect(h.captures()).toBe(1);
  // There is deliberately no filesystem clear callback on controller lifecycle.
  await h.emit("agent_settled", { aborted: true });
  expect(h.captures()).toBe(1);
});

for (const event of ["session_start", "session_shutdown", "session_tree"]) {
  test(`${event} drops local response tracking, not shared protection, and ignores old completion`, async () => {
    const h = harness();
    h.succeed();
    const old = h.controller.begin(h.ctx);
    await h.emit(event);
    h.controller.finish(old, undefined, true);
    await h.emit("agent_settled");
    expect(h.captures()).toBe(0);
    h.succeed();
    await h.emit("agent_settled");
    expect(h.captures()).toBe(1);
  });
}

for (const replacement of ["session", "cwd"]) {
  test(`${replacement} change invalidates unfinished response before its next tool`, async () => {
    const h = harness();
    h.succeed();
    const old = h.controller.begin(h.ctx);
    if (replacement === "session") h.session("other"); else h.ctx.cwd = "/other";
    const current = h.controller.begin(h.ctx);
    expect(current.lifetime).not.toBe(old.lifetime);
    h.controller.finish(old, undefined, true);
    await h.emit("agent_settled");
    expect(h.captures()).toBe(0);
  });
}

test("controller forwards capture context/signal and resets cancel a suspended capture", async () => {
  let capturedSignal!: AbortSignal;
  let release!: () => void;
  const output = spyOn(console, "error").mockImplementation(() => {});
  try {
    const h = harness(async (ctx, signal) => {
      expect(ctx).toBe(h.ctx);
      capturedSignal = signal;
      await new Promise<void>(resolve => { release = resolve; });
      throw new Error("obsolete capture");
    });
    h.succeed();
    const pending = h.emit("agent_settled");
    expect(capturedSignal.aborted).toBe(false);
    await h.emit("session_tree");
    expect(capturedSignal.aborted).toBe(true);
    release();
    await pending;
    expect(output).not.toHaveBeenCalled();
  } finally { output.mockRestore(); }
});

test("actual capture/command errors report once, without becoming checkpoint replies", async () => {
  const output = spyOn(console, "error").mockImplementation(() => {});
  try {
    const h = harness(async () => { throw new Error("jj exited 7: failed"); });
    h.succeed();
    await h.emit("agent_settled");
    expect(output).toHaveBeenCalledTimes(1);
    expect(output.mock.calls[0][0]).toContain("jj exited 7: failed");
    const call = h.controller.begin(h.ctx);
    h.controller.finish(call, { error: "bb exited 8: checker failed" }, true);
    await h.emit("agent_settled");
    expect(output).toHaveBeenCalledTimes(1);
  } finally { output.mockRestore(); }
});

test("fresh controllers capture independently without restore/export and read-only workers do nothing", async () => {
  let stored: string | null = null;
  const a = harness(async () => { stored = "a".repeat(40); });
  a.succeed();
  await a.emit("agent_settled");
  await a.emit("session_shutdown");
  expect(stored).toBe("a".repeat(40));
  const b = harness(async () => { stored = "b".repeat(40); });
  await b.emit("session_start");
  await b.emit("agent_settled");
  expect(stored).toBe("a".repeat(40));
  b.succeed();
  await b.emit("agent_settled");
  expect(stored).toBe("b".repeat(40));
});

test("native checker subprocesses get per-call identity, never stale inherited session metadata", () => {
  const old = { PI_SESSION_ID: process.env.PI_SESSION_ID, PI_SESSION_FILE: process.env.PI_SESSION_FILE };
  process.env.PI_SESSION_ID = "stale-session";
  process.env.PI_SESSION_FILE = "/stale/session.jsonl";
  try {
    const h = harness();
    const env = nativeBoundaryEnvironment(h.ctx);
    expect(env.PI_CALL_MODEL).toBe("model-a");
    expect(env.PI_SESSION_ID).toBe("session-a");
    expect(env.PI_SESSION_FILE).toBeUndefined();
    expect(process.env.PI_SESSION_FILE).toBe("/stale/session.jsonl");
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
