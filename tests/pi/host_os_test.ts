import { describe, expect, test } from "bun:test";
import hostOS, { hostOSName } from "../../config/pi-agent/pi-extensions/host-os";

describe("host OS context", () => {
  test("reads distribution names without executing shell contents", () => {
    for (const [value, expected] of [
      ['"CachyOS"', "CachyOS"],
      ["'Example Linux 1.2'", "Example Linux 1.2"],
      ["Alpine", "Alpine"],
      ['"Example \\"Linux\\" \\$HOME $(false)"', 'Example "Linux" $HOME $(false)'],
    ]) {
      expect(hostOSName("Linux", "6.12", () => `NAME=ignored\nPRETTY_NAME=${value}\n`))
        .toBe(expected);
    }
  });

  test("uses vendor metadata when host metadata cannot be read", () => {
    const paths: string[] = [];
    expect(hostOSName("Linux", "6.12", (path) => {
      paths.push(path);
      if (path === "/etc/os-release") throw new Error("unavailable");
      return 'PRETTY_NAME="Example Linux"\n';
    })).toBe("Example Linux");
    expect(paths).toEqual(["/etc/os-release", "/usr/lib/os-release"]);
  });

  test("falls back when metadata is unavailable or has no display name", () => {
    expect(hostOSName("Linux", "6.12", () => { throw new Error("unavailable"); }))
      .toBe("Linux 6.12");
    for (const contents of ['NAME=Example\n', 'PRETTY_NAME=""\n']) {
      expect(hostOSName("Linux", "6.12", (path) => {
        if (path !== "/etc/os-release") throw new Error("must not merge metadata");
        return contents;
      })).toBe("Linux 6.12");
    }
    expect(hostOSName("Darwin", "25.0", () => { throw new Error("must not read Linux metadata"); }))
      .toBe("Darwin 25.0");
  });

  test("sets host guidance without forcing the prompt or changing other sections", () => {
    let handler: (event: {
      systemPrompt: string;
      systemPromptOptions: { sections: Record<string, string> };
    }) => unknown;
    hostOS({
      on(event: string, callback: typeof handler) {
        expect(event).toBe("before_agent_start");
        handler = callback;
      },
    } as never);
    const event = {
      systemPrompt: "original instructions",
      systemPromptOptions: { sections: { other: "other guidance", host_os: "stale" } },
    };
    const expected = `User's host OS: ${hostOSName()}.\nThis identifies the machine running Pi, not necessarily the shell-tool environment.`;
    for (let turn = 0; turn < 2; turn++) {
      expect(handler!(event)).toBeUndefined();
      expect(event.systemPrompt).toBe("original instructions");
      expect(event.systemPromptOptions.sections).toEqual({
        other: "other guidance",
        host_os: expected,
      });
    }
  });
});
