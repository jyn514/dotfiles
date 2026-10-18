import { afterEach, describe, expect, spyOn, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import notifyWhenSettled from "../../config/pi-agent/pi-extensions/pi-notify";

const originalTmux = process.env.TMUX;
afterEach(() => {
  if (originalTmux === undefined) delete process.env.TMUX;
  else process.env.TMUX = originalTmux;
});

function settle(mode: string) {
  let handler: (event: unknown, ctx: { mode: string }) => void;
  notifyWhenSettled({
    on(event: string, callback: typeof handler) {
      expect(event).toBe("agent_settled");
      handler = callback;
    },
  } as never);
  const output = spyOn(process.stdout, "write").mockImplementation(() => true);
  try {
    handler!({}, { mode });
    return output.mock.calls.map(([text]) => text).join("");
  } finally {
    output.mockRestore();
  }
}

describe("settled terminal notifications", () => {
  test("sends OSC 777 directly outside tmux", () => {
    delete process.env.TMUX;
    expect(settle("tui")).toBe("\x1b]777;notify;Pi;Ready for input\x07");
  });

  test("rings tmux separately from its escaped desktop notification", () => {
    process.env.TMUX = "/tmp/tmux-1000/default,123,0";
    expect(settle("tui")).toBe("\x07\x1bPtmux;\x1b\x1b]777;notify;Pi;Ready for input\x07\x1b\\");
  });

  test.skipIf(spawnSync("tmux", ["-V"]).status !== 0)("sets a real tmux window bell alert", async () => {
    const directory = mkdtempSync(join(tmpdir(), "pi-notify-"));
    const socket = join(directory, "socket");
    const fifo = join(directory, "output");
    function tmux(...args: string[]) {
      const result = spawnSync("tmux", ["-S", socket, ...args], { encoding: "utf8" });
      expect(result.status).toBe(0);
      return result.stdout.trim();
    }
    try {
      expect(spawnSync("mkfifo", [fifo]).status).toBe(0);
      tmux("-f", "/dev/null", "new-session", "-d", "-s", "notify", `cat '${fifo}'; sleep 30`);
      tmux("set-option", "-g", "allow-passthrough", "on");
      process.env.TMUX = `${socket},123,0`;
      writeFileSync(fifo, settle("tui"));
      let bell = "";
      for (let attempt = 0; attempt < 100; attempt++) {
        bell = tmux("display-message", "-p", "-t", "notify:0", "#{window_bell_flag}");
        if (bell === "1") break;
        await Bun.sleep(10);
      }
      expect(bell).toBe("1");
    } finally {
      spawnSync("tmux", ["-S", socket, "kill-server"]);
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("does not write terminal controls in non-TUI modes", () => {
    for (const tmux of [undefined, "/tmp/tmux-1000/default,123,0"]) {
      if (tmux === undefined) delete process.env.TMUX;
      else process.env.TMUX = tmux;
      for (const mode of ["print", "json", "rpc"]) expect(settle(mode)).toBe("");
    }
  });
});
