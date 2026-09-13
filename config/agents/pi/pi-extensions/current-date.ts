import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function currentDate(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => ({
    systemPrompt: `${event.systemPrompt}\n\nToday's date: ${localDate()}.`,
  }));
}
