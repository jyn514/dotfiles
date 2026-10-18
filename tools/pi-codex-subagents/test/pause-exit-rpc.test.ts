import { expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { getAgentDir, SessionManager } from "@earendil-works/pi-coding-agent";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, productionIndex, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("RPC pause --exit publishes Saved and closes captured child safely; a get_state wake triggers existing shutdown", async () => {
  const { getAgent, getRunsDir, parentScopeKey } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "rpc-pause-exit-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child-tool");
  const files = heldToolFiles(marker);
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-parent-roundtrip.md");
  writeFileSync(templateFile, `---\nname: source-parent-roundtrip\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${heldExtension}\n---\n`);
  const rpc = sourceRpc(cwd, parentFile, false, [productionIndex]);
  try {
    const initial = await rpc.request({ type: "get_state" });
    const parentId = initial.sessionId;
    const groupFile = join(getRunsDir(), parentScopeKey(parentId), "group.json");
    const group = () => JSON.parse(readFileSync(groupFile, "utf8"));
    await rpc.request({ type: "prompt", message: `parent-held-task:${marker}` });
    await until(() => existsSync(files.started) && rpc.records.some(record => record.type === "tool_execution_start" && record.toolName === "wait_agent"),
      "real parent waits while its child tool is held");
    const child = getAgent("native-child", parentId)!;
    const childPid = child.childProcess!.pid;
    const childSessionId = SessionManager.open(child.sessionFile).getSessionId();
    const pause = rpc.request({ type: "prompt", message: "/pause --exit" });
    await until(() => existsSync(files.pauseRequested), "child observes the real native pause fence");
    expect(group().phase).toBe("preparing");
    expect(group().parent.handoff.wasActive).toBe(true);
    expect(jsonl(files.effects)).toHaveLength(0);
    writeFileSync(files.release, "release child boundary");
    expect((await pause).disposition).toBe("handled");

    // This is the durable state BEFORE any wake command or stdin EOF.
    const saved = group();
    expect(saved.phase, JSON.stringify(saved)).toBe("saved");
    expect(saved.parentId).toBe(parentId);
    expect(saved.parent.handoff.sessionId).toBe(parentId);
    expect(saved.parent.handoff.sessionFile).toBe(parentFile);
    expect(Object.keys(saved.children)).toEqual([child.id]);
    expect(saved.children[child.id].handoff.wasActive).toBe(true);
    expect(saved.children[child.id].handoff.sessionId).toBe(childSessionId);
    expect(saved.children[child.id].handoff.sessionFile).toBe(child.sessionFile);
    expect(getAgent("native-child", parentId)!.status).toBe("suspended");
    expect(getAgent("native-child", parentId)!.childProcess).toBeUndefined();
    let childAlive = true;
    try { process.kill(childPid, 0); } catch (error: any) {
      if (error.code !== "ESRCH") throw error;
      childAlive = false;
    }
    expect(childAlive).toBe(false);
    expect(jsonl(files.effects)).toHaveLength(1);
    const results = SessionManager.open(child.sessionFile).getBranch().filter((entry: any) =>
      entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "faux_hold");
    expect(results).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(child.sessionFile))).toHaveLength(1);
    expect(saved.completions.mailbox).toEqual([]);
    await delay(50);
    // Core RPC checks shutdownRequested before async prompt handling completes.
    // Document the existing client wake requirement without adding a fixture exit.
    expect(rpc.child.exitCode).toBeNull();
    expect(group().phase).toBe("saved");
    const wake = await rpc.request({ type: "get_state" });
    expect(wake.sessionId).toBe(parentId);
    expect(wake.pauseState).toBe("paused");
    await until(() => rpc.child.exitCode !== null, "get_state invokes shipped RPC's existing shutdown check");
    expect(await rpc.exited).toBe(0);
    expect(group().phase).toBe("saved");
    expect(group().children[child.id].handoff).toEqual(saved.children[child.id].handoff);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(child.sessionFile))).toHaveLength(1);
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);
