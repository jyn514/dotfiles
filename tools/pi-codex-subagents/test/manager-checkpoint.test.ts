import { expect, test, spyOn } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { childHelper, jsonl, productionIndex, sourceRpc, until } from "./source-runtime.ts";
import { CHECKPOINT_NOTIFY, CHECKPOINT_RESTORE_COMMAND, checkpointRestoreResult } from "../checkpoint.ts";
import type { PeerControl } from "./checkpoint-peer-extension.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const prompt = 'invoke-tool:{"name":"checkpoint_peer","args":{}}';
const peer = new URL("./checkpoint-peer-extension.ts", import.meta.url).pathname;
async function harness() {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "checkpoint-"));
  const parentId = randomUUID();
  const template = `checkpoint-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${peer}\n---\n`);
  let manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  await manager.ready();
  const control = (value: PeerControl) => writeFileSync(join(cwd, "checkpoint-control.json"), JSON.stringify(value));
  const observations = () => jsonl(join(cwd, "checkpoint-observations.jsonl"));
  const info = () => manager.getAgentInfo("worker", parentId);
  const settled = async () => {
    await until(() => ["completed", "failed", "interrupted"].includes(info().status) && !info().childProcess, "native settlement and process exit");
    return structuredClone(info());
  };
  const spawn = async (value: PeerControl) => {
    control(value);
    await manager.spawnAgent({ task_name: "worker", message: prompt, agent_type: template, cwd, parentSessionId: parentId,
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    return settled();
  };
  const run = async (value: PeerControl) => {
    control(value);
    await manager.sendMessage(parentId, "worker", prompt);
    return settled();
  };
  return { cwd, parentId, template, templateFile, manager: () => manager, control, observations, info, settled, spawn, run,
    async recreate() { await manager.shutdown(); manager = new AgentManager({ modelResponseTimeoutMs: 10000 }); await manager.ready(); },
    async close() { await manager.shutdown(); rmSync(templateFile, { force: true }); rmSync(cwd, { recursive: true, force: true }); },
  };
}

sourceTest("checkpoint survives real same-worker/new-PID hibernation; no-write preserves, replacement and retirement do not resurrect", async () => {
  const h = await harness();
  try {
    const first = await h.spawn({ action: "write", value: "checkpoint-secret-one", lateExport: true });
    expect(h.observations()[0].checkpoint).toBeNull();
    const second = await h.run({});
    const beforeSecondEdit = h.observations()[1];
    expect(beforeSecondEdit.checkpoint).toEqual({ repository: join(h.cwd, "repository"), commit: "checkpoint-secret-one", parent: "fixture-parent-secret" });
    expect(beforeSecondEdit.pid).not.toBe(h.observations()[0].pid);
    expect(second.id).toBe(first.id);
    expect(second.sessionFile).toBe(first.sessionFile);
    expect(beforeSecondEdit.sessionId).toBe(h.observations()[0].sessionId);
    await h.run({ action: "write", value: "checkpoint-secret-two" });
    expect(h.observations()[2].checkpoint.commit).toBe("checkpoint-secret-one");
    await h.run({ action: "retire", lateExport: true });
    expect(h.observations()[3].checkpoint.commit).toBe("checkpoint-secret-two");
    await h.run({});
    expect(h.observations()[4].checkpoint).toBeNull();
    await h.run({});
    expect(h.observations()[5].checkpoint).toBeNull();
    // Payload may appear only in the fixture's owned evidence, never production persistence.
    for (const file of [first.sessionFile, first.infoFile, first.logFile, join(first.infoFile, "..", "group.json")]) {
      if (!existsSync(file)) continue;
      const text = readFileSync(file, "utf8");
      for (const secret of ["checkpoint-secret-one", "checkpoint-secret-two", "fixture-parent-secret", "late-old-process-secret"]) {
        expect(text).not.toContain(secret);
      }
    }
  } finally { await h.close(); }
}, 30000);

sourceTest("missing, malformed, failed restore, crash and interrupt consume checkpoint authority without retries", async () => {
  const h = await harness();
  const errors = spyOn(console, "error").mockImplementation(() => {});
  try {
    await h.spawn({ action: "write", value: "checkpoint-secret-original" });
    for (const action of ["missing", "malformed"] as const) {
      await h.run({ action });
      expect(h.observations().at(-1).checkpoint).not.toBeNull();
      await h.run({});
      expect(h.observations().at(-1).checkpoint).toBeNull();
      await h.run({ action: "write", value: `checkpoint-secret-${action}` });
    }
    await h.run({ failRestore: true });
    expect(h.observations().at(-1).checkpoint).toBeNull();
    expect(errors.mock.calls.filter(call => String(call[0]).includes("checkpoint unavailable"))).toHaveLength(1);
    await h.run({});
    expect(h.observations().at(-1).checkpoint).toBeNull();
    expect(errors.mock.calls.filter(call => String(call[0]).includes("checkpoint unavailable"))).toHaveLength(1);
    await h.run({ action: "write", value: "checkpoint-secret-before-startup-failure" });
    h.control({ startupCrash: true });
    await expect(h.manager().sendMessage(h.parentId, "worker", prompt)).rejects.toThrow();
    await h.settled();
    await h.run({});
    expect(h.observations().at(-1).checkpoint).toBeNull();
    await h.run({ action: "write", value: "checkpoint-secret-before-restore-crash" });
    h.control({ restoreCrash: true });
    await expect(h.manager().sendMessage(h.parentId, "worker", prompt)).rejects.toThrow();
    await h.settled();
    await h.run({});
    expect(h.observations().at(-1).checkpoint).toBeNull();
    await h.run({ action: "write", value: "checkpoint-secret-before-crash" });
    await h.run({ action: "crash" });
    expect(h.info().status).toBe("failed");
    await h.run({});
    expect(h.observations().at(-1).checkpoint).toBeNull();
    await h.run({ action: "write", value: "checkpoint-secret-before-interrupt" });
    h.control({ action: "hold" });
    await h.manager().sendMessage(h.parentId, "worker", prompt);
    await until(() => existsSync(join(h.cwd, "checkpoint-held")), "native tool running before interruption");
    expect(h.observations().at(-1).checkpoint.commit).toBe("checkpoint-secret-before-interrupt");
    await h.manager().interruptAgent(h.parentId, "worker");
    await h.settled();
    await h.run({});
    expect(h.observations().at(-1).checkpoint).toBeNull();
  } finally { errors.mockRestore(); await h.close(); }
}, 45000);

sourceTest("checkpoints stay isolated across workers/parent sessions and disappear on manager recreation with same transcripts", async () => {
  const h = await harness();
  const foreignCwd = join(h.cwd, "foreign");
  const siblingCwd = join(h.cwd, "sibling");
  mkdirSync(foreignCwd); mkdirSync(siblingCwd);
  try {
    const first = await h.spawn({ action: "write", value: "checkpoint-secret-owned" });
    for (const [cwd, owner, name] of [[foreignCwd, randomUUID(), "worker"], [siblingCwd, h.parentId, "sibling"]]) {
      writeFileSync(join(cwd, "checkpoint-control.json"), JSON.stringify({ action: "write", value: "checkpoint-secret-other" }));
      await h.manager().spawnAgent({ task_name: name, message: prompt, agent_type: h.template, cwd, parentSessionId: owner,
        inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => !h.manager().getAgentInfo(name, owner).childProcess && h.manager().getAgentInfo(name, owner).status === "completed", "isolated worker exits");
      expect(jsonl(join(cwd, "checkpoint-observations.jsonl"))[0].checkpoint).toBeNull();
    }
    await h.run({});
    expect(h.observations().at(-1).checkpoint.commit).toBe("checkpoint-secret-owned");
    await h.recreate();
    await h.run({});
    expect(h.info().id).toBe(first.id);
    expect(h.info().sessionFile).toBe(first.sessionFile);
    expect(h.observations().at(-1).checkpoint).toBeNull();
  } finally { await h.close(); }
}, 25000);

sourceTest("ordinary controllerless workers remain quiet during initial launch and recreation", async () => {
  const { AgentManager } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "ordinary-"));
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  const parentSessionId = randomUUID();
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "ordinary", message: "ordinary task", cwd, parentSessionId,
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => manager.getAgentInfo("ordinary", parentSessionId).status === "completed" && !manager.getAgentInfo("ordinary", parentSessionId).childProcess, "ordinary initial completion");
    await manager.sendMessage(parentSessionId, "ordinary", "ordinary followup");
    await until(() => manager.getAgentInfo("ordinary", parentSessionId).status === "completed" && !manager.getAgentInfo("ordinary", parentSessionId).childProcess, "ordinary followup completion");
    const info = manager.getAgentInfo("ordinary", parentSessionId);
    expect(info.error).toBeUndefined();
    expect(readFileSync(info.logFile, "utf8")).not.toContain("checkpoint");
    expect(jsonl(info.sessionFile).filter(entry => entry.type === "custom" && entry.customType?.includes("checkpoint"))).toEqual([]);
  } finally { await manager.shutdown(); rmSync(cwd, { recursive: true, force: true }); }
}, 15000);

