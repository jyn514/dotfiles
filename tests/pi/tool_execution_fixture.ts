import { Type } from "typebox";
import { registerRoutedTool } from "../../libexec/pi-tool-execution.ts";

export async function delayedGuest(_params: unknown, ctx: { onUpdate: (value: unknown) => void }) {
  ctx.onUpdate({ content: [{ type: "text", text: "guest admitted" }], details: {} });
  await new Promise(resolve => setTimeout(resolve, 300));
  return { content: [{ type: "text", text: "guest completed" }], details: {} };
}

export default function fixture(pi: any) {
  registerRoutedTool(pi, { name: "fixture_delay", label: "fixture", description: "fixture",
    parameters: Type.Object({}), execute: async () => ({ content: [{ type: "text", text: "host completed" }], details: {} }),
  }, { guest: { module: import.meta.url, export: "delayedGuest" }, sandboxDefault: "guest" });
}
