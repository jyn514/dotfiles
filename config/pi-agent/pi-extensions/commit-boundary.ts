import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createEditTool, createWriteTool } from "@earendil-works/pi-coding-agent";
import { captureCheckpoint, createBoundaryTool } from "./commit-boundary/operations.mjs";

export type BoundaryMetadata = { error: string };
type Capture = (ctx: ExtensionContext, signal: AbortSignal) => Promise<unknown>;

/** Response tracking is local; protection belongs only to the workspace record. */
export function createBoundaryController(pi: ExtensionAPI, capture: Capture) {
  let session: string | undefined;
  let cwd: string | undefined;
  let lifetime = {};
  let wrote = false;
  let reported = false;
  let captureAbort = new AbortController();

  const reset = () => {
    captureAbort.abort();
    captureAbort = new AbortController();
    wrote = false;
    lifetime = {};
  };
  const synchronize = (ctx: ExtensionContext) => {
    const nextSession = ctx.sessionManager.getSessionId();
    if (session !== nextSession || cwd !== ctx.cwd) {
      reset();
      session = nextSession;
      cwd = ctx.cwd;
    }
  };
  const report = (message: string) => {
    if (reported) return;
    reported = true;
    console.error(`Commit-boundary checker unavailable: ${message}`);
  };
  for (const event of ["session_start", "session_tree"] as const) {
    pi.on(event, (_event, ctx) => { reset(); synchronize(ctx); });
  }
  pi.on("session_shutdown", reset);
  pi.on("agent_settled", async (event, ctx) => {
    synchronize(ctx);
    if (event.aborted) { reset(); return; }
    if (!wrote) return;
    wrote = false;
    const active = lifetime;
    try { await capture(ctx, captureAbort.signal); }
    catch (error) {
      if (active === lifetime) report(error instanceof Error ? error.message : String(error));
    }
  });
  return {
    begin(ctx: ExtensionContext) {
      synchronize(ctx);
      return { lifetime };
    },
    finish(call: { lifetime: object }, metadata: BoundaryMetadata | undefined, successfulWrite: boolean) {
      if (call.lifetime !== lifetime) return;
      if (metadata?.error) report(metadata.error);
      if (successfulWrite) wrote = true;
    },
  };
}

export function nativeBoundaryEnvironment(ctx: ExtensionContext) {
  const env: NodeJS.ProcessEnv = { ...process.env, PI_CALL_MODEL: ctx.model?.id ?? "" };
  delete env.PI_SESSION_ID;
  delete env.PI_SESSION_FILE;
  const id = ctx.sessionManager.getSessionId();
  const file = ctx.sessionManager.getSessionFile();
  if (id) {
    env.PI_SESSION_ID = id;
    if (file) env.PI_SESSION_FILE = file;
  }
  return env;
}

export default function commitBoundary(pi: ExtensionAPI) {
  // guest-tools owns the same controller when structured tools run remotely.
  if (process.env.CODEX_SANDBOX_TOOL_CONTAINER) return;
  const boundary = createBoundaryController(pi, (ctx, signal) =>
    captureCheckpoint(ctx.cwd, { signal, env: nativeBoundaryEnvironment(ctx) }));
  const factories = { createEditTool, createWriteTool };
  for (const name of ["edit", "write"] as const) {
    const template = name === "edit" ? createEditTool(process.cwd()) : createWriteTool(process.cwd());
    pi.registerTool({
      ...template,
      async execute(id, params, signal, onUpdate, ctx) {
        const call = boundary.begin(ctx);
        const guarded = createBoundaryTool(factories, name, ctx.cwd, {
          signal, env: nativeBoundaryEnvironment(ctx),
        });
        let successfulWrite = false;
        try {
          const result = await guarded.tool.execute(id, params, signal, onUpdate, ctx);
          successfulWrite = !result.isError;
          return result;
        } finally {
          boundary.finish(call, guarded.metadata(), successfulWrite);
        }
      },
    });
  }
}
