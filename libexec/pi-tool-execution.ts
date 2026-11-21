import { spawn } from "node:child_process";
import { lstat, watch } from "node:fs/promises";
import { basename, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";
import {
  parsePiResourcePaths, resourcePath, rewritePiResourcePaths, guestToolInputToHost,
} from "../config/pi-agent/pi-extensions/guest-tools-core.ts";
import type { BoundaryMetadata } from "../config/pi-agent/pi-extensions/commit-boundary.ts";

export type ToolExecutionTarget = "host" | "guest";

export type WorkerEntry = {
  /** The registering module's import.meta.url; mapped to the guest at admission. */
  module: string;
  export: string;
};

/** Constructed by the worker, never a serialized host ExtensionContext. */
export type ToolExecutionContext = {
  cwd: string;
  agentDir: string;
  piModule: string;
  model: { provider: string; modelId: string } | null;
  session: { id: string; file: string | null } | null;
  signal: AbortSignal;
  onUpdate: (result: any) => void;
};

export type ToolExecutionOptions = {
  guest: WorkerEntry | "builtin";
  /** Outside a sandbox the default is always host. Explicit guest never falls back. */
  sandboxDefault?: ToolExecutionTarget;
  /** Built-in filesystem/process tools cannot use host access inside a sandbox. */
  hostInSandbox?: boolean;
  onData?: (data: Buffer) => void;
};

export type ToolExecutionMetadata = {
  target: ToolExecutionTarget;
  source: "default" | "settings";
};

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
  | { kind: "error"; message: string; code?: string; boundary?: BoundaryMetadata };

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
  entry?: WorkerEntry,
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
    child.stdin.write(`${JSON.stringify({ tool, params, ...context, ...(entry ? { entry } : {}) })}\n`);
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
          if (terminal.kind === "error") {
            // Older workers reject the new top-level entry before dispatch.
            const unsupported = entry && terminal.message === "invalid tool request";
            const error = new Error(unsupported
              ? `guest worker does not accept portable entry requests for ${tool}; restart the sandbox with an updated worker (${terminal.message})`
              : terminal.message);
            if (unsupported) Object.assign(error, { code: "WORKER_PROTOCOL_UNSUPPORTED" });
            else if (typeof terminal.code === "string") Object.assign(error, { code: terminal.code });
            reject(error);
          }
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

type RoutedRegistration = {
  name: string;
  options: ToolExecutionOptions;
  attachment: ReturnType<typeof createGuestAttachment>;
  refresh: () => void;
};

type ExecutionQuery = { initialized: boolean; registrations: RoutedRegistration[] };
const executionChannel = "dotfiles:tool-execution:registrations";

// Extension factories receive different API objects, and reload may give modules
// separate import caches. Pi's runtime-owned event bus is the shared owner; its
// tracked subscriptions disappear when that extension runtime is replaced.
function executionQuery(pi: ExtensionAPI): ExecutionQuery {
  const query: ExecutionQuery = { initialized: false, registrations: [] };
  pi.events.emit(executionChannel, query);
  return query;
}

function executionSettings(pi: ExtensionAPI): Record<string, ToolExecutionTarget> {
  const settings = pi.getSettings() as { sandbox?: unknown };
  if (settings.sandbox === undefined) return {};
  if (!settings.sandbox || typeof settings.sandbox !== "object" || Array.isArray(settings.sandbox)) {
    throw new Error("sandbox settings must be an object");
  }
  const raw = (settings.sandbox as { toolExecution?: unknown }).toolExecution;
  if (raw === undefined) return {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("sandbox.toolExecution must be an object");
  }
  for (const [name, target] of Object.entries(raw)) {
    if (target !== "host" && target !== "guest") {
      throw new Error(`sandbox.toolExecution.${name} must be "host" or "guest", got ${JSON.stringify(target)}`);
    }
  }
  return raw as Record<string, ToolExecutionTarget>;
}

function executionRoute(
  name: string, settings: Record<string, ToolExecutionTarget>,
  options: ToolExecutionOptions, attached: boolean,
): ToolExecutionMetadata {
  const configured = Object.hasOwn(settings, name);
  const target = configured ? settings[name] : attached ? options.sandboxDefault ?? "host" : "host";
  const source = configured ? "settings" : "default";
  const label = `${name} execution: ${target} (${source})`;
  if (target === "guest" && !attached) throw new Error(`${label}: no guest is attached`);
  if (target === "host" && attached && options.hostInSandbox === false) {
    throw new Error(`${label}: sandbox policy requires guest execution`);
  }
  return { target, source };
}

/** Install configuration checks once per Pi runtime, including host-only tools. */
export function initializeToolExecution(pi: ExtensionAPI): void {
  if (executionQuery(pi).initialized) return;
  pi.events.on(executionChannel, (data) => { (data as ExecutionQuery).initialized = true; });
  pi.on("session_start", (_event, ctx) => {
    const settings = executionSettings(pi);
    const registrations = executionQuery(pi).registrations;
    const tools = pi.getAllTools();
    const names = new Set(tools.map(tool => tool.name));
    for (const registration of registrations) registration.refresh();
    for (const [name, target] of Object.entries(settings)) {
      if (!names.has(name)) {
        ctx.ui.notify(`sandbox.toolExecution.${name}: no registered tool; override remains unresolved`, "warning");
      } else if (target === "guest" && !registrations.some(tool => tool.name === name)) {
        throw new Error(`${name} execution: guest (settings): the registered tool has no guest entry point`);
      }
    }
  });
  pi.on("tool_call", (event) => {
    try {
      const settings = executionSettings(pi);
      if (settings[event.toolName] === "guest" &&
          !executionQuery(pi).registrations.some(tool => tool.name === event.toolName)) {
        return { block: true, reason: `${event.toolName} execution: guest (settings): the registered tool has no guest entry point` };
      }
    } catch (error) {
      return { block: true, reason: error instanceof Error ? error.message : String(error) };
    }
  });
}

export function isRoutedTool(pi: ExtensionAPI, name: string): boolean {
  return executionQuery(pi).registrations.some(tool => tool.name === name);
}

/** Read original-call placement from persisted result details, not current settings. */
export function toolExecutionMetadata(details: unknown): ToolExecutionMetadata | undefined {
  if (!details || typeof details !== "object" || Array.isArray(details)) return;
  const value = (details as { toolExecution?: unknown }).toolExecution;
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const metadata = value as ToolExecutionMetadata;
  if ((metadata.target === "host" || metadata.target === "guest") &&
      (metadata.source === "default" || metadata.source === "settings")) return metadata;
}

function workerEntry(entry: WorkerEntry, paths: Record<string, string>): WorkerEntry {
  if (!entry || typeof entry.module !== "string" || typeof entry.export !== "string" ||
      !entry.export || entry.export.includes("\0")) {
    throw new Error("worker entry requires a file module URL and an export name");
  }
  const url = new URL(entry.module);
  if (url.protocol !== "file:" || url.search || url.hash) {
    throw new Error("worker entry module must be a file URL without query or fragment");
  }
  return { module: pathToFileURL(resourcePath(fileURLToPath(url), paths)).href, export: entry.export };
}

/**
 * Register a normal Pi tool with an author-supplied portable operation.
 * The module is an absolute import.meta.url, never relative to call cwd.
 * Registration, schemas, renderers and UI stay on the host. Settings select
 * placement, not exposure or permission. Guest failures are never retried locally.
 */
export function registerRoutedTool<TParams extends TSchema, TDetails>(
  pi: ExtensionAPI, definition: ToolDefinition<TParams, TDetails>, supplied: ToolExecutionOptions,
): void {
  const attachment = createGuestAttachment(process.env);
  const options = { ...supplied, guest: supplied.guest === "builtin" ? "builtin" as const : { ...supplied.guest } };
  // Author descriptors are checked before registering anything executable.
  if (options.guest !== "builtin") workerEntry(options.guest, {});
  const defaultTarget = attachment ? options.sandboxDefault ?? "host" : "host";
  const describe = (route: ToolExecutionMetadata) =>
    `${definition.description}\nExecution: ${route.target} (${route.source}). Supported execution: ${
      attachment && options.hostInSandbox === false ? "guest" : "host, guest (requires an attachment)"}.`;
  const routed: ToolDefinition<TParams, TDetails> = {
    ...definition,
    description: describe({ target: defaultTarget, source: "default" }),
    async execute(id, originalParams, signal, onUpdate, ctx) {
      // Snapshot every placement input before the first asynchronous handoff.
      const route = executionRoute(definition.name, executionSettings(pi), options, !!attachment);
      const label = `${definition.name} execution: ${route.target} (${route.source})`;
      const params = { ...(originalParams as Record<string, unknown>) } as typeof originalParams & Record<string, unknown>;
      let context: CallContext | undefined;
      let entry: WorkerEntry | undefined;
      if (attachment) {
        if (route.target === "host") guestToolInputToHost(definition.name, params, attachment.resourcePaths);
        else {
          if (definition.name === "read_session" && typeof params.sessionFile === "string") {
            params.sessionFile = resourcePath(params.sessionFile, attachment.resourcePaths);
          }
          context = attachment.context(ctx);
          if (options.guest !== "builtin") entry = workerEntry(options.guest, attachment.resourcePaths);
        }
      }
      const annotate = (result: any) => {
        if (!result || typeof result !== "object") return result;
        const details = result.details;
        return {
          ...result,
          ...(details && typeof details === "object" && !Array.isArray(details)
            ? { details: { ...details, toolExecution: route } } : {}),
          ...(route.target === "guest" && result.isError && Array.isArray(result.content)
            ? { content: [...result.content, { type: "text", text: label }] } : {}),
        };
      };
      try {
        const result = route.target === "guest"
          ? await attachment!.call(definition.name, params, context!, signal,
            onUpdate ? result => onUpdate(annotate(result)) : undefined, options.onData, undefined, entry)
          : await definition.execute(id, params, signal,
            onUpdate ? result => onUpdate(annotate(result)) : undefined, ctx);
        return annotate(result);
      } catch (error) {
        const failure = new Error(`${label}: ${error instanceof Error ? error.message : String(error)}`, { cause: error });
        if (error && typeof error === "object" && "code" in error && typeof error.code === "string") {
          Object.assign(failure, { code: error.code });
        }
        throw failure;
      }
    },
  };
  const registration: RoutedRegistration = {
    name: definition.name, options, attachment,
    refresh: () => {
      routed.description = describe(executionRoute(definition.name, executionSettings(pi), options, !!attachment));
      // Re-registration refreshes metadata but normally activates direct tools.
      // Placement must not undo defaultTools or a caller's inactive selection.
      const active = pi.getActiveTools();
      pi.registerTool(routed);
      pi.setActiveTools(active);
    },
  };
  pi.events.on(executionChannel, data => (data as ExecutionQuery).registrations.push(registration));
  initializeToolExecution(pi);
  pi.registerTool(routed);
}