sourceTest("checkpoint restoration applies after startup reset and before held-child release with controller loaded first", async () => {
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "checkpoint-first-"));
  const sessionFile = join(cwd, "session.jsonl");
  writeFileSync(join(cwd, "checkpoint-control.json"), "{}");
  const rpc = sourceRpc(cwd, sessionFile, true, [peer, childHelper]);
  try {
    const state = await rpc.request({ type: "get_state" });
    expect(state.pauseState).toBe("paused");
    const checkpoint = { repository: join(cwd, "repository"), commit: "startup-order-secret", parent: "order-parent-secret" };
    const result = await rpc.request({ type: "prompt", message: `/${CHECKPOINT_RESTORE_COMMAND} ${JSON.stringify({ version: 1, checkpoint })}` });
    expect(result.disposition).toBe("handled");
    expect(rpc.records.some(record => record.type === "extension_ui_request" && record.method === "notify"
      && record.message.startsWith(CHECKPOINT_NOTIFY)
      && checkpointRestoreResult(JSON.parse(record.message.slice(CHECKPOINT_NOTIFY.length)))?.restored === true)).toBe(true);
    expect(rpc.records.filter(record => record.type === "extension_error")).toEqual([]);
    await expect(rpc.request({ type: "prompt", message: prompt })).rejects.toThrow(/paused/i);
    expect(jsonl(join(cwd, "checkpoint-observations.jsonl"))).toEqual([]);
    await rpc.request({ type: "resume" });
    await rpc.request({ type: "prompt", message: prompt });
    await until(() => rpc.records.some(record => record.type === "agent_settled"), "held child's first native settlement");
    expect(jsonl(join(cwd, "checkpoint-observations.jsonl"))[0].checkpoint).toEqual(checkpoint);
    expect(readFileSync(sessionFile, "utf8")).not.toContain("startup-order-secret");
  } finally { await rpc.close(); rmSync(cwd, { recursive: true, force: true }); }
}, 15000);

