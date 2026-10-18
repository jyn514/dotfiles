import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { CONTROL_COMMAND, CONTINUATION_MESSAGE, controlRecord } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { jsonl, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("native capture waits for the held tool; reopened helper fences provider work until one continuation", async () => {
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "held-tool-"));
  const sessionFile = join(cwd, "child.jsonl");
  const marker = join(cwd, "tool");
  const files = heldToolFiles(marker);
  let rpc = sourceRpc(cwd, sessionFile);
  const generation = "held-real-boundary";
  const control = (action: string, extra = {}) => rpc.request({ type: "prompt", message: `/${CONTROL_COMMAND} ${JSON.stringify({ action, generation, ...extra })}` });
  try {
    const initial = await rpc.request({ type: "get_state" });
    await rpc.request({ type: "prompt", message: `hold-tool:${marker}` });
    await until(() => existsSync(files.started), "real held tool starts");
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(0);
    let captured = false;
    const capture = control("capture").then(value => { captured = true; return value; });
    // An actual RPC round trip observes the native pause request, not just a timer.
    await until(async () => (await rpc.request({ type: "get_state" })).pauseState === "pausing", "capture requested native pause");
    await delay(50);
    expect(captured).toBe(false);
    expect((await rpc.request({ type: "get_state" })).pauseState).toBe("pausing");
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    writeFileSync(files.release, "release");
    await capture;
    expect(existsSync(files.ended)).toBe(true);
    expect(jsonl(files.effects)).toHaveLength(1);
    const entries = (await rpc.request({ type: "get_entries" })).entries;
    const saved = controlRecord(entries, generation, "capture");
    expect(saved?.ok).toBe(true);
    expect(saved?.snapshot?.handoff.wasActive).toBe(true);
    expect(saved?.snapshot?.handoff.sessionId).toBe(initial.sessionId);
    expect(saved?.snapshot?.handoff.sessionFile).toBe(sessionFile);
    expect(entries.filter((entry: any) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "faux_hold")).toHaveLength(1);
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    expect(await rpc.close()).toBe(0);

    rpc = sourceRpc(cwd, sessionFile, true);
    const reopened = await rpc.request({ type: "get_state" });
    expect(reopened.sessionId).toBe(initial.sessionId);
    expect(reopened.sessionFile).toBe(sessionFile);
    expect(reopened.pauseState).toBe("paused");
    const starts = jsonl(templateStartsFile(sessionFile));
    expect(starts).toHaveLength(2);
    expect(starts[1].pause).toBe("paused"); // Helper loaded before template extension.
    expect(starts[1].pid).not.toBe(starts[0].pid);
    await delay(50);
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    await control("arm", { snapshot: saved!.snapshot });
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    const admission = await rpc.request({ type: "prompt", message: CONTINUATION_MESSAGE });
    expect(admission.disposition).toBe("started");
    await control("finish", { disposition: admission.disposition });
    await until(() => rpc.records.some(record => record.type === "agent_settled"), "resumed run settles");
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(2);
    expect(readFileSync(files.ended, "utf8")).toBe(jsonl(files.effects)[0].toolCallId);
  } finally {
    await rpc.close();
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);
