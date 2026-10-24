import { appendFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function discoveryProbe(pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    const rel = relative(process.env.PI_TEST_OWNED_ROOT!, ctx.cwd);
    if (rel.startsWith("..") || rel.startsWith("/")) throw new Error("Discovery fixture needs owned cwd");
    appendFileSync(join(ctx.cwd, "discovery-starts.jsonl"), JSON.stringify({
      pid: process.pid, trusted: ctx.isProjectTrusted(), commands: pi.getCommands(), tools: pi.getActiveTools(),
    }) + "\n");
  });
  pi.registerTool({
    name: "discovered_probe", label: "Discovery probe", description: "Record a real discovered tool call.",
    parameters: Type.Object({}),
    async execute(_id, _args, _signal, _update, ctx) {
      writeFileSync(join(ctx.cwd, "discovered-called"), "called");
      return { content: [{ type: "text", text: "discovery tool called" }], details: {} };
    },
  });
}
