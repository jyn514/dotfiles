import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { expandInstructionFile } from "./pi-instruction-includes.ts";
import {
  rewritePiResourcePaths, sessionToolMetadataToGuest, sessionToolTextToGuest,
} from "./guest-tools-core.ts";
import { createGuestAttachment, toolExecutionMetadata } from "../../../libexec/pi-tool-execution.ts";

/** The same request projection for normal parent turns and generated checkpoints.
 * Bind launch-selected paths once, but read instructions and caller cwd for each
 * request. Stored history, quoted evidence, routing and tool execution stay intact.
 */
export function guestContextProjection(attachment = createGuestAttachment(process.env)) {
  if (!attachment) return async (messages: AgentMessage[], _ctx: ExtensionContext) => messages;
  if (!attachment.cwd) throw new Error("guest working directory is unavailable");
  const { repository, resourcePaths } = attachment;
  const sandboxContext = repository
    ? readFileSync(new URL("../../agents/sandbox-context.md", import.meta.url), "utf8")
      .replaceAll("{{repository}}", () => repository).trim()
    : null;
  const hostRepository = Object.entries(resourcePaths)
    .find(([, guestPath]) => guestPath === repository)?.[0];
  const instructionFiles = [
    ...(hostRepository ? [join(hostRepository, ".agents/sandbox/AGENTS.md")] : []),
    join(homedir(), ".agents/sandbox/AGENTS.md"),
  ];

  return async (messages: AgentMessage[], ctx: ExtensionContext): Promise<AgentMessage[]> => {
    const cwd = attachment.workingDirectory(ctx);
    const instructions: string[] = [];
    for (const path of instructionFiles) {
      if (existsSync(path)) instructions.push(await expandInstructionFile(path));
    }
    const sandboxInstructions = instructions.length
      ? rewritePiResourcePaths(instructions.join("\n\n"), resourcePaths)
      : null;
    const rewriteSystem = (text: string) => rewritePiResourcePaths(text, resourcePaths)
      .replace(/^Current working directory: .*$/m, () => `Current working directory: ${cwd}`)
      .replace(/<cwd>\n[^\n]*\n<\/cwd>/g, () => `<cwd>\n${cwd}\n</cwd>`);
    const rewriteSkill = (text: string) =>
      /^<skill name="[^"]+" location="[^"]+">\n/.test(text)
        ? rewritePiResourcePaths(text, resourcePaths)
        : text;
    let firstSystem = true;
    return messages.map((message) => {
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
      // Link identities can contain paths; project cwd lines only, not names or host UI metadata.
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
    });
  };
}
