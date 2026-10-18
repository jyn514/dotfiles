import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function notifyWhenSettled(pi: ExtensionAPI) {
  pi.on("agent_settled", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    const notification = "\x1b]777;notify;Pi;Ready for input\x07";
    // Ring tmux itself, then pass OSC 777 to the terminal with doubled ESC bytes.
    // The BEL terminating OSC 777 is not a standalone bell for tmux.
    process.stdout.write(process.env.TMUX
      ? `\x07\x1bPtmux;${notification.replaceAll("\x1b", "\x1b\x1b")}\x1b\\`
      : notification);
  });
}
