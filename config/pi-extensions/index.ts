import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import instructionIncludes from "./pi-instruction-includes.ts";
import notifyWhenSettled from "./pi-notify.ts";
import webSearch from "./pi-web-search.ts";

export default function dotfilesExtensions(pi: ExtensionAPI) {
  notifyWhenSettled(pi);
  instructionIncludes(pi);
  webSearch(pi);
}
