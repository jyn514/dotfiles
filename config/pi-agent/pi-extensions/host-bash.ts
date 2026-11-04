import { isAbsolute } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { guardianHistory, guardianParentHistory, reviewedHostCommand, type HostAuthorityContext } from "./host-bash-core.ts";
import { RESTART_STATE_CHANNEL, type RestartStateDiscovery } from "../../../libexec/pi-restart-state.ts";

const parameters = Type.Object({
  command: Type.String({ minLength: 1, description: "Bash command to run on the host" }),
  sandbox_permissions: Type.Optional(Type.Union([Type.Literal("use_default"), Type.Literal("require_escalated")], {
    description: "use_default keeps the sandbox (default); require_escalated requests broader host access.",
  })),
  justification: Type.Optional(Type.String({ minLength: 1, description: "For escalation: cite the failed attempt and explain the needed access" })),
  cwd: Type.Optional(Type.String({ description: "Absolute host execution directory; defaults to Pi's host working directory. Changing cwd does not expand sandbox write access." })),
  timeout: Type.Optional(Type.Number({ minimum: 1, maximum: 3600, description: "Execution timeout in seconds (default 60); review has a separate timeout" })),
});

const WORKSPACE_ENV = "PI_HOST_BASH_WORKSPACE";
const AUTHORITY_ENV = "PI_HOST_BASH_AUTHORITY_CONTEXT";
const RESTART_ENTRY = "host-bash-restart";

/** Human-selected, session-local host capability. Ordinary tools retain their guest attachment.
 * PI_HOST_CODEX_BIN selects a native Codex executable without installing or upgrading it.
 * Managed children inherit the enabled workspace through their launch environment.
 * Every call still owns a disposable Codex thread and its own policy/Guardian decision.
 */
