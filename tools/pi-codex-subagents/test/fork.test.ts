import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { CONTINUATION_MESSAGE, type SavedSession } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, productionIndex, sourceRpc, testDir, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);

function fixture(cwd: string) {
  const source = SessionManager.create(cwd);
  source.appendMessage({ role: "system", content: "", sections: { preamble: "historical prompt" },
    toolsAdded: [{ name: "historical_only", description: "Historical unavailable tool", parameters: { type: "object", properties: {} } }], timestamp: Date.now() });
  const root = source.appendMessage({ role: "user", content: "retained root", timestamp: Date.now() });
  source.appendMessage(fauxAssistantMessage(fauxToolCall("historical_only", { value: "retained call" }), { stopReason: "toolUse" }));
  const call = (source.getBranch().at(-1) as any).message.content[0];
  source.appendMessage({ role: "toolResult", toolCallId: call.id, toolName: call.name,
    content: [{ type: "text", text: "retained completed result" }], isError: false, timestamp: Date.now() });
  source.appendCompaction("native retained summary", root, 900);
  source.appendMessage({ role: "user", content: "retained selected user", timestamp: Date.now() });
  const cut = source.appendCustomEntry("retained-metadata", { inclusive: true });
  source.appendMessage(fauxAssistantMessage("excluded later response"));
  source.branch(root);
  source.appendMessage({ role: "user", content: "excluded other branch", timestamp: Date.now() });
  source.appendMessage(fauxAssistantMessage("excluded active head"));
  source.appendLabelChange(root, "current bookmark");
  return { source, cut, file: source.getSessionFile()!, before: source.getEntries(), id: source.getSessionId() };
}

