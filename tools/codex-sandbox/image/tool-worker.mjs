import { createServer } from "node:net";

const toolModule = process.env.CODEX_SANDBOX_PI_TOOL_MODULE ??
  "/opt/agent-pi/src/packages/coding-agent/dist/core/tools/index.js";
const { createAllTools, createLocalBashOperations } = await import(toolModule);

const socketPath = process.env.CODEX_SANDBOX_TOOL_SOCKET ?? "/tmp/codex-tool-worker.sock";
const tools = createAllTools(process.cwd());
const maxRequestBytes = 8 * 1024 * 1024;

function send(socket, message) {
  if (!socket.destroyed) socket.write(`${JSON.stringify(message)}\n`);
}

const server = createServer((socket) => {
  const controller = new AbortController();
  let input = Buffer.alloc(0);
  let started = false;
  let settled = false;

  socket.on("close", () => {
    if (!settled) controller.abort();
  });
  socket.on("data", (chunk) => {
    if (started) {
      socket.destroy();
      return;
    }
    input = Buffer.concat([input, chunk]);
    if (input.length > maxRequestBytes) {
      started = true;
      send(socket, { kind: "error", message: "tool request is too large" });
      socket.end();
      return;
    }
    const newline = input.indexOf(10);
    if (newline < 0) return;
    if (newline !== input.length - 1) {
      started = true;
      send(socket, { kind: "error", message: "unexpected data after tool request" });
      socket.end();
      return;
    }
    started = true;
    void (async () => {
      try {
        const request = JSON.parse(input.subarray(0, newline).toString("utf8"));
        if (!request || typeof request !== "object" ||
            typeof request.tool !== "string" || !request.params ||
            typeof request.params !== "object" || Array.isArray(request.params)) {
          throw new Error("invalid tool request");
        }
        let result;
        if (request.tool === "user_bash") {
          if (typeof request.params.command !== "string") throw new Error("invalid bash command");
          result = await createLocalBashOperations().exec(
            request.params.command, process.cwd(), {
              signal: controller.signal,
              timeout: request.params.timeout,
              onData: (data) => send(socket, { kind: "data", data: data.toString("base64") }),
            },
          );
        } else {
          if (!Object.hasOwn(tools, request.tool)) throw new Error("unknown tool");
          const tool = tools[request.tool];
          result = await tool.execute(
            request.id ?? "guest-tool", request.params, controller.signal,
            (partialResult) => send(socket, { kind: "update", result: partialResult }),
          );
        }
        send(socket, { kind: "result", result });
      } catch (error) {
        send(socket, { kind: "error", message: error instanceof Error ? error.message : String(error) });
      } finally {
        settled = true;
        socket.end();
      }
    })();
  });
});

server.maxConnections = 32;
server.listen(socketPath);
process.on("SIGTERM", () => server.close());
process.on("SIGINT", () => server.close());
