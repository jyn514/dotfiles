import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { SavedSession } from "../handoff.ts";
import { CONTINUATION_MESSAGE } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);

sourceTest("Manager launches its actual helper/template subprocess and waits for a real held tool", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-held-"));
  const parentId = randomUUID();
  const template = `source-held-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "tool");
  const files = heldToolFiles(marker);
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "real-held", message: `hold-tool:${marker}`, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(files.started), "Manager's actual subprocess enters the tool");
    const original = structuredClone(manager.getAgentInfo("real-held", parentId));
    expect(original.status).toBe("running");
    expect(original.childProcess?.pid).toBe(JSON.parse(readFileSync(files.started, "utf8")).pid);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(0);
    const completed = manager.waitAgent(parentId, ["real-held"]);
    writeFileSync(files.release, "release");
    const result = await completed;
    expect(result.event?.status).toBe("completed");
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(2);
    const final = manager.getAgentInfo("real-held", parentId);
    expect(final.id).toBe(original.id);
    expect(final.sessionFile).toBe(original.sessionFile);
    expect(final.finalResponse).toContain("faux:hold-tool:");
    await until(() => !manager.getAgentInfo("real-held", parentId).childProcess, "completed subprocess hibernates");
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 15000);

sourceTest("Manager drains admitted submissions, releases waits neutrally, captures held tools, and resumes preserved children once", async () => {
  // Dynamic import avoids initializing real Manager storage during ordinary opt-out discovery.
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-suspension-"));
  const parentId = randomUUID();
  const template = `source-held-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${heldExtension}\n---\n`);
  const completions: any[] = [];
  const options = { onUnclaimedCompletion: (event: any) => completions.push(event), modelResponseTimeoutMs: 10000 };
  let manager = new AgentManager(options);
  const markerA = join(cwd, "first");
  const markerB = join(cwd, "accepted-batch");
  const filesA = heldToolFiles(markerA);
  const filesB = heldToolFiles(markerB);
  const spawn = (task: string, marker: string, extra = {}) => manager.spawnAgent({
    task_name: task, message: `hold-tool:${marker}`, agent_type: template,
    cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1",
    inheritedThinking: "off", ...extra,
  });
  try {
    // This names a missing production contract explicitly, rather than masking it with mocks.
    for (const method of ["beginPause", "allowDrainingToolCall", "pauseChildren", "drainSubmissions", "captureChildren", "prepareChildren",
      "resumeChild", "endPause", "getCompletionState", "restoreCompletionState", "markCompletionDelivered"]) {
      expect(typeof (manager as any)[method], `Manager.${method} is required`).toBe("function");
    }
    await manager.ready();
    await spawn("first", markerA);
    await until(() => existsSync(filesA.started), "first real tool is held");
    const first = structuredClone(manager.getAgentInfo("first", parentId));
    let waiterReleased = false;
    let allReleased = false;
    const waiter = manager.waitAgent(parentId, ["first"]).then(value => { waiterReleased = true; return value; });
    const all = manager.waitAllAgents(parentId, ["first"]).then(value => { allReleased = true; return value; });
    expect(waiterReleased).toBe(false);
    expect(allReleased).toBe(false);

    manager.beginPause(parentId);
    await manager.pauseChildren(parentId);
    await until(() => existsSync(filesA.pauseRequested), "existing child is fenced before parent submissions drain");
    await until(() => waiterReleased && allReleased, "both parent wait lanes released by pause");
    const waitResult = await waiter;
    const allResult = await all;
    expect(waitResult.event).toBeUndefined();
    expect(waitResult.message).toMatch(/paus|suspend/i);
    expect(allResult.responses).toEqual([]);
    expect(allResult.message).toMatch(/paus|suspend/i);
    expect(["completed", "failed", "interrupted"]).not.toContain(manager.getAgentInfo("first", parentId).status);
    expect(completions).toHaveLength(0);

    await expect(spawn("not-admitted", join(cwd, "not-admitted"))).rejects.toThrow(/paus|suspend|admi/i);
    const admittedToolCallId = `accepted-parent-tool-${randomUUID()}`;
    manager.allowDrainingToolCall(parentId, admittedToolCallId);
    await spawn("accepted-batch", markerB, { admittedToolCallId });
    await manager.drainSubmissions(parentId);
    await until(() => existsSync(filesB.started), "already accepted parent tool batch reaches child");
    const second = structuredClone(manager.getAgentInfo("accepted-batch", parentId));
    expect(existsSync(filesA.ended)).toBe(false);
    expect(existsSync(filesB.ended)).toBe(false);

    const captures: Record<string, SavedSession> = {};
    const progress: string[] = [];
    let captureDone = false;
    const generation = randomUUID();
    const capture = manager.captureChildren(parentId, generation, (id: string, saved: SavedSession) => {
      const info = [first, second].find(info => info.id === id)!;
      const ownership = manager.getAgentInfo(info.canonicalName, parentId).childProcess;
      expect(ownership?.pid).toBeNumber();
      process.kill(ownership!.pid, 0); // Persistence owner receives capture before child closure.
      captures[id] = structuredClone(saved);
      // This callback is the owning persistence handoff, before Manager may close a child.
      writeFileSync(join(cwd, `${id}.saved.json`), JSON.stringify(saved));
    }, activity => { progress.push(activity); }).then(value => { captureDone = true; return value; });
    await until(() => existsSync(filesA.pauseRequested) && existsSync(filesB.pauseRequested), "both held children observe native capture fences");
    expect(captureDone).toBe(false);
    expect(Object.keys(captures)).toHaveLength(0);
    expect(jsonl(providerCallsFile(first.sessionFile))).toHaveLength(1);
    expect(jsonl(providerCallsFile(second.sessionFile))).toHaveLength(1);
    writeFileSync(filesA.release, "release first");
    // Holding the other tool must still prevent whole-group capture from completing.
    await until(() => existsSync(filesA.ended), "first held tool really ended");
    expect(captureDone).toBe(false);
    writeFileSync(filesB.release, "release second");
    const returned = await capture;
    expect(Object.keys(captures).sort()).toEqual([first.id, second.id].sort());
    expect(Object.keys(returned).sort()).toEqual(Object.keys(captures).sort());
    for (const info of [first, second]) {
      const capturing = progress.indexOf(`capturing child ${info.canonicalName}`);
      const closing = progress.indexOf(`closing child ${info.canonicalName}`);
      expect(capturing).toBeGreaterThanOrEqual(0);
      expect(closing).toBeGreaterThan(capturing);
    }
    await until(() => [first, second].every(info => !manager.getAgentInfo(info.canonicalName, parentId).childProcess), "captured children close after owner persistence");
    for (const info of [first, second]) {
      const saved = captures[info.id];
      expect(saved.handoff.sessionFile).toBe(info.sessionFile);
      expect(saved.handoff.wasActive,
        `${info.canonicalName}: expected active held capture; providerCalls=${JSON.stringify(jsonl(providerCallsFile(info.sessionFile)))}`).toBe(true);
      expect(jsonl(info.sessionFile).find(entry => entry.type === "session")?.id).toBe(saved.handoff.sessionId);
      expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(1);
      expect(jsonl(info.sessionFile).filter(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "faux_hold")).toHaveLength(1);
      expect(manager.getAgentInfo(info.canonicalName, parentId).id).toBe(info.id);
      expect(manager.getAgentInfo(info.canonicalName, parentId).sessionFile).toBe(info.sessionFile);
      expect(["completed", "failed", "interrupted"]).not.toContain(manager.getAgentInfo(info.canonicalName, parentId).status);
    }
    expect(completions).toHaveLength(0);
    const completionState = structuredClone(manager.getCompletionState(parentId));
    expect(completionState.mailbox).toEqual([]);

    await manager.shutdown();
    manager = new AgentManager(options);
    await manager.ready();
    manager.beginPause(parentId);
    manager.restoreCompletionState(parentId, completionState);
    // Read snapshots back from the durable owner instead of relying on original object identity.
    const restored: Record<string, SavedSession> = Object.fromEntries(Object.keys(captures).map(id => [id,
      JSON.parse(readFileSync(join(cwd, `${id}.saved.json`), "utf8"))]));
    await manager.prepareChildren(parentId, restored);
    for (const info of [first, second]) {
      const current = manager.getAgentInfo(info.canonicalName, parentId);
      expect(current.id).toBe(info.id);
      expect(current.sessionFile).toBe(info.sessionFile);
      const starts = jsonl(templateStartsFile(info.sessionFile));
      expect(starts).toHaveLength(2);
      expect(starts[1].pause).toBe("paused"); // Helper's first startup handler fenced template work.
      expect(starts[1].pid).not.toBe(starts[0].pid);
      expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(1);
    }
    await delay(50);
    expect(jsonl(filesA.effects)).toHaveLength(1);
    expect(jsonl(filesB.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(first.sessionFile))).toHaveLength(1);
    expect(jsonl(providerCallsFile(second.sessionFile))).toHaveLength(1);

    for (const info of [first, second]) {
      const result = await manager.resumeChild(parentId, info.id, restored[info.id], (saved: SavedSession) => {
        restored[info.id] = structuredClone(saved);
        writeFileSync(join(cwd, `${info.id}.saved.json`), JSON.stringify(saved));
      });
      expect(result.complete).toBe(true);
    }
    await until(() => [first, second].every(info => manager.getAgentInfo(info.canonicalName, parentId).status === "completed"), "both resumed children settle");
    for (const [info, files] of [[first, filesA], [second, filesB]] as const) {
      expect(jsonl(files.effects)).toHaveLength(1);
      const calls = jsonl(providerCallsFile(info.sessionFile));
      expect(calls).toHaveLength(2);
      expect(calls.filter(call => call.text === CONTINUATION_MESSAGE)).toHaveLength(1);
      const records = jsonl(info.sessionFile);
      expect(records.filter(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "faux_hold")).toHaveLength(1);
    }
    // Completion ownership survives a restore without inventing new event IDs.
    const pending = structuredClone(manager.getCompletionState(parentId));
    expect(pending.mailbox).toHaveLength(2);
    expect(new Set(pending.mailbox.map(event => event.id)).size).toBe(2);
    manager.restoreCompletionState(parentId, pending);
    expect(manager.getCompletionState(parentId)).toEqual(pending);
    const event = pending.mailbox[0];
    manager.markCompletionDelivered(event.id);
    manager.markCompletionDelivered(event.id);
    const delivered = structuredClone(manager.getCompletionState(parentId));
    expect(delivered.delivered.filter(id => id === event.id)).toHaveLength(1);
    manager.restoreCompletionState(parentId, delivered);
    expect(manager.getCompletionState(parentId)).toEqual(delivered);
    manager.endPause(parentId);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);
