import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { heldToolFiles } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("discard forgets a live child's saved raw inputs, preserves its admitted tool and equal-text core-owned input", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "discard-"));
  const parentId = randomUUID();
  const template = `discard-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const firstMarker = join(cwd, "first");
  const nextMarker = join(cwd, "continued");
  const firstTool = heldToolFiles(firstMarker);
  const nextTool = heldToolFiles(nextMarker);
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "live", agent_type: template,
      message: `hold-tool:${firstMarker}\nresume-hold-tool:${nextMarker}`, cwd,
      parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(firstTool.started), "original tool starts");
    writeFileSync(`${firstMarker}.defer`, "record raw inputs during native handoff settlement");
    manager.beginPause(parentId);
    const capture = manager.captureChildren(parentId, randomUUID(), () => {});
    await until(() => existsSync(firstTool.pauseRequested), "original child reaches pause fence");
    writeFileSync(firstTool.release, "finish original tool");
    const snapshots = await capture;
    const id = manager.getAgentInfo("live", parentId).id;
    const saved = snapshots[id];
    expect(saved.handoff.pending.deferred).toHaveLength(2);
    const originalRaw = saved.handoff.pending.deferred[0];
    expect(originalRaw.kind).toBe("raw");
    if (originalRaw.kind !== "raw") throw new Error("Expected native raw settlement input");
    expect(existsSync(`${firstMarker}.seen`)).toBe(false);
    await manager.prepareChildren(parentId, snapshots);
    await expect(manager.resumeChild(parentId, id, saved, updated => {
      snapshots[id] = updated;
      if (updated.marker === "started") throw new Error("injected parent progress persistence failure");
    })).rejects.toThrow("injected parent progress persistence failure");
    await until(() => existsSync(nextTool.started) && manager.getAgentInfo("live", parentId).status === "running",
      "accepted continuation reaches its own unfinished tool");
    expect(existsSync(nextTool.effects)).toBe(false);
    // A separate occurrence is now acknowledged by native steering admission.
    manager.allowDrainingToolCall(parentId, "core-owned-input");
    await manager.sendMessage(parentId, "live", originalRaw.text, "core-owned-input");
    expect(readFileSync(`${firstMarker}.seen`, "utf8")).toBe(`${originalRaw.text}\n`);
    // Coordinator's durable revocation ordering is tested separately.
    await manager.discardSuspension(parentId);
    expect(manager.getAgentInfo("live", parentId).status).toBe("running");
    expect(existsSync(nextTool.effects)).toBe(false);

    manager.beginPause(parentId);
    const nextCapture = manager.captureChildren(parentId, randomUUID(), (_id, snapshot) => {
      writeFileSync(join(cwd, "next-saved.json"), JSON.stringify(snapshot));
    });
    await until(() => existsSync(nextTool.pauseRequested), "admitted tool remains live until its next safe boundary");
    writeFileSync(nextTool.release, "finish admitted continuation tool");
    const next = await nextCapture;
    expect(next[id].handoff.pending.deferred).toHaveLength(0);
    expect(next[id].handoff.pending.steering).toHaveLength(1);
    expect(jsonl(firstTool.effects)).toHaveLength(1);
    expect(jsonl(nextTool.effects)).toHaveLength(1);
    await manager.prepareChildren(parentId, next);
    expect((await manager.resumeChild(parentId, id, next[id], updated => { next[id] = updated; })).complete).toBe(true);
    manager.endPause(parentId);
    await until(() => manager.getAgentInfo("live", parentId).status === "completed", "new generation completes without revoked input");
    expect(readFileSync(`${firstMarker}.seen`, "utf8")).toBe(`${originalRaw.text}\n`);
    expect(jsonl(firstTool.effects)).toHaveLength(1);
    expect(jsonl(nextTool.effects)).toHaveLength(1);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 25000);
