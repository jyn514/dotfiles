import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { CONTINUATION_MESSAGE, type ControlRecord, type ControlRequest, type SavedSession } from "../handoff.ts";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
for (const fault of ["capture transport", "parent persistence"] as const) {
  sourceTest(`same-generation retry after ${fault} failure preserves both equal inputs and one tool effect`, async () => {
    const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
    const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "retry-"));
    const parentId = randomUUID();
    const template = `retry-${randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
    const marker = join(cwd, "tool");
    const files = heldToolFiles(marker);
    const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
    try {
      await manager.ready();
      await manager.spawnAgent({ task_name: "retry", message: `hold-tool:${marker}`, agent_type: template,
        cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => existsSync(files.started), "native tool starts before capture");
      const original = manager.getAgentInfo("retry", parentId);
      await manager.sendMessage(parentId, "retry", "same pending input");
      await manager.sendMessage(parentId, "retry", "same pending input");
      manager.beginPause(parentId);
      const generation = randomUUID();
      let injected = false;
      // Inject only a transport-boundary failure, not fake native admission or capture.
      const transport = manager as unknown as {
        control(live: unknown, request: ControlRequest): Promise<ControlRecord>;
      };
      const nativeControl = transport.control.bind(manager);
      if (fault === "capture transport") transport.control = async (live, request) => {
        if (request.action === "capture" && !injected) {
          injected = true;
          throw new Error("transient capture transport failure");
        }
        return nativeControl(live, request);
      };
      let retained: SavedSession | undefined;
      const first = manager.captureChildren(parentId, generation, (_id, saved) => {
        retained = saved;
        if (!injected) { injected = true; throw new Error("transient parent persistence failure"); }
      });
      if (fault === "parent persistence") {
        await until(() => existsSync(files.pauseRequested), "child reaches its native pause request");
        writeFileSync(files.release, "finish the already admitted tool");
      }
      await expect(first).rejects.toThrow(`transient ${fault}`);
      if (fault === "capture transport") writeFileSync(files.release, "finish the already admitted tool");
      const snapshots = await manager.captureChildren(parentId, generation, () => {});
      const saved = snapshots[original.id];
      if (retained) expect(saved).toBe(retained);
      expect(saved.handoff.wasActive).toBe(true);
      expect(saved.handoff.pending.steering).toHaveLength(2);
      expect(new Set(saved.items.map(item => item.id)).size).toBe(2);
      expect(jsonl(files.effects)).toHaveLength(1);
      expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
      await manager.prepareChildren(parentId, snapshots);
      expect((await manager.resumeChild(parentId, original.id, saved, updated => { snapshots[original.id] = updated; })).complete).toBe(true);
      manager.endPause(parentId);
      await until(() => manager.getAgentInfo("retry", parentId).status === "completed", "fresh continuation completes");
      const entries = SessionManager.open(original.sessionFile).getBranch();
      expect(entries.filter(entry => entry.type === "custom_message" && (typeof entry.content === "string"
        ? entry.content === "same pending input"
        : entry.content.length === 1 && entry.content[0].type === "text" && entry.content[0].text === "same pending input"))).toHaveLength(2);
      expect(jsonl(files.effects)).toHaveLength(1);
      expect(entries.filter(entry => entry.type === "message" && entry.message.role === "user"
        && (typeof entry.message.content === "string" ? entry.message.content === CONTINUATION_MESSAGE
          : entry.message.content.some(part => part.type === "text" && part.text === CONTINUATION_MESSAGE)))).toHaveLength(1);
    } finally {
      await manager.shutdown();
      rmSync(templateFile, { force: true });
      rmSync(cwd, { recursive: true, force: true });
    }
  }, 20000);
}
