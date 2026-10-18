import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { CONTINUATION_MESSAGE, type SavedSession } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("single-child Manager capture/reopen/resume preserves identity and executes the tool effect once", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-single-"));
  const parentId = randomUUID();
  const template = `source-held-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "tool");
  const files = heldToolFiles(marker);
  const ownedSnapshot = join(cwd, "saved.json");
  let manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "single", message: `hold-tool:${marker}`, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(files.started), "single Manager tool starts");
    const original = structuredClone(manager.getAgentInfo("single", parentId));
    manager.beginPause(parentId);
    await manager.drainSubmissions(parentId);
    let captureDone = false;
    const capture = manager.captureChildren(parentId, randomUUID(), (id: string, saved: SavedSession) => {
      expect(id).toBe(original.id);
      writeFileSync(ownedSnapshot, JSON.stringify(saved));
    }).then(value => { captureDone = true; return value; });
    await until(() => existsSync(files.pauseRequested), "single held child observes native capture fence");
    expect(captureDone).toBe(false);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    writeFileSync(files.release, "release");
    const snapshots = await capture;
    expect(snapshots[original.id].handoff.wasActive).toBe(true);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    const completionState = structuredClone(manager.getCompletionState(parentId));
    expect(completionState.mailbox).toEqual([]);
    await manager.shutdown();

    manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
    await manager.ready();
    manager.beginPause(parentId);
    manager.restoreCompletionState(parentId, completionState);
    const saved: SavedSession = JSON.parse(readFileSync(ownedSnapshot, "utf8"));
    await manager.prepareChildren(parentId, { [original.id]: saved });
    const reopened = manager.getAgentInfo("single", parentId);
    expect(reopened.id).toBe(original.id);
    expect(reopened.sessionFile).toBe(original.sessionFile);
    expect(jsonl(templateStartsFile(original.sessionFile)).at(-1).pause).toBe("paused");
    await delay(50);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    const result = await manager.resumeChild(parentId, original.id, saved, (updated: SavedSession) => {
      writeFileSync(ownedSnapshot, JSON.stringify(updated));
    });
    expect(result.complete, result.error).toBe(true);
    await until(() => manager.getAgentInfo("single", parentId).status === "completed", "single resumed child completes");
    expect(jsonl(files.effects)).toHaveLength(1);
    const calls = jsonl(providerCallsFile(original.sessionFile));
    expect(calls).toHaveLength(2);
    expect(calls.filter(call => call.text === CONTINUATION_MESSAGE)).toHaveLength(1);
    const state = structuredClone(manager.getCompletionState(parentId));
    expect(state.mailbox).toHaveLength(1);
    manager.restoreCompletionState(parentId, state);
    expect(manager.getCompletionState(parentId)).toEqual(state);
    manager.markCompletionDelivered(state.mailbox[0].id);
    manager.markCompletionDelivered(state.mailbox[0].id);
    expect(manager.getCompletionState(parentId).delivered).toEqual([state.mailbox[0].id]);
    manager.endPause(parentId);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);
