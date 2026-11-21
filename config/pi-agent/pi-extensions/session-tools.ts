import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerSessionSearch, { readSessionToolResult, type ReadSessionOptions } from "../../../tools/pi-session-search/index.ts";
import { registerRoutedTool, type ToolExecutionContext } from "../../../libexec/pi-tool-execution.ts";
import { sessionTitleMetadata } from "./session-title.ts";

export async function readSessionWorker(params: ReadSessionOptions, ctx: ToolExecutionContext) {
  const result = await readSessionToolResult(params, ctx.signal);
  if ("isError" in result) {
    result.content[0].text = result.content[0].text.replace("read_session failed:", "read_session failed in guest:");
    return result;
  }
  if (result.details.sessionFile && !Array.isArray(result.details.versions)) {
    const sdk = await import(ctx.piModule);
    Object.assign(result.details, await sessionTitleMetadata(result.details.sessionFile, sdk.SessionManager));
  }
  return result;
}

export default function sessionTools(pi: ExtensionAPI): void {
  const adapter = Object.create(pi) as ExtensionAPI;
  adapter.registerTool = (tool) => {
    if (tool.name === "read_session") {
      registerRoutedTool(pi, tool, { guest: { module: import.meta.url, export: "readSessionWorker" }, sandboxDefault: "host" });
    } else {
      pi.registerTool(tool);
    }
  };
  registerSessionSearch(adapter);
}
