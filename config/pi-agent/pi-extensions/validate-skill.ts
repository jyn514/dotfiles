import {
  defineTool,
  getAgentDir,
  loadSkills,
  truncateHead,
  type ExtensionAPI,
  type ResourceDiagnostic,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { registerRoutedTool, type ToolExecutionContext } from "../../../libexec/pi-tool-execution.ts";

function validateSkillResult(params: { path: string }, cwd: string, agentDir: string, sdk: { loadSkills: typeof loadSkills; truncateHead: typeof truncateHead }) {
  const { skills, diagnostics } = sdk.loadSkills({
    cwd, agentDir, skillPaths: [params.path.replace(/^@/, "")], includeDefaults: false,
  });
  const details: { loaded: boolean; name?: string; diagnostics: ResourceDiagnostic[] } = {
    loaded: skills.length > 0, name: skills[0]?.name, diagnostics,
  };
  const output = sdk.truncateHead(JSON.stringify(details, null, 2));
  return {
    content: [{ type: "text" as const, text: output.content + (output.truncated
      ? "\n[Output truncated; full diagnostics are in result details.]" : "") }],
    details,
  };
}

export async function validateSkillWorker(params: { path: string }, ctx: ToolExecutionContext) {
  const sdk = await import(ctx.piModule);
  return validateSkillResult(params, ctx.cwd, ctx.agentDir, sdk);
}

export function createValidateSkillTool() {
  const agentDir = getAgentDir();
  return defineTool({
    name: "validate_skill",
    label: "Validate skill",
    description: "Check whether Pi can load a SKILL.md file. Returns loaded, name, and Pi's diagnostics. Text output is limited to 2000 lines or 50KB; full diagnostics remain in result details.",
    promptSnippet: "Check whether Pi can load a skill file",
    parameters: Type.Object({
      path: Type.String({ minLength: 1, description: "Path to SKILL.md, relative to the current working directory or absolute" }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      return validateSkillResult(params, ctx.cwd, agentDir, { loadSkills, truncateHead });
    },
  });
}

export default function validateSkill(pi: ExtensionAPI): void {
  registerRoutedTool(pi, createValidateSkillTool(), {
    guest: { module: import.meta.url, export: "validateSkillWorker" }, sandboxDefault: "guest",
  });
}