sourceTest("production pause records never persist the live boundary checkpoint", async () => {
  const { SUBAGENT_DIR, getAgent, getRunsDir, parentScopeKey } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "checkpoint-group-"));
  const template = `checkpoint-group-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${peer}\n---\n`);
  const parentFile = join(cwd, "parent.jsonl");
  const controlFile = join(cwd, "checkpoint-control.json");
  writeFileSync(controlFile, JSON.stringify({ action: "write", value: "group-checkpoint-secret" }));
  const rpc = sourceRpc(cwd, parentFile, false, [productionIndex]);
  let pause: Promise<any> | undefined;
  try {
    const parentId = (await rpc.request({ type: "get_state" })).sessionId;
    const invoke = (name: string, args: unknown) => rpc.request({ type: "prompt", message: `invoke-tool:${JSON.stringify({ name, args })}` });
    await invoke("spawn_agent", { task_name: "worker", agent_type: template, cwd, message: prompt });
    await until(() => getAgent("worker", parentId)?.status === "completed" && !getAgent("worker", parentId)?.childProcess, "production worker hibernates with checkpoint");
    const worker = structuredClone(getAgent("worker", parentId)!);
    writeFileSync(controlFile, JSON.stringify({ action: "hold" }));
    await until(() => rpc.records.filter(record => record.type === "agent_settled").length > 0, "parent spawn tool settled");
    await invoke("send_message", { target: "worker", message: prompt });
    await until(() => existsSync(join(cwd, "checkpoint-held")), "production worker restored and running a tool before pause");
    expect(jsonl(join(cwd, "checkpoint-observations.jsonl")).at(-1).checkpoint.commit).toBe("group-checkpoint-secret");
    pause = rpc.request({ type: "prompt", message: "/pause" });
    void pause.catch(() => {});
    const groupFile = join(getRunsDir(), parentScopeKey(parentId), "group.json");
    await until(() => existsSync(groupFile), "production pause begins durable group record");
    writeFileSync(join(cwd, "checkpoint-release"), "release only owned fixture tool");
    expect((await pause).disposition).toBe("handled");
    expect(JSON.parse(readFileSync(groupFile, "utf8")).phase).toBe("saved");
    for (const file of [groupFile, parentFile, worker.sessionFile, worker.infoFile, worker.logFile]) {
      expect(readFileSync(file, "utf8")).not.toContain("group-checkpoint-secret");
      expect(readFileSync(file, "utf8")).not.toContain("fixture-parent-secret");
    }
  } finally {
    writeFileSync(join(cwd, "checkpoint-release"), "cleanup releases fixture tool");
    await rpc.close(); await pause?.catch(() => {});
    rmSync(templateFile, { force: true }); rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);

sourceTest("missing/malformed restore results and helper errors cannot authorize a prompt or resurrect a checkpoint", async () => {
  const h = await harness();
  const old = process.env.PI_TEST_CHECKPOINT_FILTER;
  const transport = join(h.cwd, "checkpoint-transport.json");
  const filtered = join(h.cwd, "checkpoint-result-filtered");
  try {
    await h.spawn({ action: "write", value: "receipt-secret-initial" });
    for (const mode of ["missing", "malformed", "error"]) {
      const before = h.observations().length;
      writeFileSync(transport, JSON.stringify({ result: mode }));
      process.env.PI_TEST_CHECKPOINT_FILTER = "1";
      h.control({});
      await expect(h.manager().sendMessage(h.parentId, "worker", prompt)).rejects.toThrow(/restoration result missing or malformed/);
      await h.settled();
      expect(readFileSync(filtered, "utf8")).toBe(mode);
      expect(h.observations()).toHaveLength(before);
      expect(h.info().status).toBe("failed");
      delete process.env.PI_TEST_CHECKPOINT_FILTER;
      rmSync(transport); rmSync(filtered);
      await h.run({});
      expect(h.observations().at(-1).checkpoint).toBeNull();
      await h.run({ action: "write", value: `receipt-secret-${mode}` });
    }
  } finally {
    if (old === undefined) delete process.env.PI_TEST_CHECKPOINT_FILTER; else process.env.PI_TEST_CHECKPOINT_FILTER = old;
    await h.close();
  }
}, 25000);
