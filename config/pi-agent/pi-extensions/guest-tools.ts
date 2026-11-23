import { guestContextProjection } from "./guest-context.ts";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  createBashTool, createEditTool, createEditToolDefinition, createFindTool, createGrepTool,
  createLsTool, createReadTool, createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  rewritePiResourcePaths, guestToolInputToHost,
} from "./guest-tools-core.ts";
import {
  createGuestAttachment, initializeToolExecution, isRoutedTool, registerRoutedTool,
} from "../../../libexec/pi-tool-execution.ts";
export { createGuestAttachment, waitForGuestToolReady } from "../../../libexec/pi-tool-execution.ts";

export default function guestTools(pi: ExtensionAPI) {
  initializeToolExecution(pi);
  const attachment = createGuestAttachment(process.env);
  if (!attachment) return;
  const { cwd, repository, resourcePaths, previousCwd } = attachment;
  if (!cwd) throw new Error("guest working directory is unavailable");
  pi.on("session_start", () => attachment.ready());
  const projectContext = guestContextProjection(attachment);
  // Reload can update this extension while the launcher environment stays old.
  // Keep guest tools attached and clear stale facts rather than guessing from cwd.
  if (!repository) {
    console.error("Sandbox repository context is unavailable; start a new sandbox to enable it.");
  }
  // Routed tools normalize only after their call's placement is captured.
  // Unadapted host tools retain the existing path mapping.
  pi.on("tool_call", (event) => {
    if (!isRoutedTool(pi, event.toolName)) guestToolInputToHost(event.toolName, event.input, resourcePaths);
  });
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
    registerRoutedTool(pi, tool, { guest: "builtin", sandboxDefault: "guest", hostInSandbox: false });
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
  pi.on("context_with_system", async (event, ctx) => ({
    messages: await projectContext(event.messages, ctx),
  }));
}