sourceTest("native inclusive fork preserves history, source and parent; managed continuation reopens only the child", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-"));
  const original = fixture(cwd);
  // Native readers may repair a missing trailing newline; conversation entries stay identical.
  writeFileSync(original.file, readFileSync(original.file, "utf8").replace(/\n$/, ""));
  const parent = SessionManager.create(cwd);
  parent.appendMessage({ role: "user", content: "unaffected parent", timestamp: Date.now() });
  parent.appendMessage(fauxAssistantMessage("parent response"));
  const parentBefore = parent.getEntries();
  const template = `fork-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\ntools: read\n---\ncurrent template task prefix\n`);
  const roleFile = join(SUBAGENT_DIR, "SYSTEM.md");
  const previousRole = existsSync(roleFile) ? readFileSync(roleFile) : undefined;
  writeFileSync(roleFile, "EDITED_FORK_ROLE_INITIAL_MARKER");
  writeFileSync(join(cwd, "AGENTS.md"), "FORK_SHARED_INITIAL_MARKER");
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const previous = process.env.PI_TEST_CAPTURE_CONTEXT;
  process.env.PI_TEST_CAPTURE_CONTEXT = "1";
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "bounded", message: "required new task", agent_type: template,
      fork_from: { session_id: original.id, through_entry_id: original.cut }, cwd,
      parentSessionId: parent.getSessionId(), parentSessionFile: parent.getSessionFile(),
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    const info = manager.getAgentInfo("bounded", parent.getSessionId());
    await until(() => manager.getAgentInfo("bounded", parent.getSessionId()).status === "completed", "fork child completion");
    const child = SessionManager.open(info.sessionFile);
    expect(child.getSessionId()).toBe(info.sessionId!);
    expect(child.getSessionId()).not.toBe(original.id);
    expect(child.getSessionId()).not.toBe(parent.getSessionId());
    expect(child.getCwd()).toBe(cwd);
    expect(existsSync(child.getHeader()!.parentSession!)).toBe(true);
    expect(SessionManager.open(child.getHeader()!.parentSession!).getHeader()!.parentSession).toBe(original.file);
    expect(child.getEntry(original.cut)?.type).toBe("custom");
    expect(child.getBranch().some(entry => entry.type === "compaction")).toBe(true);
    const request = jsonl(providerCallsFile(info.sessionFile))[0];
    const context = JSON.stringify(request.messages);
    expect(context).toContain("native retained summary");
    expect(context).toContain("retained completed result");
    expect(context).toContain("retained selected user");
    expect(context).not.toContain("excluded later response");
    expect(context).not.toContain("excluded other branch");
    expect(context).not.toContain("excluded active head");
    expect(request.messages.filter((message: any) => message.role === "user").at(-1).content)
      .toEqual([{ type: "text", text: "current template task prefix\n\nrequired new task" }]);
    expect(request.tools.sort()).toEqual(["link_reply", "read"]);
    expect(request.systemPrompt.split("EDITED_FORK_ROLE_INITIAL_MARKER")).toHaveLength(2);
    expect(request.systemPrompt.split("FORK_SHARED_INITIAL_MARKER")).toHaveLength(2);
    expect(request.systemPrompt).toContain("You are an expert coding assistant");
    expect(request.systemPrompt).not.toContain("historical prompt");
    expect(SessionManager.open(original.file).getEntries()).toEqual(original.before);
    expect(parent.getEntries()).toEqual(parentBefore);
    expect(parent.getSessionId()).not.toBe(child.getSessionId());
    expect(SessionManager.open(parent.getSessionFile()!).getEntries()).toEqual(parentBefore);
    const nativeId = child.getSessionId();
    // The origin is no longer available: continuation must use only the child.
    rmSync(original.file);
    writeFileSync(roleFile, "EDITED_FORK_ROLE_CURRENT_MARKER");
    writeFileSync(join(cwd, "AGENTS.md"), "FORK_SHARED_CURRENT_MARKER");
    await manager.sendMessage(parent.getSessionId(), "bounded", "continuation task");
    await until(() => manager.getAgentInfo("bounded", parent.getSessionId()).status === "completed", "recreated child completes");
    expect(SessionManager.open(info.sessionFile).getSessionId()).toBe(nativeId);
    const currentRequests = jsonl(providerCallsFile(info.sessionFile));
    expect(currentRequests).toHaveLength(2);
    expect(currentRequests[1].systemPrompt.split("EDITED_FORK_ROLE_CURRENT_MARKER")).toHaveLength(2);
    expect(currentRequests[1].systemPrompt.split("FORK_SHARED_CURRENT_MARKER")).toHaveLength(2);
    expect(currentRequests[1].systemPrompt).not.toContain("EDITED_FORK_ROLE_INITIAL_MARKER");
    expect(currentRequests[1].systemPrompt).not.toContain("FORK_SHARED_INITIAL_MARKER");
    expect(currentRequests[1].systemPrompt).not.toContain("historical prompt");
    expect(currentRequests[1].text).toBe("continuation task");
    expect(jsonl(info.sessionFile).filter(entry => entry.message?.role === "user"
      && JSON.stringify(entry.message.content).includes("required new task"))).toHaveLength(1);
  } finally {
    await manager.shutdown();
    if (previous === undefined) delete process.env.PI_TEST_CAPTURE_CONTEXT; else process.env.PI_TEST_CAPTURE_CONTEXT = previous;
    if (previousRole === undefined) rmSync(roleFile, { force: true }); else writeFileSync(roleFile, previousRole);
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("registered spawn_agent exposes inclusive fork and rejects missing required message before execution", async () => {
  const { SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-tool-"));
  const original = fixture(cwd);
  const template = `fork-tool-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\ntools: read\n---\n`);
  const parentFile = join(cwd, "parent.jsonl");
  const rpc = sourceRpc(cwd, parentFile, false, [productionIndex]);
  const invoke = (args: Record<string, unknown>) => rpc.request({ type: "prompt", message: `invoke-tool:${JSON.stringify({ name: "spawn_agent", args })}` });
  try {
    const parentState = await rpc.request({ type: "get_state" });
    await invoke({ task_name: "tool-bounded", agent_type: template, message: "required tool task",
      fork_from: { session_id: original.id, through_entry_id: original.cut } });
    await until(() => jsonl(parentFile).some(entry => entry.message?.role === "toolResult" && entry.message.toolName === "spawn_agent"), "actual spawn tool result");
    const result = jsonl(parentFile).find(entry => entry.message?.role === "toolResult" && entry.message.toolName === "spawn_agent").message;
    expect(result.isError).toBe(false);
    expect(result.details.session_id).not.toBe(original.id);
    expect(result.details.fork_from).toEqual({ session_id: original.id, through_entry_id: original.cut });
    expect(result.details.provider).toBe("faux");
    expect(result.details.modelId).toBe("faux-1");
    expect((await rpc.request({ type: "get_state" })).sessionId).toBe(parentState.sessionId);
    await until(() => rpc.records.some(record => record.type === "agent_end"), "parent settles");
    await invoke({ task_name: "missing-message", fork_from: { session_id: original.id, through_entry_id: original.cut } });
    await until(() => jsonl(parentFile).filter(entry => entry.message?.role === "toolResult" && entry.message.toolName === "spawn_agent").length === 2, "missing required message tool rejection");
    const failure = jsonl(parentFile).filter(entry => entry.message?.role === "toolResult" && entry.message.toolName === "spawn_agent")[1].message;
    expect(failure.isError).toBe(true);
    expect(JSON.stringify(failure.content)).toContain("message");
    expect(SessionManager.open(original.file).getEntries()).toEqual(original.before);
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("source/cut failures perform no provider work; omission remains fresh", async () => {
  const { AgentManager } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-errors-"));
  const original = fixture(cwd);
  const parentId = randomUUID();
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const previous = process.env.PI_TEST_CAPTURE_CONTEXT;
  process.env.PI_TEST_CAPTURE_CONTEXT = "1";
  const params = { task_name: "invalid", message: "required", cwd, parentSessionId: parentId,
    inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" as const };
  try {
    await manager.ready();
    await expect(manager.spawnAgent({ ...params, fork_from: { session_id: randomUUID(), through_entry_id: original.cut } }))
      .rejects.toThrow("Source session not found");
    await expect(manager.spawnAgent({ ...params, fork_from: { session_id: original.id, through_entry_id: "missing-cut" } }))
      .rejects.toThrow("Source entry not found");
    const duplicate = join(original.source.getSessionDir(), "duplicate.jsonl");
    copyFileSync(original.file, duplicate);
    await expect(manager.spawnAgent({ ...params, fork_from: { session_id: original.id, through_entry_id: original.cut } }))
      .rejects.toThrow("Ambiguous source session");
    rmSync(duplicate);
    expect(manager.listAgents(undefined, parentId)).toEqual([]);
    await manager.spawnAgent({ ...params, task_name: "fresh" });
    await until(() => manager.getAgentInfo("fresh", parentId).status === "completed", "fresh child completes");
    const fresh = manager.getAgentInfo("fresh", parentId);
    expect(fresh.forkFrom).toBeUndefined();
    const request = jsonl(providerCallsFile(fresh.sessionFile))[0];
    expect(JSON.stringify(request.messages)).not.toContain("retained selected user");
    expect(request.tools).toContain("read");
    expect(request.tools).toContain("bash");
    expect(request.tools).toContain("edit");
    expect(request.tools).toContain("write");
    expect(jsonl(providerCallsFile(fresh.sessionFile))).toHaveLength(1);
    expect(SessionManager.open(original.file).getEntries()).toEqual(original.before);
  } finally {
    await manager.shutdown();
    if (previous === undefined) delete process.env.PI_TEST_CAPTURE_CONTEXT; else process.env.PI_TEST_CAPTURE_CONTEXT = previous;
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("fork restores native source selection, applies native modifiers and never registers unavailable historical tools", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-native-tools-"));
  const extension = join(testDir, "fork-tools-extension.ts");
  const sourceFile = join(cwd, "source.jsonl");
  const rpc = sourceRpc(cwd, sourceFile, false, [extension], { PI_TEST_FORK_SOURCE: "1" });
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const templateFiles: string[] = [];
  let sourceClosed = false;
  try {
    await rpc.request({ type: "prompt", message: "retain the native source tool selection" });
    await until(() => rpc.records.some(record => record.type === "agent_settled"), "source records its real active-tool declaration");
    expect(jsonl(providerCallsFile(sourceFile))[0].tools.sort()).toEqual(["fork_source_only", "grep", "read"]);
    await rpc.close();
    sourceClosed = true;
    const source = SessionManager.open(sourceFile);
    const cut = source.appendCustomEntry("native-tool-selection-cut", {});
    const sourceBefore = source.getEntries();
    await manager.ready();
    for (const selection of [
      { name: "omitted", tools: undefined, expected: ["grep", "link_reply", "read"] },
      { name: "modifiers", tools: "-read,+ls", expected: ["grep", "link_reply", "ls"] },
    ]) {
      const template = `fork-${selection.name}-${randomUUID()}`;
      const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
      templateFiles.push(templateFile);
      mkdirSync(dirname(templateFile), { recursive: true });
      writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${extension}\n${selection.tools ? `tools: ${selection.tools}\n` : ""}---\n`);
      const task = `native-${selection.name}`;
      // Script an actual attempted call: an unavailable declaration must not become executable.
      await manager.spawnAgent({ task_name: task, message: 'invoke-tool:{"name":"fork_source_only","args":{}}',
        agent_type: template, cwd, parentSessionId: source.getSessionId(), parentSessionFile: sourceFile,
        inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off",
        fork_from: { session_id: source.getSessionId(), through_entry_id: cut } });
      const info = manager.getAgentInfo(task, source.getSessionId());
      await until(() => manager.getAgentInfo(task, source.getSessionId()).status === "completed", `${selection.name} native-policy child completes`);
      const registered = JSON.parse(readFileSync(`${info.sessionFile}.fork-tools.json`, "utf8")).registered;
      expect(registered).toContain("fork_default_active");
      expect(registered).toContain("fork_default_inactive");
      expect(registered).not.toContain("fork_source_only");
      const requests = jsonl(providerCallsFile(info.sessionFile));
      expect(requests).toHaveLength(2);
      for (const request of requests) expect(request.tools.sort()).toEqual(selection.expected);
      const rejectedCall = jsonl(info.sessionFile).find(entry => entry.message?.role === "toolResult"
        && entry.message.toolName === "fork_source_only");
      expect(rejectedCall?.message.isError).toBe(true);
      expect(JSON.stringify(rejectedCall.message.content)).toContain("not found");
      expect(SessionManager.open(sourceFile).getEntries()).toEqual(sourceBefore);
    }
  } finally {
    if (!sourceClosed) await rpc.close();
    await manager.shutdown();
    for (const file of templateFiles) rmSync(file, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("fork pause/recreation keeps native identity and completed historical effects without re-extracting the source", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-pause-"));
  const sourceFile = join(cwd, "actual-source.jsonl");
  const historicalMarker = join(cwd, "historical-effect");
  const historicalFiles = heldToolFiles(historicalMarker);
  const sourceRpcSession = sourceRpc(cwd, sourceFile);
  const template = `fork-pause-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\ntools: faux_hold\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "new-effect");
  const files = heldToolFiles(marker);
  const snapshotFile = join(cwd, "saved.json");
  const roleFile = join(SUBAGENT_DIR, "SYSTEM.md");
  const previousRole = existsSync(roleFile) ? readFileSync(roleFile) : undefined;
  writeFileSync(roleFile, "EDITED_PAUSE_ROLE_INITIAL_MARKER");
  writeFileSync(join(cwd, "AGENTS.md"), "PAUSE_SHARED_INITIAL_MARKER");
  let manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  let sourceClosed = false;
  try {
    await sourceRpcSession.request({ type: "prompt", message: `hold-tool:${historicalMarker}` });
    await until(() => existsSync(historicalFiles.started), "actual source tool starts");
    writeFileSync(historicalFiles.release, "release historical tool");
    await until(() => sourceRpcSession.records.some(record => record.type === "agent_settled"), "actual source tool and response finish");
    await sourceRpcSession.close();
    sourceClosed = true;
    expect(jsonl(historicalFiles.effects)).toHaveLength(1);
    const source = SessionManager.open(sourceFile);
    const parentId = source.getSessionId();
    const firstMessage = source.getBranch().find(entry => entry.type === "message")!;
    source.appendCompaction("native history of completed work", firstMessage.id, 1000);
    source.appendMessage({ role: "user", content: "retained boundary after completed effect", timestamp: Date.now() });
    const cut = source.appendCustomEntry("source-completed-boundary", {});
    const originalEntries = source.getEntries();
    const sourceToolResult = originalEntries.find((entry: any) => entry.message?.role === "toolResult" && entry.message.toolName === "faux_hold") as any;
    expect(sourceToolResult.message.details.path).toBe(historicalMarker);
    await manager.ready();
    await manager.spawnAgent({ task_name: "paused-fork", message: `hold-tool:${marker}`, agent_type: template,
      fork_from: { session_id: parentId, through_entry_id: cut }, cwd,
      parentSessionId: parentId, parentSessionFile: sourceFile,
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(files.started), "fork's new task tool starts");
    const initialPrompt = jsonl(providerCallsFile(manager.getAgentInfo("paused-fork", parentId).sessionFile))[0].systemPrompt;
    expect(initialPrompt.split("EDITED_PAUSE_ROLE_INITIAL_MARKER")).toHaveLength(2);
    expect(initialPrompt.split("PAUSE_SHARED_INITIAL_MARKER")).toHaveLength(2);
    const original = structuredClone(manager.getAgentInfo("paused-fork", parentId));
    const nativeId = SessionManager.open(original.sessionFile).getSessionId();
    const fullForkFile = SessionManager.open(original.sessionFile).getHeader()!.parentSession!;
    expect(jsonl(historicalFiles.effects)).toHaveLength(1);
    expect(SessionManager.open(sourceFile).getEntries()).toEqual(originalEntries);
    manager.beginPause(parentId);
    await manager.drainSubmissions(parentId);
    let captured = false;
    const capture = manager.captureChildren(parentId, randomUUID(), (id, saved) => {
      expect(id).toBe(original.id);
      writeFileSync(snapshotFile, JSON.stringify(saved));
    }).then(result => { captured = true; return result; });
    await until(() => existsSync(files.pauseRequested), "fork tool observes native pause fence");
    expect(captured).toBe(false);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    writeFileSync(files.release, "finish admitted fork tool");
    const snapshots = await capture;
    expect(snapshots[original.id].handoff.wasActive).toBe(true);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(historicalFiles.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    await manager.shutdown();

    // Suspended runs outlive retention, including both native files and their parent link.
    const old = new Date(Date.now() - 8 * 86400000);
    const suspended = JSON.parse(readFileSync(original.infoFile, "utf8"));
    Object.assign(suspended, { createdAt: old.getTime(), updatedAt: old.getTime(), lastActivity: old.getTime() });
    writeFileSync(original.infoFile, JSON.stringify(suspended));
    for (const file of [original.infoFile, original.logFile, original.sessionFile, fullForkFile, dirname(original.sessionFile)]) utimesSync(file, old, old);
    rmSync(sourceFile);
    writeFileSync(roleFile, "EDITED_PAUSE_ROLE_CURRENT_MARKER");
    writeFileSync(join(cwd, "AGENTS.md"), "PAUSE_SHARED_CURRENT_MARKER");
    manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    await manager.ready();
    expect(existsSync(fullForkFile)).toBe(true);
    expect(existsSync(original.sessionFile)).toBe(true);
    manager.beginPause(parentId);
    const saved: SavedSession = JSON.parse(readFileSync(snapshotFile, "utf8"));
    await manager.prepareChildren(parentId, { [original.id]: saved });
    const reopened = manager.getAgentInfo("paused-fork", parentId);
    expect(reopened.id).toBe(original.id);
    expect(reopened.sessionId).toBe(nativeId);
    expect(reopened.sessionFile).toBe(original.sessionFile);
    expect(reopened.forkFrom).toEqual({ session_id: parentId, through_entry_id: cut });
    expect(jsonl(templateStartsFile(original.sessionFile)).at(-1).pause).toBe("paused");
    await delay(50);
    expect(jsonl(providerCallsFile(original.sessionFile))).toHaveLength(1);
    const result = await manager.resumeChild(parentId, original.id, saved, updated => writeFileSync(snapshotFile, JSON.stringify(updated)));
    expect(result.complete, result.error).toBe(true);
    await until(() => manager.getAgentInfo("paused-fork", parentId).status === "completed", "fork resumes and completes");
    expect(SessionManager.open(original.sessionFile).getSessionId()).toBe(nativeId);
    expect(jsonl(historicalFiles.effects)).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(1);
    const requests = jsonl(providerCallsFile(original.sessionFile));
    expect(requests).toHaveLength(2);
    expect(requests.at(-1).text).toBe(CONTINUATION_MESSAGE);
    expect(requests.at(-1).systemPrompt.split("EDITED_PAUSE_ROLE_CURRENT_MARKER")).toHaveLength(2);
    expect(requests.at(-1).systemPrompt.split("PAUSE_SHARED_CURRENT_MARKER")).toHaveLength(2);
    expect(requests.at(-1).systemPrompt).not.toContain("EDITED_PAUSE_ROLE_INITIAL_MARKER");
    expect(requests.at(-1).systemPrompt).not.toContain("PAUSE_SHARED_INITIAL_MARKER");
    expect(jsonl(original.sessionFile).filter(entry => entry.message?.role === "toolResult"
      && entry.message.toolCallId === sourceToolResult.message.toolCallId)).toHaveLength(1);
    expect(jsonl(original.sessionFile).filter(entry => entry.message?.role === "user"
      && JSON.stringify(entry.message.content).includes(`hold-tool:${marker}`))).toHaveLength(1);
    manager.endPause(parentId);
  } finally {
    if (!sourceClosed) await sourceRpcSession.close();
    await manager.shutdown();
    if (previousRole === undefined) rmSync(roleFile, { force: true }); else writeFileSync(roleFile, previousRole);
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("retention removes both expired owned native fork files but never the original source or neighboring tasks", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "fork-retention-"));
  const original = fixture(cwd);
  const parentId = randomUUID();
  const template = `fork-retention-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\ntools: read\n---\n`);
  let manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  let forkDirectory: string | undefined;
  let unrelated: string | undefined;
  try {
    await manager.ready();
    const params = { message: "required retention task", agent_type: template, cwd, parentSessionId: parentId,
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" as const };
    await manager.spawnAgent({ ...params, task_name: "expired-fork", fork_from: { session_id: original.id, through_entry_id: original.cut } });
    await manager.spawnAgent({ ...params, task_name: "keep-neighbor" });
    await until(() => ["expired-fork", "keep-neighbor"].every(name => manager.getAgentInfo(name, parentId).status === "completed"), "both retention fixture tasks settle");
    const expired = manager.getAgentInfo("expired-fork", parentId);
    const neighbor = manager.getAgentInfo("keep-neighbor", parentId);
    forkDirectory = dirname(expired.sessionFile);
    const fullFork = SessionManager.open(expired.sessionFile).getHeader()!.parentSession!;
    expect(existsSync(fullFork)).toBe(true);
    expect(dirname(fullFork)).toBe(forkDirectory);
    await manager.shutdown();
    const old = new Date(Date.now() - 8 * 86400000);
    const saved = JSON.parse(readFileSync(expired.infoFile, "utf8"));
    Object.assign(saved, { createdAt: old.getTime(), updatedAt: old.getTime(), lastActivity: old.getTime() });
    writeFileSync(expired.infoFile, JSON.stringify(saved));
    for (const file of [expired.infoFile, expired.logFile, ...readdirSync(forkDirectory).map(name => join(forkDirectory!, name)), forkDirectory]) utimesSync(file, old, old);
    unrelated = join(dirname(expired.infoFile), `${expired.id}.notes`);
    writeFileSync(unrelated, "unrelated owned fixture file");
    manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    await manager.ready();
    expect(existsSync(expired.infoFile)).toBe(false);
    expect(existsSync(expired.logFile)).toBe(false);
    expect(existsSync(expired.sessionFile)).toBe(false);
    expect(existsSync(fullFork)).toBe(false);
    expect(existsSync(forkDirectory)).toBe(false);
    expect(existsSync(unrelated)).toBe(true);
    expect(existsSync(neighbor.infoFile)).toBe(true);
    expect(existsSync(neighbor.sessionFile)).toBe(true);
    expect(SessionManager.open(original.file).getEntries()).toEqual(original.before);
    expect(manager.listAgents(undefined, parentId).map(entry => entry.agent_name)).toEqual(["/keep-neighbor"]);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    if (forkDirectory) rmSync(forkDirectory, { recursive: true, force: true });
    if (unrelated) rmSync(unrelated, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);
