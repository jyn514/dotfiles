import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("failed held-process startup is not the saved task's terminal outcome; repair retries without the original task", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "startup-"));
  const parentId = randomUUID();
  const template = `startup-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "tool");
  const files = heldToolFiles(marker);
  const executable = process.env.PI_SUBAGENT_PI_BIN;
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "startup", message: `hold-tool:${marker}`, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(files.started), "native tool starts");
    const original = manager.getAgentInfo("startup", parentId);
    manager.beginPause(parentId);
    const capture = manager.captureChildren(parentId, randomUUID(), () => {});
    await until(() => existsSync(files.pauseRequested), "native child reaches pause request");
    writeFileSync(files.release, "complete original tool once");
    const snapshots = await capture;
    expect(snapshots[original.id].handoff.wasActive).toBe(true);
    process.env.PI_SUBAGENT_PI_BIN = join(cwd, "missing-pi");
    await expect(manager.prepareChildren(parentId, snapshots)).rejects.toThrow();
    expect(manager.getAgentInfo("startup", parentId).status).toBe("suspended");
    expect(manager.getAgentInfo("startup", parentId).error).toContain("Restoration failed before continuation admission");
    expect(manager.getCompletionState(parentId).mailbox).toHaveLength(0);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    process.env.PI_SUBAGENT_PI_BIN = executable;
    await manager.prepareChildren(parentId, snapshots);
    expect(manager.getAgentInfo("startup", parentId).status).toBe("suspended");
    expect((await manager.resumeChild(parentId, original.id, snapshots[original.id], updated => { snapshots[original.id] = updated; })).complete).toBe(true);
    manager.endPause(parentId);
    await until(() => manager.getAgentInfo("startup", parentId).status === "completed", "fresh continuation completes after startup repair");
    expect(manager.getAgentInfo("startup", parentId).id).toBe(original.id);
    expect(manager.getAgentInfo("startup", parentId).sessionFile).toBe(original.sessionFile);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(2);
  } finally {
    if (executable === undefined) delete process.env.PI_SUBAGENT_PI_BIN;
    else process.env.PI_SUBAGENT_PI_BIN = executable;
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);
