import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { jsonl, heldExtension, sourceRpc, productionIndex, until } from "./source-runtime.ts";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const fixture = join(import.meta.dir, "extension-channel-fixture.ts");
sourceTest("named channels round-trip real RPC with authoritative identity, nested requests, input admission and completed-worker reopening", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "extension-rpc-"));
  const parentId = randomUUID();
  const template = `channel-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}, ${fixture}\n---\n`);
  const events: any[] = [];
  const completions: any[] = [];
  const manager = new AgentManager({ onExtensionRequest: async event => {
    events.push(event);
    return { ok: true, value: { payload: event.payload, origin: event.origin } };
  }, onUnclaimedCompletion: event => completions.push(event) });
  const spawn = async (name: string, message = "hello-channel") => {
    await manager.spawnAgent({ task_name: name, message, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    return manager.getAgentInfo(name, parentId);
  };
  try {
    await manager.ready();
    const info = await spawn("completed");
    await until(() => manager.getAgentInfo("completed", parentId).status === "completed", "initial completion");
    const original = manager.getAgentInfo("completed", parentId);
    const calls = jsonl(providerCallsFile(info.sessionFile)).length;
    const payload = { text: "quote \"\nUnicode: 𐐀\u2028", nested: [null, true, { x: 1 }] };
    expect(await manager.requestExtension(parentId, info.id, "fixture:echo", payload)).toEqual(payload);
    expect(manager.getAgentInfo("completed", parentId).status).toBe("completed");
    expect(manager.getAgentInfo("completed", parentId).finalResponse).toBe(original.finalResponse);
    expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(calls);
    expect(completions.filter(e => e.agentName === info.canonicalName)).toHaveLength(1);

    const nested = await manager.requestExtension(parentId, info.id, "fixture:nested", { workerId: "spoofed", taskName: "fake" });
    expect(nested).toEqual({ payload: { workerId: "spoofed", taskName: "fake" }, origin: {
      workerId: info.id, taskName: info.taskName, sessionId: info.sessionId,
    } });
    expect(events).toHaveLength(1);
    expect(events[0].ownerSessionId).toBe(parentId);
    await expect(manager.requestExtension(parentId, info.id, "missing", null)).rejects.toMatchObject({ code: "unavailable" });
    await expect(manager.requestExtension(parentId, info.id, "fixture:throw", null)).rejects.toMatchObject({ code: "handler_error", message: "fixture handler failure" });
    await expect(manager.requestExtension(randomUUID(), info.id, "fixture:echo", null)).rejects.toMatchObject({ code: "unavailable" });

    expect(await manager.requestExtension(parentId, info.id, "fixture:input", "actual-user-channel-answer")).toEqual({ admitted: true });
    await until(() => jsonl(providerCallsFile(info.sessionFile)).length === calls + 1, "actual user input invokes child model");
    await until(() => manager.getAgentInfo("completed", parentId).status === "completed", "answer run completes");
    expect(jsonl(info.sessionFile).filter(e => e.type === "message" && e.message?.role === "user").at(-1)?.message.content).toEqual([{ type: "text", text: "actual-user-channel-answer" }]);
    expect(jsonl(info.sessionFile).some(e => e.message?.customType === "subagent-link")).toBe(false);
    expect(jsonl(providerCallsFile(info.sessionFile)).at(-1)?.text).toBe("actual-user-channel-answer");

    const raced = await spawn("raced", "hold-tool:" + join(cwd, "raced"));
    await until(() => existsSync(heldToolFiles(join(cwd, "raced")).started), "race original tool active");
    const entered = join(cwd, "handler-entered");
    const release = join(cwd, "handler-release");
    const request = manager.requestExtension(parentId, raced.id, "fixture:deferred-input", { entered, release, message: "race-user-input" });
    await until(() => existsSync(entered), "handler is in flight before original settles");
    writeFileSync(heldToolFiles(join(cwd, "raced")).release, "release original tool");
    await until(() => manager.getAgentInfo("raced", parentId).status === "completed", "original completes while handler is in flight");
    expect(manager.getAgentInfo("raced", parentId).childProcess?.pid).toBeTruthy();
    writeFileSync(release, "release handler");
    expect(await request).toEqual({ admitted: true });
    await until(() => jsonl(providerCallsFile(raced.sessionFile)).at(-1)?.text === "race-user-input", "racing answer starts actual child run");
    await until(() => manager.getAgentInfo("raced", parentId).status === "completed" && manager.getAgentInfo("raced", parentId).finalResponse?.includes("race-user-input"), "manager tracks raced second completion");

    const interrupted = await spawn("interrupted", "hold-tool:" + join(cwd, "interrupted"));
    await until(() => existsSync(heldToolFiles(join(cwd, "interrupted")).started), "held worker started");
    await manager.interruptAgent(parentId, "interrupted");
    await expect(manager.requestExtension(parentId, interrupted.id, "fixture:echo", null)).rejects.toMatchObject({ code: "inactive" });
    manager.beginPause(parentId);
    await expect(manager.requestExtension(parentId, info.id, "fixture:echo", null)).rejects.toThrow();
    manager.endPause(parentId);
    const failed = await spawn("failed", "peer-provider-failure");
    await until(() => manager.getAgentInfo("failed", parentId).status === "failed", "provider failure");
    await expect(manager.requestExtension(parentId, failed.id, "fixture:echo", null)).rejects.toMatchObject({ code: "inactive" });

    const exited = await spawn("exited");
    await until(() => manager.getAgentInfo("exited", parentId).status === "completed", "worker completes before exit-handler request");
    await expect(manager.requestExtension(parentId, exited.id, "fixture:exit", null)).rejects.toMatchObject({ code: "closed" });
    const timed = await spawn("timed");
    await until(() => manager.getAgentInfo("timed", parentId).status === "completed", "worker completes before unresponsive handler");
    const callsBeforeTimeout = jsonl(providerCallsFile(timed.sessionFile)).length;
    const started = Date.now();
    await expect(manager.requestExtension(parentId, timed.id, "fixture:pending", null)).rejects.toMatchObject({ code: "timeout" });
    expect(Date.now() - started).toBeLessThan(8000);
    expect(manager.getAgentInfo("timed", parentId).status).toBe("completed");
    expect(jsonl(providerCallsFile(timed.sessionFile))).toHaveLength(callsBeforeTimeout);
    expect(manager.getAgentInfo("timed", parentId).childProcess).toBeUndefined();
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true }); rmSync(cwd, { recursive: true, force: true });
  }
}, 40000);

