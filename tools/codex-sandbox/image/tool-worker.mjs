import { createServer } from "node:net";
import { captureCheckpoint, createBoundaryTool } from "./commit-boundary-operations.mjs";

const startupStarted = performance.now();
const toolModule = process.env.CODEX_SANDBOX_PI_TOOL_MODULE ??
  "/opt/agent-pi/src/packages/coding-agent/dist/index.js";
const {
  createReadTool, createBashTool, createPowerShellTool, createEditTool,
  createWriteTool, createGrepTool, createFindTool, createLsTool, createLocalBashOperations,
  getAgentDir, loadSkills,
} = await import(toolModule);
if (process.env.CODEX_SANDBOX_TIMING) {
  process.stderr.write(`Sandbox service: agent/tool-module-import=${
    ((performance.now() - startupStarted) / 1000).toFixed(2)}s\n`);
}
const toolFactories = {
  read: createReadTool, bash: createBashTool, powershell: createPowerShellTool,
  edit: createEditTool, write: createWriteTool, grep: createGrepTool,
  find: createFindTool, ls: createLsTool,
};

const socketPath = process.env.CODEX_SANDBOX_TOOL_SOCKET ?? "/tmp/codex-tool-worker.sock";
const maxRequestBytes = 8 * 1024 * 1024;

// Required even for non-shell tools: null is explicit unknown, not legacy fallback.
function parseCallModel(model) {
  if (model === null) return null;
  if (!model || typeof model !== "object" || Array.isArray(model) ||
      Object.keys(model).length !== 2 || !Object.hasOwn(model, "provider") ||
      !Object.hasOwn(model, "modelId") ||
      [model.provider, model.modelId].some(value =>
        typeof value !== "string" || value.length === 0 || /[\x00-\x1f\x7f-\x9f]/u.test(value))) {
    throw new Error("invalid call model");
  }
  return { provider: model.provider, modelId: model.modelId };
}

function parseCallSession(session) {
  if (session === null) return null;
  if (!session || typeof session !== "object" || Array.isArray(session) ||
      Object.keys(session).length !== 2 ||
      typeof session.id !== "string" || !session.id || /[\x00-\x1f\x7f-\x9f]/u.test(session.id) ||
      !(session.file === null || (typeof session.file === "string" &&
        session.file.startsWith("/") && !/[\x00-\x1f\x7f-\x9f]/u.test(session.file)))) {
    throw new Error("invalid call session");
  }
  return { id: session.id, file: session.file };
}

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
      let guarded;
      const reply = (frame) => {
        const boundary = guarded?.metadata();
        send(socket, { ...frame, ...(boundary ? { boundary } : {}) });
      };
      try {
        const request = JSON.parse(input.subarray(0, newline).toString("utf8"));
        if (!request || typeof request !== "object" ||
            typeof request.tool !== "string" || !request.params ||
            typeof request.params !== "object" || Array.isArray(request.params) ||
            Object.keys(request).some(key => !["tool", "params", "model", "session", "id"].includes(key))) {
          throw new Error("invalid tool request");
        }
        const model = parseCallModel(request.model);
        const session = parseCallSession(request.session);
        // Each request owns its environment; never publish session state globally.
        const callEnv = (base) => {
          const env = { ...base, PI_CALL_MODEL: model?.modelId ?? "" };
          delete env.PI_SESSION_ID;
          delete env.PI_SESSION_FILE;
          if (session) {
            env.PI_SESSION_ID = session.id;
            if (session.file !== null) env.PI_SESSION_FILE = session.file;
          }
          return env;
        };
        let result;
        if (request.tool === "commit_boundary_checkpoint") {
          if (Object.keys(request.params).length !== 0) throw new Error("invalid checkpoint request");
          result = await captureCheckpoint(process.cwd(), {
            signal: controller.signal, env: callEnv(process.env),
          });
        } else if (request.tool === "validate_skill") {
          if (typeof request.params.path !== "string" || request.params.path.length === 0 ||
              Object.keys(request.params).some(key => key !== "path")) {
            throw new Error("invalid skill path request");
          }
          const { skills, diagnostics } = loadSkills({
            cwd: process.cwd(),
            agentDir: getAgentDir(),
            skillPaths: [request.params.path.replace(/^@/, "")],
            includeDefaults: false,
          });
          result = { loaded: skills.length > 0, name: skills[0]?.name, diagnostics };
        } else if (request.tool === "user_bash") {
          if (typeof request.params.command !== "string") throw new Error("invalid bash command");
          result = await createLocalBashOperations().exec(
            request.params.command, process.cwd(), {
              env: callEnv(process.env),
              signal: controller.signal,
              timeout: request.params.timeout,
              onData: (data) => send(socket, { kind: "data", data: data.toString("base64") }),
            },
          );
        } else {
          const spawnHook = context => ({
            ...context, env: callEnv(context.env),
          });
          if (!Object.hasOwn(toolFactories, request.tool)) throw new Error("unknown tool");
          const shellOptions = request.tool === "bash" || request.tool === "powershell"
            ? { spawnHook } : undefined;
          if (request.tool === "edit" || request.tool === "write") {
            guarded = createBoundaryTool({ createEditTool, createWriteTool }, request.tool, process.cwd(), {
              signal: controller.signal, env: callEnv(process.env),
            });
          }
          const tool = guarded?.tool ?? toolFactories[request.tool](process.cwd(), shellOptions);
          result = await tool.execute(
            request.id ?? "guest-tool", request.params, controller.signal,
            (partialResult) => send(socket, { kind: "update", result: partialResult }),
          );
        }
        reply({ kind: "result", result });
      } catch (error) {
        reply({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      } finally {
        settled = true;
        socket.end();
      }
    })();
  });
});

server.maxConnections = 32;
server.listen(socketPath, () => {
  if (process.env.CODEX_SANDBOX_TIMING) {
    process.stderr.write(`Sandbox service: agent/tool-worker-ready=${
      ((performance.now() - startupStarted) / 1000).toFixed(2)}s\n`);
  }
});
process.on("SIGTERM", () => server.close());
process.on("SIGINT", () => server.close());
