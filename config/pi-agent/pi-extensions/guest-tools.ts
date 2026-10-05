import { spawn } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createBashTool, createEditTool, createFindTool, createGrepTool,
  createLsTool, createReadTool, createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { rewritePiResourcePaths } from "./guest-tools-core.ts";

type CallModel = { provider: string; modelId: string } | null;

function callModel(ctx: ExtensionContext): CallModel {
  const model = ctx.model;
  return model ? { provider: model.provider, modelId: model.id } : null;
}

type GuestFrame =
  | { kind: "update"; result: unknown }
  | { kind: "data"; data: string }
  | { kind: "result"; result: any }
  | { kind: "error"; message: string };

function callGuest(
  tool: string,
  params: Record<string, unknown>,
  model: CallModel,
  signal?: AbortSignal,
  onUpdate?: (result: any) => void,
  onData?: (data: Buffer) => void,
): Promise<any> {
  const connector = process.env.CODEX_SANDBOX_TOOL_CONNECT;
  if (!connector || !process.env.CODEX_SANDBOX_TOOL_CONTAINER) {
    return Promise.reject(new Error("guest tool attachment is unavailable"));
  }
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [connector], { stdio: ["pipe", "pipe", "pipe"] });
    let pending = "";
    let errorText = "";
    let terminal: GuestFrame | undefined;
    let protocolError: Error | undefined;
    const abort = () => child.kill("SIGTERM");
    child.stdin.on("error", (error) => { protocolError = error; });
    child.on("error", (error) => { protocolError = error; });
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    child.stdin.write(`${JSON.stringify({ tool, params, model })}\n`);
    child.stdout.on("data", (data: Buffer) => {
      pending += data.toString("utf8");
      if (pending.length > 32 * 1024 * 1024) {
        protocolError = new Error("guest tool response is too large");
        child.kill("SIGTERM");
        return;
      }
      let newline: number;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        try {
          const frame = JSON.parse(line) as GuestFrame;
          if (frame.kind === "update") onUpdate?.(frame.result);
          else if (frame.kind === "data") onData?.(Buffer.from(frame.data, "base64"));
          else if (frame.kind === "result" || frame.kind === "error") {
            if (terminal) throw new Error("duplicate guest tool result");
            terminal = frame;
            child.stdin.end();
          } else throw new Error("unknown guest tool response");
        } catch (error) {
          protocolError = error instanceof Error ? error : new Error(String(error));
          child.kill("SIGTERM");
          return;
        }
      }
    });
    child.stderr.on("data", (data: Buffer) => {
      errorText = (errorText + data.toString("utf8")).slice(-4096);
    });
    child.on("close", (status) => {
      signal?.removeEventListener("abort", abort);
      if (protocolError) reject(protocolError);
      else if (signal?.aborted) reject(new Error("guest tool cancelled"));
      else if (pending || !terminal) reject(new Error(errorText || `guest tool transport ended (${status})`));
      else if (terminal.kind === "error") reject(new Error(terminal.message));
      else resolve(terminal.result);
    });
  });
}

export default function guestTools(pi: ExtensionAPI) {
  if (!process.env.CODEX_SANDBOX_TOOL_CONTAINER) return;
  const cwd = process.env.CODEX_SANDBOX_GUEST_CWD;
  if (!cwd) throw new Error("guest working directory is unavailable");
  const encodedResourcePaths = process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
  const resourcePaths = encodedResourcePaths
    ? JSON.parse(encodedResourcePaths) as Record<string, string>
    : {};
  if (Object.entries(resourcePaths).some(([hostPath, guestPath]) =>
    !hostPath.startsWith("/") || !guestPath.startsWith("/"))) {
    throw new Error("Pi resource path mapping is invalid");
  }
  const tools = [
    createReadTool(cwd), createBashTool(cwd), createEditTool(cwd),
    createWriteTool(cwd), createGrepTool(cwd), createFindTool(cwd), createLsTool(cwd),
  ];
  for (const tool of tools) {
    pi.registerTool({
      ...tool,
      execute: (id, params, signal, onUpdate, ctx) =>
        callGuest(tool.name, params as Record<string, unknown>, callModel(ctx), signal, onUpdate),
    });
  }
  pi.on("user_bash", (_event, ctx) => {
    const model = callModel(ctx);
    return {
      operations: {
        exec: (command, _cwd, { onData, signal, timeout }) =>
          callGuest("user_bash", { command, timeout }, model, signal, undefined, onData),
      },
    };
  });
  pi.on("context", (event) => {
    // Pi expands /skill commands on the host into user messages, separately
    // from the system prompt. Rewrite the model's copy, including resumed history.
    const rewriteSkill = (text: string) =>
      /^<skill name="[^"]+" location="[^"]+">\n/.test(text)
        ? rewritePiResourcePaths(text, resourcePaths)
        : text;
    return {
      messages: event.messages.map((message) => {
        if (message.role !== "user") return message;
        return {
          ...message,
          content: typeof message.content === "string"
            ? rewriteSkill(message.content)
            : message.content.map((block) => block.type === "text"
              ? { ...block, text: rewriteSkill(block.text) }
              : block),
        };
      }),
    };
  });
  pi.on("before_agent_start", (event) => {
    const rewrittenPrompt = rewritePiResourcePaths(event.systemPrompt, resourcePaths);
    const systemPrompt = rewrittenPrompt.replace(
      `Current working directory: ${event.systemPromptOptions.cwd}`,
      `Current working directory: ${cwd}`,
    ) + (process.env.CODEX_SANDBOX_PREVIOUS_CWD
      ? `\nThis conversation moved from ${rewritePiResourcePaths(process.env.CODEX_SANDBOX_PREVIOUS_CWD, resourcePaths)} to ${cwd}; older paths remain historical context.\n`
      : "");
    return { systemPrompt };
  });
}