sourceTest("parent endpoint discovery and handler registration reach the real child through the production manager extension", async () => {
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "extension-parent-"));
  const template = `channel-parent-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${fixture}\n---\n`);
  const root = sourceRpc(cwd, join(cwd, "root.jsonl"), false, [fixture, productionIndex]);
  try {
    await root.request({ type: "get_state" });
    await root.request({ type: "prompt", message: `invoke-tool:${JSON.stringify({ name: "spawn_agent", args: { task_name: "child", message: `invoke-tool:${JSON.stringify({ name: "fixture_request", args: { channel: "fixture:parent", payload: { x: "child-to-parent" } } })}`, agent_type: template } })}` });
    const { readdirSync } = await import("node:fs");
    let info: any;
    await until(() => {
      const paths = readdirSync(getRunsDir(), { recursive: true }) as string[];
      info = paths.filter(p => p.endsWith(".info.json")).map(p => JSON.parse(readFileSync(join(getRunsDir(), p), "utf8"))).find(p => p.taskName === "child");
      return info?.status === "completed";
    }, "worker completes native request tool");
    const toolResult = jsonl(info.sessionFile).find(e => e.message?.toolName === "fixture_request" && e.message?.role === "toolResult");
    expect(toolResult.message.details).toEqual({ payload: { x: "child-to-parent" }, origin: { workerId: info.id, taskName: "child", sessionId: info.sessionId } });
    await until(async () => !(await root.request({ type: "get_state" })).isStreaming, "parent model is idle");
    const before = jsonl(providerCallsFile(join(cwd, "root.jsonl"))).length;
    await root.request({ type: "prompt", message: `/fixture-parent-request ${JSON.stringify({ workerId: info.id, channel: "fixture:nested", payload: [1, "nested command"] })}` });
    const entries = (await root.request({ type: "get_entries" })).entries;
    expect(entries.findLast((e: any) => e.customType === "fixture-parent-result")?.data).toEqual({ ok: true, result: { payload: [1, "nested command"], origin: { workerId: info.id, taskName: "child", sessionId: info.sessionId } } });
    expect(jsonl(providerCallsFile(join(cwd, "root.jsonl")))).toHaveLength(before);
  } finally {
    await root.close(); rmSync(templateFile, { force: true }); rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);
