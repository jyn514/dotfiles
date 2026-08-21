import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function notifyWhenSettled(pi: ExtensionAPI) {
  pi.on("agent_settled", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    process.stdout.write("\x1b]777;notify;Pi;Ready for input\x07");
  });
}
