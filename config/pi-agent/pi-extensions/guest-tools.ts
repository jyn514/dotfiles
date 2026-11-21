import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { expandInstructionFile } from "./pi-instruction-includes.ts";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  createBashTool, createEditTool, createEditToolDefinition, createFindTool, createGrepTool,
  createLsTool, createReadTool, createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  parsePiResourcePaths, resourcePath, rewritePiResourcePaths, guestToolInputToHost,
  sessionToolMetadataToGuest, sessionToolTextToGuest,
} from "./guest-tools-core.ts";
import {
  createGuestAttachment, initializeToolExecution, isRoutedTool, registerRoutedTool, toolExecutionMetadata,
} from "../../../libexec/pi-tool-execution.ts";
export { createGuestAttachment, waitForGuestToolReady } from "../../../libexec/pi-tool-execution.ts";

export default function guestTools(pi: ExtensionAPI) {
  initializeToolExecution(pi);
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
  // Routed tools normalize only after their call's placement is captured.
  // Unadapted host tools retain the existing path mapping.
  pi.on("tool_call", (event) => {
    if (!isRoutedTool(pi, event.toolName)) guestToolInputToHost(event.toolName, event.input, resourcePaths);
  });
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
          (message.toolName === "search_sessions" || message.toolName === "read_session") &&
          toolExecutionMetadata(message.details)?.target !== "guest") {
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
