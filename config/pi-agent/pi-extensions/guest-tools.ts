import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { lstat, watch } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";
import { expandInstructionFile } from "./pi-instruction-includes.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createBashTool, createEditTool, createEditToolDefinition, createFindTool, createGrepTool,
  createLsTool, createReadTool, createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  parsePiResourcePaths, resourcePath, rewritePiResourcePaths, guestToolInputToHost,
  sessionToolMetadataToGuest, sessionToolTextToGuest,
} from "./guest-tools-core.ts";
import type { BoundaryMetadata } from "./commit-boundary.ts";

type CallModel = { provider: string; modelId: string } | null;

type CallContext = {
  cwd?: string;
  model: CallModel;
  session: { id: string; file: string | null } | null;
};

function callContext(ctx: ExtensionContext, resourcePaths: Record<string, string>, launchCwd: string | undefined): CallContext {
  const model = ctx.model;
  const id = ctx.sessionManager.getSessionId();
  const file = ctx.sessionManager.getSessionFile();
  const cwd = resourcePath(ctx.cwd, resourcePaths);
  return {
    // Old workers reject unknown fields. Keep their launch-directory request
    // shape until a caller actually needs per-call cwd support.
    ...(cwd === launchCwd ? {} : { cwd }),
    model: model ? { provider: model.provider, modelId: model.id } : null,
    session: id ? { id, file: file ? rewritePiResourcePaths(file, resourcePaths) : null } : null,
  };
}

type GuestFrame =
  | { kind: "update"; result: unknown }
  | { kind: "data"; data: string }
  | { kind: "result"; result: any; boundary?: BoundaryMetadata }
  | { kind: "error"; message: string; boundary?: BoundaryMetadata };

type BoundaryCall = {
  onBoundary: (metadata: BoundaryMetadata | undefined) => void;
};

export async function waitForGuestToolReady(path?: string): Promise<void> {
  if (!path) return;
  const inspect = async () => {
    try {
      const metadata = await lstat(path, { bigint: false });
      if (!metadata.isFile() || metadata.uid !== process.getuid?.() || (metadata.mode & 0o777) !== 0o600) {
        throw new Error("guest tool worker published invalid readiness");
      }
      return true;
    } catch (error: any) {
      if (error?.code === "ENOENT") return false;
      throw error;
    }
  };
  if (await inspect()) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const events = watch(dirname(path), { signal: controller.signal });
    if (await inspect()) return;
    for await (const event of events) {
      if (event.filename === basename(path) && await inspect()) return;
    }
  } catch (error: any) {
    if (error?.name === "AbortError") throw new Error("guest tool worker did not become ready");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  throw new Error("guest tool worker readiness watch ended");
}

function boundaryReply(metadata: BoundaryMetadata | undefined) {
  if (metadata === undefined) return undefined;
  if (!metadata || Object.keys(metadata).length !== 1 || typeof metadata.error !== "string") {
    throw new Error("invalid guest boundary error");
  }
  return metadata;
}

function callGuest(
  attachment: { connector?: string; container: string; command?: string },
  tool: string,
  params: Record<string, unknown>,
  context: CallContext,
  signal?: AbortSignal,
  onUpdate?: (result: any) => void,
  onData?: (data: Buffer) => void,
  boundary?: BoundaryCall,
): Promise<any> {
  const { connector, container, command } = attachment;
  if (!connector) {
    return Promise.reject(new Error("guest tool attachment is unavailable"));
  }
  return new Promise((resolve, reject) => {
    // Keep ordinary child environment current, but never select a different
    // worker/engine halfway through this extension runtime's attachment.
    const child = spawn("python3", [connector], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, CODEX_SANDBOX_TOOL_CONTAINER: container, CODEX_SANDBOX_TOOL_COMMAND: command },
    });
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
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (data: string) => {
      pending += data;
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
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (data: string) => {
      errorText = (errorText + data).slice(-4096);
    });
    child.on("close", (status) => {
      signal?.removeEventListener("abort", abort);
      if (signal?.aborted) reject(new Error("guest tool cancelled"));
      else if (protocolError) reject(protocolError);
      else if (pending || !terminal) reject(new Error(errorText || `guest tool transport ended (${status})`));
      else {
        try {
          if (boundary && (terminal.kind === "result" || terminal.kind === "error")) {
            boundary.onBoundary(boundaryReply(terminal.boundary));
          }
          if (terminal.kind === "error") reject(new Error(terminal.message));
          else if (terminal.kind === "result") resolve(terminal.result);
        } catch (error) {
          reject(error);
        }
      }
    });
  });
}

/** Bind only launch-selected resources, once per extension initialization/reload.
 * Cwd and model/session identity are copied from Pi at each invocation, never here.
 */
