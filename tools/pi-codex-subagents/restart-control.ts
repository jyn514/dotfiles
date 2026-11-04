import { chmodSync, unlinkSync } from "node:fs";
import { createServer, type Server, type Socket } from "node:net";
import { isAbsolute } from "node:path";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { SuspensionCoordinator } from "./suspension.js";

const COMMAND = "sandbox-restart-control";
const MAX_REQUEST_BYTES = 16 * 1024;

type Operation = "pause" | "unpause" | "shutdown";
type Request = { version: 1; id: string; operation: Operation };

interface PendingRequest {
  operation: Operation;
  socket: Socket;
}

function parseRequest(line: string): Request {
  const value = JSON.parse(line) as Partial<Request>;
  if (value.version !== 1 || !/^[A-Za-z0-9-]{1,128}$/.test(value.id ?? "")
    || !["pause", "unpause", "shutdown"].includes(value.operation ?? "")) {
    throw new Error("Invalid sandbox restart control request");
  }
  return value as Request;
}

function reply(socket: Socket, id: string, error?: unknown): void {
  const response = error === undefined
    ? { version: 1, id, ok: true }
    : { version: 1, id, ok: false, error: error instanceof Error ? error.message : String(error) };
  socket.end(`${JSON.stringify(response)}\n`);
}

export interface RestartController {
  close(): Promise<void>;
}

export function startRestartController(pi: ExtensionAPI,
  suspension: SuspensionCoordinator): RestartController | undefined {
  const path = process.env.CODEX_SANDBOX_PI_CONTROL;
  if (!path || !isAbsolute(path)) return undefined;
  const pending = new Map<string, PendingRequest>();
  let server: Server | undefined;

  pi.registerCommand(COMMAND, {
    allowedWhilePaused: true,
    description: "Internal sandbox restart control",
    handler: async (args: string, ctx: ExtensionCommandContext) => {
      const id = args.trim();
      const request = pending.get(id);
      if (!request) return ctx.ui?.notify?.("Sandbox restart control request is unavailable.", "error");
      pending.delete(id);
      try {
        if (request.operation === "pause") await suspension.pause(ctx, false);
        else if (request.operation === "unpause") await suspension.unpause(ctx);
        reply(request.socket, id);
        if (request.operation === "shutdown") setImmediate(() => ctx.shutdown());
      } catch (error) {
        reply(request.socket, id, error);
      }
    },
  });

  server = createServer(socket => {
    socket.setEncoding("utf8");
    let buffer = "";
    let accepted = false;
    const fail = (error: unknown) => {
      if (!socket.destroyed) reply(socket, "", error);
    };
    socket.on("data", chunk => {
      if (accepted) return;
      buffer += chunk;
      if (buffer.length > MAX_REQUEST_BYTES) return fail(new Error("Sandbox restart control request is too large"));
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      accepted = true;
      try {
        const request = parseRequest(buffer.slice(0, newline));
        if (pending.has(request.id)) throw new Error("Duplicate sandbox restart control request");
        pending.set(request.id, { operation: request.operation, socket });
        pi.sendUserMessage(`/${COMMAND} ${request.id}`, { expandPromptTemplates: true });
      } catch (error) {
        fail(error);
      }
    });
    socket.on("error", () => {
      for (const [id, request] of pending) if (request.socket === socket) pending.delete(id);
    });
  });
  server.listen(path, () => chmodSync(path, 0o600));
  server.on("error", error => {
    for (const [id, request] of pending) {
      pending.delete(id);
      reply(request.socket, id, error);
    }
  });

  return {
    close() {
      for (const [id, request] of pending) {
        pending.delete(id);
        reply(request.socket, id, new Error("Pi is shutting down"));
      }
      return new Promise<void>(resolve => {
        if (!server?.listening) return resolve();
        server.close(() => {
          try { unlinkSync(path); } catch { /* owner cleanup also removes the private directory */ }
          resolve();
        });
      });
    },
  };
}
