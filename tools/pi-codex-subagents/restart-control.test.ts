import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { createConnection } from "node:net";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { RESTART_STATE_CHANNEL, type RestartState, type RestartStateDiscovery } from "../../libexec/pi-restart-state.ts";
import { startRestartController, type RestartController } from "./restart-control.js";

const roots: string[] = [];
const events = new EventEmitter();
let controller: RestartController | undefined;

afterEach(async () => {
  await controller?.close();
  controller = undefined;
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
  delete process.env.CODEX_SANDBOX_PI_CONTROL;
  events.removeAllListeners();
});

async function until(predicate: () => boolean): Promise<void> {
  const deadline = Date.now() + 2_000;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("condition timed out");
    await Bun.sleep(10);
  }
}

function request(path: string, operation: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(path);
    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(`${JSON.stringify({
      version: 1, id: randomUUID(), operation,
    })}\n`));
    socket.on("data", chunk => { buffer += chunk; });
    socket.on("error", reject);
    socket.on("end", () => resolve(JSON.parse(buffer)));
  });
}

test("sandbox restart control dispatches pause, unpause, and acknowledged shutdown", async () => {
  const root = join(tmpdir(), `restart-control-${randomUUID()}`);
  roots.push(root); mkdirSync(root);
  const path = join(root, "control.sock");
  process.env.CODEX_SANDBOX_PI_CONTROL = path;
  let handler: any;
  let shutdown = 0;
  const calls: string[] = [];
  events.on(RESTART_STATE_CHANNEL, (request: RestartStateDiscovery) => request.provide({
    async capture() { await Bun.sleep(1); calls.push("capture"); },
    async restore() { await Bun.sleep(1); calls.push("restore"); },
  }));
  const ctx = { shutdown() { shutdown++; }, ui: { notify() {} } };
  const pi = {
    events,
    registerCommand(_name: string, options: any) { handler = options.handler; },
    sendUserMessage(message: string) {
      const id = message.split(" ", 2)[1];
      queueMicrotask(() => void handler(id, ctx));
    },
  };
  const suspension = {
    async pause(ctx: any, exit: boolean, states: RestartState[]) {
      expect(exit).toBe(false);
      for (const state of states) await state.capture(ctx);
      calls.push("pause");
    },
    async unpause(ctx: any, states: RestartState[]) {
      for (const state of states) await state.restore(ctx);
      calls.push("unpause");
    },
  };
  controller = startRestartController(pi as any, suspension as any);
  expect(controller).toBeDefined();
  await until(() => existsSync(path));

  expect((await request(path, "pause")).ok).toBe(true);
  expect((await request(path, "unpause")).ok).toBe(true);
  expect((await request(path, "shutdown")).ok).toBe(true);
  await until(() => shutdown === 1);
  expect(calls).toEqual(["capture", "pause", "restore", "unpause"]);
});

for (const clientState of ["idle", "half-open reply"] as const) {
  test(`sandbox restart control closes ${clientState} connections during shutdown`, async () => {
    const root = join(tmpdir(), `restart-control-${randomUUID()}`);
    roots.push(root); mkdirSync(root);
    const path = join(root, "control.sock");
    process.env.CODEX_SANDBOX_PI_CONTROL = path;
    let handler: any;
    const ctx = { shutdown() {}, ui: { notify() {} } };
    controller = startRestartController({
      events,
      registerCommand(_name: string, options: any) { handler = options.handler; },
      sendUserMessage(message: string) {
        queueMicrotask(() => void handler(message.split(" ", 2)[1], ctx));
      },
    } as any, { async pause() {}, async unpause() {} } as any);
    await until(() => existsSync(path));

    // The peer need not finish a request or close its writable half after a reply.
    const socket = createConnection({ path, allowHalfOpen: true });
    try {
      await new Promise<void>((resolve, reject) => {
        socket.once("connect", resolve);
        socket.once("error", reject);
      });
      if (clientState === "half-open reply") {
        const response = new Promise<any>((resolve, reject) => {
          let buffer = "";
          socket.setEncoding("utf8");
          socket.on("data", chunk => { buffer += chunk; });
          socket.once("end", () => {
            try { resolve(JSON.parse(buffer)); } catch (error) { reject(error); }
          });
        });
        socket.write(`${JSON.stringify({ version: 1, id: randomUUID(), operation: "pause" })}\n`);
        expect((await response).ok).toBe(true);
      }
      let closed = false;
      const closing = Promise.all([controller!.close(), controller!.close()])
        .then(() => { closed = true; });
      await until(() => closed);
      await closing;
      expect(existsSync(path)).toBe(false);
    } finally {
      socket.destroy();
    }
  });
}