export function createGuestAttachment(env: NodeJS.ProcessEnv) {
  const container = env.CODEX_SANDBOX_TOOL_CONTAINER;
  if (!container) return undefined;
  const transport = {
    container,
    connector: env.CODEX_SANDBOX_TOOL_CONNECT,
    command: env.CODEX_SANDBOX_TOOL_COMMAND,
  };
  const resourcePaths = parsePiResourcePaths(env.CODEX_SANDBOX_PI_RESOURCE_PATHS);
  const readyPath = env.CODEX_SANDBOX_TOOL_READY_HOST;
  const launchCwd = env.CODEX_SANDBOX_GUEST_CWD;
  return {
    cwd: launchCwd,
    repository: env.CODEX_SANDBOX_GUEST_REPO,
    previousCwd: env.CODEX_SANDBOX_PREVIOUS_CWD,
    resourcePaths,
    workingDirectory: (ctx: Pick<ExtensionContext, "cwd">) => resourcePath(ctx.cwd, resourcePaths),
    context: (ctx: ExtensionContext) => callContext(ctx, resourcePaths, launchCwd),
    ready: () => waitForGuestToolReady(readyPath),
    call: callGuest.bind(undefined, transport),
  };
}

export default function guestTools(pi: ExtensionAPI) {
  const attachment = createGuestAttachment(process.env);
  if (!attachment) return;
  const { cwd, repository, resourcePaths, previousCwd } = attachment;
  if (!cwd) throw new Error("guest working directory is unavailable");
  pi.on("session_start", () => attachment.ready());
  const sandboxContext = repository
    ? readFileSync(new URL("../../agents/sandbox-context.md", import.meta.url), "utf8")
      .replaceAll("{{repository}}", () => repository).trim()
    : null;
  // Reload can update this extension while the launcher environment stays old.
  // Keep guest tools attached and clear stale facts rather than guessing from cwd.
  if (!repository) {
    console.error("Sandbox repository context is unavailable; start a new sandbox to enable it.");
  }
  // Session tools and subagent launch run on the host. Translate their path
  // inputs without changing transcript contents or decoding opaque cursors.
  pi.on("tool_call", (event) => guestToolInputToHost(event.toolName, event.input, resourcePaths));
  const hostRepository = Object.entries(resourcePaths)
    .find(([, guestPath]) => guestPath === repository)?.[0];
  const instructionFiles = [
    ...(hostRepository ? [join(hostRepository, ".agents/sandbox/AGENTS.md")] : []),
    join(homedir(), ".agents/sandbox/AGENTS.md"),
  ];
  const previousGuestCwd = previousCwd && rewritePiResourcePaths(previousCwd, resourcePaths);
  pi.on("session_start", (event, ctx) => {
    const cwd = attachment.workingDirectory(ctx);
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
  const edit = createEditToolDefinition(cwd);
  const guestEdit: typeof edit = {
    ...createEditTool(cwd),
    // Guest paths do not name host files. Never start Pi's local edit preview;
    // show only the guest's actual diff or error through its result renderer.
    renderCall(args, theme, context) {
      return new Text(`${theme.fg("toolTitle", theme.bold("edit"))} ${args.path ?? "..."}`, context.outputPad, 0);
    },
    renderResult(result, options, theme, context) {
      return edit.renderResult!(result, options, theme, { ...context, state: {} });
    },
  };
  const tools = [
    createReadTool(cwd), createBashTool(cwd), guestEdit,
    createWriteTool(cwd), createGrepTool(cwd), createFindTool(cwd), createLsTool(cwd),
  ];
  for (const tool of tools) {
    pi.registerTool({
      ...tool,
      async execute(id, params, signal, onUpdate, ctx) {
        return attachment.call(tool.name, params as Record<string, unknown>, attachment.context(ctx), signal, onUpdate);
      },
    });
  }
  pi.on("user_bash", (_event, ctx) => {
    const context = attachment.context(ctx);
    return {
      operations: {
        exec: (command, _cwd, { onData, signal, timeout }) =>
          attachment.call("user_bash", { command, timeout }, context, signal, undefined, onData),
      },
    };
  });
  pi.on("context_with_system", async (event, ctx) => {
    const cwd = attachment.workingDirectory(ctx);
    const instructions: string[] = [];
    for (const path of instructionFiles) {
      if (existsSync(path)) instructions.push(await expandInstructionFile(path));
    }
    const sandboxInstructions = instructions.length
      ? rewritePiResourcePaths(instructions.join("\n\n"), resourcePaths)
      : null;
    // Project the guest view for every request, including structured system patches
    // and resumed history that startup hooks cannot rewrite.
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
        if (message.role === "toolResult" &&
          (message.toolName === "search_sessions" || message.toolName === "read_session")) {
          return {
            ...message,
            details: sessionToolMetadataToGuest(message.details, resourcePaths),
            content: message.content.map((block) => block.type === "text"
              ? { ...block, text: sessionToolTextToGuest(message.toolName, block.text, message.details, resourcePaths) }
              : block),
          };
        }
        // Link identities can contain paths; project only cwd lines, not names or host UI metadata.
        if (message.role === "toolResult" && message.toolName === "link_list") {
          return {
            ...message,
            content: message.content.map((block) => block.type === "text"
              ? { ...block, text: block.text.replace(/^([ \t]+cwd: )(.+)$/gm,
                (_line: string, label: string, path: string) => label + rewritePiResourcePaths(path, resourcePaths)) }
              : block),
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
