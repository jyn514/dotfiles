import {
  defineTool,
  getAgentDir,
  loadSkills,
  truncateHead,
  type ExtensionAPI,
  type ResourceDiagnostic,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { callGuest, callModel } from "./guest-tools.ts";

export const validateSkillTool = defineTool({
  name: "validate_skill",
  label: "Validate skill",
  description: "Check whether Pi can load a SKILL.md file. Returns loaded, name, and Pi's diagnostics. Text output is limited to 2000 lines or 50KB; full diagnostics remain in result details.",
  promptSnippet: "Check whether Pi can load a skill file",
  parameters: Type.Object({
    path: Type.String({ minLength: 1, description: "Path to SKILL.md, relative to the current working directory or absolute" }),
  }),
  async execute(_toolCallId, params, signal, _onUpdate, ctx) {
    let details: { loaded: boolean; name?: string; diagnostics: ResourceDiagnostic[] };
    if (process.env.CODEX_SANDBOX_TOOL_CONTAINER) {
      details = await callGuest("validate_skill", params, callModel(ctx), signal);
    } else {
      const { skills, diagnostics } = loadSkills({
        cwd: ctx.cwd,
        agentDir: getAgentDir(),
        skillPaths: [params.path.replace(/^@/, "")],
        includeDefaults: false,
      });
      details = { loaded: skills.length > 0, name: skills[0]?.name, diagnostics };
    }
    const output = truncateHead(JSON.stringify(details, null, 2));
    return {
      content: [{ type: "text", text: output.content + (output.truncated
        ? "\n[Output truncated; full diagnostics are in result details.]" : "") }],
      details,
    };
  },
});

export default function validateSkill(pi: ExtensionAPI): void {
  pi.registerTool(validateSkillTool);
}
