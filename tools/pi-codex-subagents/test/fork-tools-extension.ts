import { writeFileSync } from "node:fs";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** No-I/O tools distinguish registration from restored native activation. */
export default function forkTools(pi: ExtensionAPI) {
  for (const [name, defaultActive] of [["fork_default_active", true], ["fork_default_inactive", false]] as const) {
    pi.registerTool({ name, defaultActive, label: name, description: "Fork selection fixture.", parameters: Type.Object({}),
      async execute() { return { content: [{ type: "text", text: name }], details: {} }; } });
  }
  const source = process.env.PI_TEST_FORK_SOURCE === "1";
  if (source) {
    pi.registerTool({ name: "fork_source_only", label: "Source-only fixture", description: "Unavailable in child configuration.",
      parameters: Type.Object({}), async execute() { return { content: [{ type: "text", text: "source only" }], details: {} }; } });
  }
  pi.on("session_start", (_event, ctx) => {
    if (source) pi.setActiveTools(["read", "grep", "fork_source_only"]);
    writeFileSync(`${ctx.sessionManager.getSessionFile()}.fork-tools.json`, JSON.stringify({
      registered: pi.getAllTools().map(tool => tool.name), active: pi.getActiveTools(),
    }));
  });
}