for (const outcome of ["success", "failure", "queued", "cancelled", "legacy-success", "legacy-busy"] as const) {
  test(`sandbox reload control reports ${outcome} after reload teardown`, async () => {
    const root = join(tmpdir(), `reload-control-${randomUUID()}`);
    roots.push(root); mkdirSync(root);
    const path = join(root, "control.sock");
    process.env.CODEX_SANDBOX_PI_CONTROL = path;
    let handler: any;
    let reloadStarted = false;
    let admitted = false;
    let startReload!: () => void;
    let finishReload!: () => void;
    const heldReload = new Promise<void>(resolve => { finishReload = resolve; });
    const ctx = {
      isIdle: () => outcome !== "legacy-busy",
      async reload() {
        reloadStarted = true;
        // Real reload awaits session_shutdown, which closes the old controller.
        await controller!.close("reload");
        await heldReload;
        if (outcome === "failure") throw new Error("resource discovery failed");
      },
      ui: { notify() {} },
    };
    if (!outcome.startsWith("legacy")) Object.assign(ctx, {
      async requestReload(onComplete: (error?: Error) => void) {
        admitted = true;
        const run = async () => {
          try { await ctx.reload(); onComplete(); }
          catch (error) { onComplete(error instanceof Error ? error : new Error(String(error))); }
        };
        startReload = () => { void run(); };
        if (outcome !== "queued" && outcome !== "cancelled") await run();
      },
    });
    const pi = {
      events,
      registerCommand(_name: string, options: any) { handler = options.handler; },
      sendUserMessage(message: string) {
        queueMicrotask(() => void handler(message.split(" ", 2)[1], ctx));
      },
    };
    controller = startRestartController(pi as any, {} as any);
    await until(() => existsSync(path));

    let replied = false;
    const response = request(path, "reload").then(value => { replied = true; return value; });
    try {
      if (outcome === "queued" || outcome === "cancelled") {
        await until(() => admitted);
        expect(replied).toBe(false);
        expect(reloadStarted).toBe(false);
        expect(existsSync(path)).toBe(true);
        if (outcome === "cancelled") {
          await controller!.close("quit");
          const result = await response;
          expect(result.ok).toBe(false);
          expect(result.error).toBe("Pi is shutting down");
          return;
        }
        startReload();
      }
      if (outcome !== "legacy-busy") {
        await until(() => reloadStarted && !existsSync(path));
        expect(replied).toBe(false);
        // The replacement must be able to own the same path before the old
        // request finishes, and late old-controller cleanup must leave it alone.
        const replacement = startRestartController(pi as any, {} as any)!;
        try {
          await until(() => existsSync(path));
          finishReload();
          const result = await response;
          expect(result.ok).toBe(outcome !== "failure");
          if (outcome === "failure") expect(result.error).toBe("resource discovery failed");
          await controller!.close();
          expect(existsSync(path)).toBe(true);
        } finally {
          await replacement.close();
        }
      } else {
        const result = await response;
        expect(result.ok).toBe(false);
        expect(result.error).toContain("busy");
        expect(reloadStarted).toBe(false);
        expect(existsSync(path)).toBe(true);
      }
    } finally {
      finishReload();
    }
  });
}

test("sandbox restart control returns suspension failures without shutting down", async () => {
  const root = join(tmpdir(), `restart-control-${randomUUID()}`);
  roots.push(root); mkdirSync(root);
  const path = join(root, "control.sock");
  process.env.CODEX_SANDBOX_PI_CONTROL = path;
  let handler: any;
  const ctx = { shutdown() { throw new Error("unexpected shutdown"); }, ui: { notify() {} } };
  const pi = {
    events,
    registerCommand(_name: string, options: any) { handler = options.handler; },
    sendUserMessage(message: string) {
      queueMicrotask(() => void handler(message.split(" ", 2)[1], ctx));
    },
  };
  controller = startRestartController(pi as any, {
    async pause() { throw new Error("capture failed"); }, async unpause() {},
  } as any);
  await until(() => existsSync(path));

  const response = await request(path, "pause");
  expect(response.ok).toBe(false);
  expect(response.error).toBe("capture failed");
});
