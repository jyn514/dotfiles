import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import contextBreakdown from "./context-breakdown.ts";
import currentDate from "./current-date.ts";
import skillReferenceAutocomplete from "./skill-reference-autocomplete.ts";
import instructionIncludes from "./pi-instruction-includes.ts";
import lunaCompaction from "./luna-compaction.ts";
import notifyWhenSettled from "./pi-notify.ts";
import promptHistorySearch from "./prompt-history-search.ts";
import sessionTitle from "./session-title.ts";
import subagentRouting from "./subagent-routing.ts";
import systemPrompt from "./system-prompt.ts";
import webSearch from "./pi-web-search.ts";

export default function dotfilesExtensions(pi: ExtensionAPI) {
  contextBreakdown(pi);
  currentDate(pi);
  skillReferenceAutocomplete(pi);
  lunaCompaction(pi);
  notifyWhenSettled(pi);
  instructionIncludes(pi);
  promptHistorySearch(pi);
  sessionTitle(pi);
  subagentRouting(pi);
  systemPrompt(pi);
  webSearch(pi);
}
