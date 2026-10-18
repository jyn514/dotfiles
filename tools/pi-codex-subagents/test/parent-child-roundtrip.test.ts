import { expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { getAgentDir, SessionManager } from "@earendil-works/pi-coding-agent";
import { CONTINUATION_MESSAGE } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, productionIndex, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const text = (content: any): string => typeof content === "string" ? content : content?.filter((part: any) => part.type === "text").map((part: any) => part.text).join("\n") ?? "";
const toolResults = (file: string, name: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === name) as any[];
const freshMarkers = (file: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "message" && entry.message.role === "user" && text(entry.message.content) === CONTINUATION_MESSAGE);
const completions = (file: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "custom_message" && entry.customType === "pi-codex-subagent-completion") as any[];
const lateSteering = "same-batch steering after pause";
const steeringHistory = (file: string) => SessionManager.open(file).getBranch().filter((entry: any) =>
  (entry.type === "custom_message" && text(entry.content) === lateSteering)
  || (entry.type === "message" && entry.message.role === "user" && text(entry.message.content) === lateSteering));

sourceTest.each(["direct", "nested"])("production index/coordinator saves active parent+child and drains %s same-batch steering before capture", async (mode) => {
  const nested = mode === "nested";
  const laterTool = nested ? "faux_nested_send" : "send_message";
  const parentExtensions = nested ? [productionIndex, heldExtension] : [productionIndex];
  const { getAgent, getRunsDir, parentScopeKey } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "parent-child-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child-tool");
  const files = heldToolFiles(marker);
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-parent-roundtrip.md");
  writeFileSync(templateFile, `---\nname: source-parent-roundtrip\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${heldExtension}\n---\n`);
  // Production index owns Manager/coordinator. The optional test tool uses only
  // public ctx.executeTool; Manager loads child-helper before child template code.
  let rpc = sourceRpc(cwd, parentFile, false, parentExtensions);
  try {
    const initial = await rpc.request({ type: "get_state" });
    const parentId = initial.sessionId;
    const groupFile = join(getRunsDir(), parentScopeKey(parentId), "group.json");
    const group = () => JSON.parse(readFileSync(groupFile, "utf8"));
    await rpc.request({ type: "prompt", message: `parent-${nested ? "nested-" : ""}held-task:${marker}` });
    await until(() => existsSync(files.started) && rpc.records.some(record => record.type === "tool_execution_start" && record.toolName === "wait_agent"),
      "production parent is waiting on its actual held-tool child");
    const child = getAgent("native-child", parentId)!;
    expect(child).toBeTruthy();
    const childId = child.id;
    const childFile = child.sessionFile;
    expect(SessionManager.open(parentFile).getSessionId()).toBe(parentId);
    expect(toolResults(parentFile, "spawn_agent")).toHaveLength(1);
    expect(toolResults(parentFile, "wait_agent")).toHaveLength(0);
    expect(toolResults(parentFile, laterTool)).toHaveLength(0);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(0);

    let pauseReplied = false;
    const pause = rpc.request({ type: "prompt", message: "/pause" }).then(result => { pauseReplied = true; return result; });
    await until(() => existsSync(groupFile) && !!group().parent, "coordinator durably exports active parent before child capture finishes");
    expect(group().phase).toBe("preparing");
    expect(group().parent.handoff.wasActive).toBe(true);
    expect(pauseReplied).toBe(false);
    const releasedWaits = toolResults(parentFile, "wait_agent");
    expect(releasedWaits).toHaveLength(1);
    expect(JSON.parse(text(releasedWaits[0].message.content)).paused).toBe(true);
    // The later call was already admitted in the same assistant tool batch. Its
    // tool_call hook must register the drain token after pause releases the wait.
    const drainedSend = toolResults(parentFile, laterTool);
    expect(drainedSend).toHaveLength(1);
    expect(drainedSend[0].message.isError).not.toBe(true);
    expect(drainedSend[0].message.details.delivery).toBe("steer");
    if (nested) {
      expect(toolResults(parentFile, "send_message")).toHaveLength(0); // Nested results are not transcript entries.
      expect(drainedSend[0].message.nestedCalls.calls).toHaveLength(1);
      expect(drainedSend[0].message.nestedCalls.calls[0]).toMatchObject({
        name: "send_message", status: "ok", arguments: { target: "native-child", message: lateSteering },
      });
      expect(rpc.records.filter(record => record.type === "tool_execution_end" && record.toolName === "send_message"
        && record.parentToolCallId === drainedSend[0].message.toolCallId)).toHaveLength(1);
    }
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(0);
    await until(() => existsSync(files.pauseRequested), "held child observes the coordinator's actual native pause fence");
    expect(readFileSync(files.pauseRequested, "utf8")).toMatch(/^(pausing|paused)$/);
    writeFileSync(files.release, "release actual child tool");
    expect((await pause).disposition).toBe("handled");
    const saved = group();
    expect(saved.phase, JSON.stringify(saved)).toBe("saved");
    // Closing stdin is the documented RPC shutdown path. /pause --exit currently
    // sets shutdownRequested after RPC's async handled-prompt shutdown check.
    expect(await rpc.close()).toBe(0);
    expect(saved.parentId).toBe(parentId);
    expect(saved.parent.handoff.sessionFile).toBe(parentFile);
    expect(Object.keys(saved.children)).toEqual([childId]);
    expect(saved.children[childId].handoff.sessionFile).toBe(childFile);
    expect(saved.children[childId].handoff.wasActive).toBe(true);
    expect(saved.children[childId].handoff.pending.steering.map((message: any) => text(message.content))).toEqual([lateSteering]);
    expect(saved.children[childId].items.filter((item: any) => item.lane === "steering")).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(0);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(toolResults(childFile, "faux_hold")).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(freshMarkers(parentFile)).toHaveLength(0);
    expect(freshMarkers(childFile)).toHaveLength(0);

    // No fixture hold flag: production discovery of saved group must fence parent startup.
    rpc = sourceRpc(cwd, parentFile, false, parentExtensions);
    const reopened = await rpc.request({ type: "get_state" });
    expect(reopened.sessionId).toBe(parentId);
    expect(reopened.sessionFile).toBe(parentFile);
    expect(reopened.pauseState).toBe("paused");
    expect(group().phase).toBe("saved");
    expect(getAgent("native-child", parentId)!.id).toBe(childId);
    expect(getAgent("native-child", parentId)!.sessionFile).toBe(childFile);
    expect(getAgent("native-child", parentId)!.childProcess).toBeUndefined();
    await delay(50);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(jsonl(templateStartsFile(childFile))).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(0);

    expect((await rpc.request({ type: "prompt", message: "/unpause" })).disposition).toBe("handled");
    await until(() => group().phase === "consumed", "production coordinator consumes the saved generation");
    await until(() => completions(parentFile).length === 1 && getAgent("native-child", parentId)!.status === "completed",
      "one real child completion is delivered into parent history");
    await until(async () => !(await rpc.request({ type: "get_state" })).isStreaming, "parent settles after completion delivery");
    const consumed = group();
    expect(consumed.parentResumed).toBe(true);
    expect(consumed.resumed).toEqual([childId]);
    expect(consumed.completions.mailbox).toHaveLength(1);
    const completionId = consumed.completions.mailbox[0].id;
    expect(consumed.completions.delivered).toEqual([completionId]);
    expect(completions(parentFile)[0].details.completionId).toBe(completionId);
    expect(completions(parentFile)[0].details.agent_name).toBe("/native-child");
    expect(getAgent("native-child", parentId)!.id).toBe(childId);
    expect(getAgent("native-child", parentId)!.sessionFile).toBe(childFile);
    expect(SessionManager.open(childFile).getSessionId()).toBe(saved.children[childId].handoff.sessionId);
    expect(freshMarkers(parentFile)).toHaveLength(1);
    expect(freshMarkers(childFile)).toHaveLength(1);
    expect(toolResults(parentFile, "spawn_agent")).toHaveLength(1);
    expect(toolResults(parentFile, "wait_agent")).toHaveLength(1);
    expect(toolResults(parentFile, laterTool)).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(1);
    expect(toolResults(childFile, "faux_hold")).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(2);
    const childStarts = jsonl(templateStartsFile(childFile));
    expect(childStarts).toHaveLength(2);
    expect(childStarts[1].pause).toBe("paused");
    expect(childStarts[1].pid).not.toBe(childStarts[0].pid);

    // An already consumed generation is revoked, even if /unpause is requested again.
    const parentCalls = jsonl(providerCallsFile(parentFile)).length;
    await rpc.request({ type: "prompt", message: "/unpause" });
    await delay(50);
    expect(freshMarkers(parentFile)).toHaveLength(1);
    expect(freshMarkers(childFile)).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(1);
    expect(toolResults(parentFile, laterTool)).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(parentCalls);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(2);
    expect(jsonl(files.effects)).toHaveLength(1);
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);
