import { expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createConnection } from "node:net";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { getRunsDir, parentScopeKey } from "../core.ts";
import { productionIndex, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);

function control(path: string, operation: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(path);
    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(`${JSON.stringify({
      version: 1, id: randomUUID(), operation,
    })}\n`));
    socket.on("data", chunk => { buffer += chunk; });
    socket.on("error", reject);
    socket.on("end", () => resolve(JSON.parse(buffer)));
  });
}

sourceTest("external restart control durably pauses, shuts down, reopens, and unpauses", async () => {
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "restart-control-native-"));
  const manager = SessionManager.create(cwd, join(cwd, "sessions"));
  const sessionFile = manager.getSessionFile()!;
  mkdirSync(join(cwd, "sessions"), { recursive: true });
  writeFileSync(sessionFile, `${JSON.stringify(manager.getHeader())}\n`);
  const groupFile = join(getRunsDir(), parentScopeKey(manager.getSessionId()), "group.json");
  const firstControl = join(cwd, "first.sock");
  const first = sourceRpc(cwd, sessionFile, false, [productionIndex], {
    CODEX_SANDBOX_PI_CONTROL: firstControl,
  });
  try {
    await first.request({ type: "get_state" });
    await until(() => existsSync(firstControl), "first restart controller listens");
    expect((await control(firstControl, "pause")).ok).toBe(true);
    expect(JSON.parse(readFileSync(groupFile, "utf8")).phase).toBe("saved");
    expect((await first.request({ type: "get_state" })).pauseState).toBe("paused");
    expect((await control(firstControl, "shutdown")).ok).toBe(true);
    // RPC mode checks its shutdown flag after a command; the interactive TUI
    // owns its own shutdown loop and needs no wake request.
    await first.request({ type: "get_state" });
    expect(await first.exited).toBe(0);

    const secondControl = join(cwd, "second.sock");
    const second = sourceRpc(cwd, sessionFile, false, [productionIndex], {
      CODEX_SANDBOX_PI_CONTROL: secondControl,
    });
    try {
      await second.request({ type: "get_state" });
      await until(() => existsSync(secondControl), "replacement restart controller listens");
      expect((await control(secondControl, "unpause")).ok).toBe(true);
      expect((await second.request({ type: "get_state" })).pauseState).toBe("unpaused");
      expect(JSON.parse(readFileSync(groupFile, "utf8")).phase).toBe("consumed");
    } finally {
      await second.close();
    }
  } finally {
    if (first.child.exitCode === null) await first.close();
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20_000);
