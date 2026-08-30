import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import currentDate from "./current-date.ts";
import instructionIncludes from "./pi-instruction-includes.ts";
import notifyWhenSettled from "./pi-notify.ts";
import promptHistorySearch from "./prompt-history-search.ts";
import systemPrompt from "./system-prompt.ts";
import webSearch from "./pi-web-search.ts";

export default function dotfilesExtensions(pi: ExtensionAPI) {
  currentDate(pi);
  notifyWhenSettled(pi);
  instructionIncludes(pi);
  promptHistorySearch(pi);
  systemPrompt(pi);
  webSearch(pi);
}
