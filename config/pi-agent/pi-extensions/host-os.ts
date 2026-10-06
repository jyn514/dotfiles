import { readFileSync } from "node:fs";
import { release, type } from "node:os";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export function hostOSName(
  system = type(),
  version = release(),
  readFile = (path: string) => readFileSync(path, "utf8"),
): string {
  if (system === "Linux") {
    for (const path of ["/etc/os-release", "/usr/lib/os-release"]) {
      let contents: string;
      try {
        contents = readFile(path);
      } catch {
        continue;
      }
      const value = contents.match(/^PRETTY_NAME=(.*)$/m)?.[1].trim();
      if (value) {
        // os-release uses shell quoting; never execute its contents.
        const name = value.startsWith('"') && value.endsWith('"')
          ? value.slice(1, -1).replace(/\\(["\\$`])/g, "$1")
          : value.startsWith("'") && value.endsWith("'")
            ? value.slice(1, -1)
            : value;
        if (name) return name;
      }
      // /etc/os-release takes precedence, even if it has no display name.
      break;
    }
  }
  return `${system} ${version}`;
}

export default function hostOS(pi: ExtensionAPI): void {
  // Pi runs on the host even when its shell tools run in the guest.
  const name = hostOSName();
  pi.on("before_agent_start", (event) => {
    event.systemPromptOptions.sections.host_os = `User's host OS: ${name}.\nThis identifies the machine running Pi, not necessarily the shell-tool environment.`;
  });
}