export default function hostBash(pi: ExtensionAPI): void {
  const executable = process.env.PI_HOST_CODEX_BIN || "codex";
  const inherited = process.env.PI_SUBAGENT_ID && process.env.PI_SUBAGENT_PARENT_SESSION_ID
    ? process.env[WORKSPACE_ENV] : undefined;
  const inheritedWorkspace = inherited && isAbsolute(inherited) ? inherited : undefined;
  const managedChild = Boolean(process.env.PI_SUBAGENT_ID && process.env.PI_SUBAGENT_PARENT_SESSION_ID);
  const inheritedAuthority = managedChild ? process.env[AUTHORITY_ENV] : undefined;
  let enabled = false;
  let session: string | undefined;
  let workspace: string | undefined;
  let authority: HostAuthorityContext | undefined;
  const publishAuthority = (ctx: ExtensionContext) => {
    if (!enabled || session !== ctx.sessionManager.getSessionId()) return;
    if (!managedChild) {
      const file = ctx.sessionManager.getSessionFile();
      const leafId = ctx.sessionManager.getLeafId();
      authority = file && leafId && workspace ? {
        file, leafId, sessionId: ctx.sessionManager.getSessionId(), workspace,
      } : undefined;
    }
    if (authority) process.env[AUTHORITY_ENV] = JSON.stringify(authority);
    else delete process.env[AUTHORITY_ENV];
  };
  const active = new Set<AbortController>();
  const disable = (ctx: ExtensionContext) => {
    enabled = false;
    workspace = undefined;
    authority = undefined;
    delete process.env[WORKSPACE_ENV];
    delete process.env[AUTHORITY_ENV];
    for (const controller of active) controller.abort();
    pi.setActiveTools(pi.getActiveTools().filter(name => name !== "host_bash"));
    ctx.ui.setStatus("host-bash", undefined);
  };
  const enable = (ctx: ExtensionContext, root: string) => {
    // Pi's registration allowlist cannot be widened by inherited activation.
    if (!pi.getAllTools().some(tool => tool.name === "host_bash")) return false;
    enabled = true;
    session = ctx.sessionManager.getSessionId();
    workspace = root;
    if (managedChild && inheritedAuthority) {
      try {
        const parsed = JSON.parse(inheritedAuthority);
        if (parsed.workspace === root && isAbsolute(parsed.file) && typeof parsed.leafId === "string"
          && typeof parsed.sessionId === "string") authority = parsed;
      } catch { /* Missing or invalid human context prevents child execution below. */ }
    }
    process.env[WORKSPACE_ENV] = root;
    publishAuthority(ctx);
    pi.setActiveTools([...new Set([...pi.getActiveTools(), "host_bash"])]);
    ctx.ui.setStatus("host-bash", "host: auto-review");
    return true;
  };
  const captureRestartState = (ctx: ExtensionContext) => {
    pi.appendEntry(RESTART_ENTRY, {
      version: 1, sessionId: ctx.sessionManager.getSessionId(),
      workspace: enabled && session === ctx.sessionManager.getSessionId() ? workspace : null,
    });
  };
  pi.events.on(RESTART_STATE_CHANNEL, (request: RestartStateDiscovery) => {
    request.provide({
      capture: captureRestartState,
      restore(ctx) {
        const entry = ctx.sessionManager.getEntries().findLast(
          item => item.type === "custom" && item.customType === RESTART_ENTRY,
        );
        const saved = entry?.type === "custom" ? entry.data as {
          version?: unknown; sessionId?: unknown; workspace?: unknown;
        } | undefined : undefined;
        // Loading history never restores access. Only the restart controller
        // calls this, and neither a fork nor a different workspace can reuse it.
        if (saved?.version === 1 && saved.sessionId === ctx.sessionManager.getSessionId()
          && typeof saved.workspace === "string" && saved.workspace === ctx.cwd) {
          enable(ctx, saved.workspace);
        }
      },
    });
  });
  pi.on("session_start", (event, ctx) => {
    disable(ctx);
    session = ctx.sessionManager.getSessionId();
    if (event.reason === "startup" && inheritedWorkspace) enable(ctx, inheritedWorkspace);
  });
  pi.on("session_shutdown", (_event, ctx) => disable(ctx));
  // The launcher snapshots process.env at dispatch. Refresh the parent's branch
  // after new user input, without treating a child's assignment as human input.
  pi.on("before_agent_start", (_event, ctx) => publishAuthority(ctx));
  pi.on("tool_call", (_event, ctx) => publishAuthority(ctx));
  pi.registerCommand("host", {
    description: "Toggle sandboxed host_bash with automatic approval review (/host on|off)",
    handler: async (argument, ctx) => {
      const choice = argument.trim();
      if (choice && choice !== "on" && choice !== "off") {
        ctx.ui.notify("Usage: /host [on|off]", "warning");
        return;
      }
      if (choice === "off" || (!choice && enabled)) {
        disable(ctx);
        captureRestartState(ctx);
        ctx.ui.notify("host_bash disabled", "info");
        return;
      }
      if (!enable(ctx, ctx.cwd)) {
        ctx.ui.notify("host_bash is excluded by this session's tool allowlist", "warning");
        return;
      }
      ctx.ui.notify("host_bash enabled; host commands run in Codex's sandbox. Guardian reviews actions requiring approval. Ordinary tools stay in the guest.", "info");
    },
  });
  pi.registerTool({
    name: "host_bash", label: "host bash", defaultActive: false,
    description: "Run Bash on the host in Codex's workspace sandbox. Use host paths. Escalate only after a failed sandboxed attempt shows that broader access would resolve a sandbox restriction. Stop on policy or Guardian denial.",
    promptSnippet: "Run host Bash in Codex's sandbox, with Guardian review for escalation",
    parameters,
    async execute(_id, params, signal, _onUpdate, ctx) {
      if (!enabled || !workspace || session !== ctx.sessionManager.getSessionId()) {
        throw new Error("Host execution is disabled. Use /host or inherit it from an enabled parent.");
      }
      const hostWorkspace = workspace;
      const parentAuthority = managedChild ? authority : undefined;
      const cwd = params.cwd ?? ctx.cwd;
      if (!isAbsolute(cwd)) throw new Error("host_bash cwd must be an absolute host path");
      const controller = new AbortController();
      active.add(controller);
      const combined = AbortSignal.any([controller.signal, ...(signal ? [signal] : [])]);
      // A hung server must not leave an approval pending forever. Native review has its own deadline.
      const timeout = setTimeout(() => controller.abort(), ((params.timeout ?? 60) + 120) * 1000);
      // Guest runtime images stage the extension bundle without host-only libexec.
      // Load the shared transport only when the human enables host execution.
      let client: any;
      let failed = false;
      try {
        const { CodexClient } = await import(new URL("../../../libexec/codex-client.mjs", import.meta.url).href);
        client = new CodexClient({ command: executable, signal: combined, cwd: hostWorkspace });
        await client.initialize({ name: "pi_host_bash", version: "1" });
        if (managedChild && !parentAuthority) throw new Error("Inherited host execution needs the parent's saved human context");
        const history = [
          ...(parentAuthority ? await guardianParentHistory(parentAuthority) : []),
          ...guardianHistory(ctx.sessionManager.getBranch(), managedChild),
        ];
        const result = await reviewedHostCommand(client, history, {
          command: params.command, workspace: hostWorkspace, cwd, timeout: params.timeout ?? 60, justification: params.justification,
          sandbox_permissions: params.sandbox_permissions,
        });
        return {
          content: [{ type: "text", text: `Host working directory: ${cwd}\nExecution: ${result.execution}\n${result.stdout}${result.stderr}\nExit code: ${result.exitCode}\nGuardian: ${result.review?.rationale ?? "not required by exec policy"}` }],
          isError: result.exitCode !== 0,
          details: { cwd, exitCode: result.exitCode, review: result.review, execution: result.execution },
        };
      } catch (error) {
        failed = true;
        throw error;
      } finally {
        clearTimeout(timeout);
        active.delete(controller);
        // Preserve a denial or cancellation if cleanup also reports a killed server.
        try { await client?.close(); } catch (error) { if (!failed) throw error; }
      }
    },
  });
}
