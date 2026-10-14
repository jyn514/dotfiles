import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { expandInstructionFile } from "./pi-instruction-includes.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createBashTool, createEditTool, createFindTool, createGrepTool,
  createLsTool, createReadTool, createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { rewritePiResourcePaths } from "./guest-tools-core.ts";

type CallModel = { provider: string; modelId: string } | null;

type CallContext = {
  model: CallModel;
  session: { id: string; file: string | null } | null;
};

function guestResourcePaths(): Record<string, string> {
  const paths = JSON.parse(process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS || "{}");
  if (Object.entries(paths).some(([hostPath, guestPath]) =>
    !hostPath.startsWith("/") || typeof guestPath !== "string" || !guestPath.startsWith("/"))) {
    throw new Error("Pi resource path mapping is invalid");
  }
  return paths;
}

export function callContext(ctx: ExtensionContext): CallContext {
  const model = ctx.model;
  const id = ctx.sessionManager.getSessionId();
  const file = ctx.sessionManager.getSessionFile();
  return {
    model: model ? { provider: model.provider, modelId: model.id } : null,
    session: id ? { id, file: file ? rewritePiResourcePaths(file, guestResourcePaths()) : null } : null,
  };
}

type GuestFrame =
  | { kind: "update"; result: unknown }
  | { kind: "data"; data: string }
  | { kind: "result"; result: any }
  | { kind: "error"; message: string };

export function callGuest(
  tool: string,
  params: Record<string, unknown>,
  context: CallContext,
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
    child.stdin.write(`${JSON.stringify({ tool, params, ...context })}\n`);
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
  const repository = process.env.CODEX_SANDBOX_GUEST_REPO;
  const sandboxContext = repository
    ? readFileSync(new URL("../../agents/sandbox-context.md", import.meta.url), "utf8")
      .replaceAll("{{repository}}", () => repository).trim()
    : null;
  // Reload can update this extension while the launcher environment stays old.
  // Keep guest tools attached and clear stale facts rather than guessing from cwd.
  if (!repository) {
    console.error("Sandbox repository context is unavailable; start a new sandbox to enable it.");
  }
  const resourcePaths = guestResourcePaths();
  const hostRepository = Object.entries(resourcePaths)
    .find(([, guestPath]) => guestPath === repository)?.[0];
  const instructionFiles = [
    ...(hostRepository ? [join(hostRepository, ".agents/sandbox/AGENTS.md")] : []),
    join(homedir(), ".agents/sandbox/AGENTS.md"),
  ];
  const previousCwd = process.env.CODEX_SANDBOX_PREVIOUS_CWD;
  const previousGuestCwd = previousCwd && rewritePiResourcePaths(previousCwd, resourcePaths);
  pi.on("session_start", (event, ctx) => {
    if (event.reason !== "startup" && event.reason !== "reload") return;
    if (!previousGuestCwd || previousGuestCwd === cwd) return;
    // A cross-directory resume first restarts in the selected session's directory.
    // Do not append to that source session while its handoff is still pending.
    if (ctx.sessionManager.getCwd() !== ctx.cwd) return;
    const sessionId = ctx.sessionManager.getSessionId();
    if (ctx.sessionManager.getBranch().some((entry) =>
      entry.type === "custom_message" && entry.customType === "sandbox-handoff"
      && (entry.details as { sessionId?: string } | undefined)?.sessionId === sessionId)) return;
    pi.sendMessage({
      customType: "sandbox-handoff", display: false,
      details: { sessionId, previousDirectory: previousGuestCwd, currentDirectory: cwd },
      content: [
        `Working directory switched from ${previousGuestCwd} to ${cwd}.`,
        "Continue the user's objective.",
        "This switch authorizes work in the destination within that objective.",
        "Before making changes, read the destination's repository instructions and inspect working-copy state and change ownership.",
        "Older paths remain historical context.",
      ].join("\n"),
    }, { triggerTurn: false });
  });
  const tools = [
    createReadTool(cwd), createBashTool(cwd), createEditTool(cwd),
    createWriteTool(cwd), createGrepTool(cwd), createFindTool(cwd), createLsTool(cwd),
  ];
  for (const tool of tools) {
    pi.registerTool({
      ...tool,
      execute: (id, params, signal, onUpdate, ctx) =>
        callGuest(tool.name, params as Record<string, unknown>, callContext(ctx), signal, onUpdate),
    });
  }
  pi.on("user_bash", (_event, ctx) => {
    const context = callContext(ctx);
    return {
      operations: {
        exec: (command, _cwd, { onData, signal, timeout }) =>
          callGuest("user_bash", { command, timeout }, context, signal, undefined, onData),
      },
    };
  });
  pi.on("context_with_system", async (event) => {
    const instructions: string[] = [];
    for (const path of instructionFiles) {
      if (existsSync(path)) instructions.push(await expandInstructionFile(path));
    }
    const sandboxInstructions = instructions.length
      ? rewritePiResourcePaths(instructions.join("\n\n"), resourcePaths)
      : null;
    // Goal-triggered runs skip before_agent_start. Project the guest view at
    // request time, including structured system patches and resumed history.
    const rewriteSystem = (text: string) => rewritePiResourcePaths(text, resourcePaths)
      .replace(/^Current working directory: .*$/m, () => `Current working directory: ${cwd}`)
      .replace(/<cwd>\n[^\n]*\n<\/cwd>/g, () => `<cwd>\n${cwd}\n</cwd>`);
    const rewriteSkill = (text: string) =>
      /^<skill name="[^"]+" location="[^"]+">\n/.test(text)
        ? rewritePiResourcePaths(text, resourcePaths)
        : text;
    let firstSystem = true;
    return {
      messages: event.messages.map((message) => {
        if (message.role === "system") {
          const sections = Object.fromEntries(
            Object.entries(message.sections ?? {}).map(([name, text]) =>
              [name, text === null ? null : rewriteSystem(text)]),
          );
          if (firstSystem || message.sections?.sandbox_context !== undefined) {
            sections.sandbox_context = sandboxContext;
          }
          if (firstSystem || message.sections?.sandbox_instructions !== undefined) {
            sections.sandbox_instructions = sandboxInstructions;
          }
          firstSystem = false;
          return {
            ...message,
            content: typeof message.content === "string"
              ? rewriteSystem(message.content)
              : message.content.map((block) => ({ ...block, text: rewriteSystem(block.text) })),
            ...(sections ? { sections } : {}),
          };
        }
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
}
