import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { LINK_MESSAGE_TYPE, admittedLink, type LinkDelivery } from "../link.ts";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("Manager link selects owned live workers, validates native replies and routes by stable ID without waking paused/completed tasks", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-"));
  const parentId = randomUUID();
  const foreignId = randomUUID();
  const template = `source-link-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\ntools: faux_hold\nextensions: ${heldExtension}\n---\n`);
  const replies: any[] = [];
  const completions: any[] = [];
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000,
    onLinkReply: async event => {
      replies.push(event);
      return { content: [{ type: "text", text: "accepted native worker reply" }], details: { status: "submitted" } };
    }, onUnclaimedCompletion: event => completions.push(event) });
  const otherManager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const spawn = async (name: string, owner = parentId, ownerManager = manager) => {
    const marker = join(cwd, name);
    await ownerManager.spawnAgent({ task_name: name, message: `link-worker:${marker}`, agent_type: template,
      cwd, parentSessionId: owner, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(heldToolFiles(`${marker}.first`).started), `${name} initial real tool`);
    return { marker, info: structuredClone(ownerManager.getAgentInfo(name, owner)) };
  };
  const delivery = (id = randomUUID()): LinkDelivery => ({ from: "remote-root", fromSessionId: randomUUID(),
    id, content: "native root broadcast", broadcast: true });
  const entries = (file: string) => jsonl(file);
  try {
    await Promise.all([manager.ready(), otherManager.ready()]);
    const one = await spawn("one");
    const two = await spawn("two");
    const foreign = await spawn("foreign", foreignId);
    const privateWorker = await spawn("private", parentId, otherManager);
    expect((await manager.replyLink(parentId, { workerId: privateWorker.info.id, taskName: "one" }, delivery())).status).toBe("skipped");
    for (const worker of [one, two, foreign, privateWorker]) {
      expect(worker.info.tools).toBe("faux_hold");
      expect(jsonl(providerCallsFile(worker.info.sessionFile))[0].tools.sort()).toEqual(["faux_hold", "link_reply"]);
    }
    const message = delivery();
    const result = await manager.broadcastLink(parentId, message);
    expect(result.map(worker => worker.workerId).sort()).toEqual([one.info.id, two.info.id].sort());
    expect(result.every(worker => worker.status === "submitted"), JSON.stringify(result)).toBe(true);
    // Native queued steering is not yet a delivered transcript reference.
    expect(entries(one.info.sessionFile).some(entry => admittedLink(entry, parentId, one.info.id)?.id === message.id)).toBe(false);
    expect(replies).toEqual([]);
    expect(entries(foreign.info.sessionFile).some(entry => entry.message?.customType === LINK_MESSAGE_TYPE)).toBe(false);
    const callsBeforeForeign = jsonl(providerCallsFile(foreign.info.sessionFile)).length;
    expect(await manager.replyLink(parentId, { workerId: foreign.info.id, taskName: "one" }, delivery())).toEqual({
      status: "skipped", reason: "worker_not_owned_or_inactive" });
    expect(jsonl(providerCallsFile(foreign.info.sessionFile))).toHaveLength(callsBeforeForeign);

    writeFileSync(heldToolFiles(`${one.marker}.first`).release, "release");
    writeFileSync(heldToolFiles(`${two.marker}.first`).release, "release");
    await until(() => replies.length === 2, "both workers independently reply to one broadcast");
    expect(new Set(replies.map(event => event.worker.workerId))).toEqual(new Set([one.info.id, two.info.id]));
    for (const reply of replies) {
      expect(reply.ownerSessionId).toBe(parentId);
      expect(reply.reference).toEqual(message);
      expect(reply.message).toBe("native worker reply");
    }
    for (const worker of [one, two]) {
      await until(() => existsSync(heldToolFiles(`${worker.marker}.second`).started), "reply tool returned native routing result");
      const replyResult = entries(worker.info.sessionFile).find(entry => entry.message?.role === "toolResult" && entry.message.toolName === "link_reply");
      expect(replyResult?.message.details).toEqual({ status: "submitted" });
    }
    const privateMessage = { ...delivery(), broadcast: false, replyTo: message.id, content: "private stable worker reply" };
    // Display name is not authority, including a misleading name of a different task.
    expect(await manager.replyLink(parentId, { workerId: one.info.id, taskName: "two" }, privateMessage)).toEqual({ status: "submitted" });
    writeFileSync(heldToolFiles(`${one.marker}.second`).release, "release");
    await until(() => manager.getAgentInfo("one", parentId).status === "completed", "first worker completes normally");
    expect(replies.filter(event => event.worker.workerId === one.info.id).map(event => event.reference.id)).toEqual([message.id, privateMessage.id]);
    expect(entries(two.info.sessionFile).some(entry => admittedLink(entry, parentId, two.info.id)?.id === privateMessage.id)).toBe(false);
    const before = readFileSync(one.info.sessionFile, "utf8");
    const calls = jsonl(providerCallsFile(one.info.sessionFile)).length;
    expect((await manager.replyLink(parentId, { workerId: one.info.id, taskName: "one" }, delivery())).status).toBe("skipped");
    expect(readFileSync(one.info.sessionFile, "utf8")).toBe(before);
    expect(jsonl(providerCallsFile(one.info.sessionFile))).toHaveLength(calls);
    expect(completions.filter(event => event.agentName === one.info.canonicalName)).toHaveLength(1);

    // Native pause without the group-level pause map must still fence deliveries.
    await manager.pauseChildren(parentId);
    await until(() => existsSync(heldToolFiles(`${two.marker}.second`).pauseRequested), "native child pause observed");
    const twoCalls = jsonl(providerCallsFile(two.info.sessionFile)).length;
    const pausedMessage = delivery();
    expect((await manager.replyLink(parentId, { workerId: two.info.id, taskName: "two" }, pausedMessage)).status).toBe("skipped");
    expect((await manager.broadcastLink(parentId, pausedMessage)).every(worker => worker.status === "skipped")).toBe(true);
    manager.beginPause(parentId);
    expect((await manager.replyLink(parentId, { workerId: two.info.id, taskName: "two" }, delivery())).status).toBe("skipped");
    await delay(50);
    expect(jsonl(providerCallsFile(two.info.sessionFile))).toHaveLength(twoCalls);
    expect(entries(two.info.sessionFile).some(entry => admittedLink(entry, parentId, two.info.id)?.id === pausedMessage.id)).toBe(false);
    expect(manager.getAgentInfo("two", parentId).childProcess?.pid).toBe(two.info.childProcess?.pid);
  } finally {
    await Promise.all([manager.shutdown(), otherManager.shutdown()]);
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("Manager link never releases restored-held children and remains available after successful native resume", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-resume-"));
  const parentId = randomUUID();
  const template = `source-link-resume-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "worker");
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const message: LinkDelivery = { from: "root", fromSessionId: randomUUID(), id: randomUUID(), content: "after native resume" };
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "resumed", message: `link-worker:${marker}`, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(heldToolFiles(`${marker}.first`).started), "initial held tool");
    const info = structuredClone(manager.getAgentInfo("resumed", parentId));
    const worker = { workerId: info.id, taskName: info.canonicalName };
    manager.beginPause(parentId);
    await manager.drainSubmissions(parentId);
    const capture = manager.captureChildren(parentId, randomUUID(), () => {});
    await until(() => existsSync(heldToolFiles(`${marker}.first`).pauseRequested), "capture pause fence");
    writeFileSync(heldToolFiles(`${marker}.first`).release, "release");
    const snapshots = await capture;
    await manager.prepareChildren(parentId, snapshots);
    const before = jsonl(providerCallsFile(info.sessionFile)).length;
    // Remove the parent fence deliberately: held native/control state alone still owns admission.
    manager.endPause(parentId);
    expect((await manager.replyLink(parentId, worker, message)).status).toBe("skipped");
    expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(before);
    manager.beginPause(parentId);
    const resumed = await manager.resumeChild(parentId, info.id, snapshots[info.id], () => {});
    expect(resumed.complete, resumed.error).toBe(true);
    manager.endPause(parentId);
    await until(() => existsSync(heldToolFiles(`${marker}.second`).started), "resumed worker is actually active");
    expect(await manager.replyLink(parentId, worker, message)).toEqual({ status: "submitted" });
    writeFileSync(heldToolFiles(`${marker}.second`).release, "release");
    await until(() => manager.getAgentInfo("resumed", parentId).status === "completed", "resumed worker completion");
    const records = jsonl(info.sessionFile);
    expect(records.some(entry => admittedLink(entry, parentId, info.id)?.id === message.id)).toBe(true);
    expect(records.find(entry => entry.message?.toolName === "link_reply")?.message.details).toEqual({
      status: "unsupported", reason: "link_integration_unavailable" });
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);

sourceTest("native queued link admission does not grant reply authority to the same in-flight tool batch", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-queued-"));
  const parentId = randomUUID();
  const template = `source-link-queued-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "batch");
  const replies: unknown[] = [];
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000, onLinkReply: async event => {
    replies.push(event);
    return { content: [{ type: "text", text: "should not route" }], details: { status: "submitted" } };
  } });
  const message: LinkDelivery = { from: "root", fromSessionId: randomUUID(), id: randomUUID(), content: "not admitted during old batch" };
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "queued", message: `queued-link-reply:${JSON.stringify({ path: marker, replyTo: message.id })}`,
      agent_type: template, cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(heldToolFiles(marker).started), "first tool of native assistant batch held");
    const info = manager.getAgentInfo("queued", parentId);
    expect(await manager.replyLink(parentId, { workerId: info.id, taskName: info.canonicalName }, message)).toEqual({ status: "submitted" });
    expect(jsonl(info.sessionFile).some(entry => admittedLink(entry, parentId, info.id)?.id === message.id)).toBe(false);
    expect(existsSync(`${marker}.link-reply-started`)).toBe(false);
    expect(jsonl(info.sessionFile).some(entry => entry.message?.toolName === "link_reply")).toBe(false);
    writeFileSync(heldToolFiles(marker).release, "release");
    await until(() => manager.getAgentInfo("queued", parentId).status === "completed", "same batch reply denied and queued message consumed normally");
    const records = jsonl(info.sessionFile);
    const reply = records.find(entry => entry.message?.role === "toolResult" && entry.message.toolName === "link_reply");
    const hold = records.find(entry => entry.message?.role === "toolResult" && entry.message.toolName === "faux_hold_sequential");
    expect(hold).toBeDefined();
    expect(records.indexOf(hold)).toBeLessThan(records.indexOf(reply));
    expect(JSON.parse(readFileSync(`${marker}.link-reply-started`, "utf8")).holdEnded).toBe(true);
    expect(reply?.message.isError).toBe(true);
    expect(reply?.message.details).toEqual({ status: "failed", reason: "unknown_reference" });
    expect(replies).toEqual([]);
    const deliveryIndex = records.findIndex(entry => admittedLink(entry, parentId, info.id)?.id === message.id);
    expect(deliveryIndex).toBeGreaterThan(records.indexOf(reply));
    expect(jsonl(heldToolFiles(marker).effects)).toHaveLength(1);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 15000);

sourceTest("Manager broadcast snapshots a starting worker, waits existing native startup, and delivers only once active", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-starting-"));
  const parentId = randomUUID();
  const template = `source-link-starting-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  const startupExtension = new URL("./link-startup-extension.ts", import.meta.url).pathname;
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}, ${startupExtension}\n---\n`);
  const marker = join(cwd, "worker");
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  const message: LinkDelivery = { from: "root", fromSessionId: randomUUID(), id: randomUUID(), content: "selected during startup" };
  let spawn: Promise<unknown> | undefined;
  try {
    await manager.ready();
    spawn = manager.spawnAgent({ task_name: "starting", message: `link-worker:${marker}`, agent_type: template,
      cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(join(cwd, "startup-started")), "real async session_start barrier entered");
    const info = structuredClone(manager.getAgentInfo("starting", parentId));
    expect(info.status).toBe("starting");
    expect(existsSync(heldToolFiles(`${marker}.first`).started)).toBe(false);
    expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(0);
    let broadcastSettled = false;
    // Selection occurs synchronously before broadcastLink's first await.
    const broadcast = manager.broadcastLink(parentId, message).then(result => { broadcastSettled = true; return result; });
    await delay(30);
    expect(broadcastSettled).toBe(false);
    expect(manager.getAgentInfo("starting", parentId).status).toBe("starting");
    writeFileSync(join(cwd, "startup-release"), "release native startup");
    await spawn;
    expect(await broadcast).toEqual([{ workerId: info.id, taskName: info.canonicalName, status: "submitted" }]);
    await until(() => existsSync(heldToolFiles(`${marker}.first`).started), "same starting child became active");
    const startup = JSON.parse(readFileSync(join(cwd, "startup-started"), "utf8"));
    expect(manager.getAgentInfo("starting", parentId).childProcess?.pid).toBe(startup.pid);
    writeFileSync(heldToolFiles(`${marker}.first`).release, "release first tool");
    await until(() => existsSync(heldToolFiles(`${marker}.second`).started), "native helper delivery admitted after first tool");
    const records = jsonl(info.sessionFile);
    expect(records.filter(entry => admittedLink(entry, parentId, info.id, startup.sessionId)?.id === message.id)).toHaveLength(1);
    expect(records.find(entry => entry.message?.toolName === "link_reply")?.message.details).toEqual({
      status: "unsupported", reason: "link_integration_unavailable" });
  } finally {
    writeFileSync(join(cwd, "startup-release"), "cleanup releases owned barrier");
    await spawn?.catch(() => {});
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 15000);

sourceTest("an admitted worker reply reference survives child recreation and native resume in the same session", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-persisted-"));
  const parentId = randomUUID();
  const template = `source-link-persisted-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${heldExtension}\n---\n`);
  const marker = join(cwd, "worker");
  const replies: any[] = [];
  let manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  const message: LinkDelivery = { from: "original remote root", fromSessionId: randomUUID(), id: randomUUID(), content: "reference admitted before capture" };
  try {
    await manager.ready();
    await manager.spawnAgent({ task_name: "persisted", message: `saved-link-reference:${JSON.stringify({ path: marker, replyTo: message.id })}`,
      agent_type: template, cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    await until(() => existsSync(heldToolFiles(`${marker}.first`).started), "first held tool before admission");
    const info = structuredClone(manager.getAgentInfo("persisted", parentId));
    const worker = { workerId: info.id, taskName: info.canonicalName };
    expect(await manager.replyLink(parentId, worker, message)).toEqual({ status: "submitted" });
    writeFileSync(heldToolFiles(`${marker}.first`).release, "release first tool for real admission");
    await until(() => existsSync(heldToolFiles(`${marker}.second`).started), "second held tool after admission");
    const admittedBefore = jsonl(info.sessionFile).find(entry => admittedLink(entry, parentId, info.id)?.id === message.id);
    expect(admittedBefore).toBeDefined();
    const sessionId = admittedBefore.details.recipientSessionId;
    expect(typeof sessionId).toBe("string");
    expect(jsonl(info.sessionFile).some(entry => entry.message?.toolName === "link_reply")).toBe(false);
    manager.beginPause(parentId);
    await manager.drainSubmissions(parentId);
    const capture = manager.captureChildren(parentId, randomUUID(), () => {});
    await until(() => existsSync(heldToolFiles(`${marker}.second`).pauseRequested), "native capture after old reference admission");
    writeFileSync(heldToolFiles(`${marker}.second`).release, "release second tool for capture");
    const snapshots = await capture;
    expect(snapshots[info.id].handoff.sessionId).toBe(sessionId);
    const completionState = structuredClone(manager.getCompletionState(parentId));
    await manager.shutdown();
    manager = new AgentManager({ modelResponseTimeoutMs: 10000, onLinkReply: async event => {
      replies.push(event);
      return { content: [{ type: "text", text: "persisted reference accepted" }], details: { status: "submitted" } };
    } });
    await manager.ready();
    manager.beginPause(parentId);
    manager.restoreCompletionState(parentId, completionState);
    await manager.prepareChildren(parentId, snapshots);
    const reopened = manager.getAgentInfo("persisted", parentId);
    expect(reopened.id).toBe(info.id);
    expect(reopened.sessionFile).toBe(info.sessionFile);
    expect(reopened.childProcess?.pid).not.toBe(info.childProcess?.pid);
    const resumed = await manager.resumeChild(parentId, info.id, snapshots[info.id], () => {});
    expect(resumed.complete, resumed.error).toBe(true);
    manager.endPause(parentId);
    await until(() => existsSync(heldToolFiles(`${marker}.resume`).started), "resumed tool batch waits for group release");
    writeFileSync(heldToolFiles(`${marker}.resume`).release, "group release completed; allow reply against old reference");
    await until(() => manager.getAgentInfo("persisted", parentId).status === "completed", "resumed worker finishes reply tool");
    expect(replies, JSON.stringify(jsonl(info.sessionFile).filter(entry => entry.message?.toolName === "link_reply"))).toHaveLength(1);
    expect(replies[0]).toEqual({ ownerSessionId: parentId, worker, reference: message, message: "reply after child recreation" });
    await until(() => manager.getAgentInfo("persisted", parentId).status === "completed", "resumed native reply result returns to worker");
    const records = jsonl(info.sessionFile);
    expect(records.filter(entry => admittedLink(entry, parentId, info.id, sessionId)?.id === message.id)).toHaveLength(1);
    expect(records.find(entry => entry.message?.toolName === "link_reply")?.message.details).toEqual({ status: "submitted" });
    expect(records.find(entry => entry.type === "session")?.id).toBe(sessionId);
  } finally {
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 20000);

for (const configuration of [
  { label: "empty allowlist", tools: "", held: false },
  { label: "native tool modifiers", tools: "+faux_hold,-link_reply", held: true },
]) {
  sourceTest(`Manager derives helper registration without widening ${configuration.label}`, async () => {
    const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
    const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-tools-"));
    const parentId = randomUUID();
    const template = `source-link-tools-${randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    writeFileSync(templateFile, `---\nname: ${template}\ntools: ${configuration.tools}\nextensions: ${heldExtension}\n---\n`);
    const marker = join(cwd, "worker");
    const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
    try {
      await manager.ready();
      await manager.spawnAgent({ task_name: "tools", message: configuration.held ? `link-worker:${marker}` : "ordinary task without builtin or task tools",
        agent_type: template, cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      const info = structuredClone(manager.getAgentInfo("tools", parentId));
      await until(() => jsonl(providerCallsFile(info.sessionFile)).length > 0, "actual native provider tool inventory");
      expect(info.tools).toBe(configuration.tools);
      const tools = jsonl(providerCallsFile(info.sessionFile))[0].tools as string[];
      expect(tools).toContain("link_reply");
      for (const rootTool of ["link_send", "link_set_identity", "link_list", "link_compact"]) expect(tools).not.toContain(rootTool);
      if (configuration.held) {
        for (const intendedTool of ["read", "bash", "edit", "write", "faux_hold"]) expect(tools).toContain(intendedTool);
        await until(() => existsSync(heldToolFiles(`${marker}.first`).started), "modifier retains intended task tool");
        const message: LinkDelivery = { from: "root", fromSessionId: randomUUID(), id: randomUUID(), content: "modifier worker input" };
        expect(await manager.replyLink(parentId, { workerId: info.id, taskName: info.canonicalName }, message)).toEqual({ status: "submitted" });
        writeFileSync(heldToolFiles(`${marker}.first`).release, "release for actual helper invocation");
        await until(() => existsSync(heldToolFiles(`${marker}.second`).started), "modifier worker invoked helper and received native result");
        expect(jsonl(info.sessionFile).find(entry => entry.message?.toolName === "link_reply")?.message.details).toEqual({
          status: "unsupported", reason: "link_integration_unavailable" });
      } else {
        expect(tools).toEqual(["link_reply"]);
        await until(() => manager.getAgentInfo("tools", parentId).status === "completed", "empty task allowlist completes normally");
      }
    } finally {
      await manager.shutdown();
      rmSync(templateFile, { force: true });
      rmSync(cwd, { recursive: true, force: true });
    }
  }, 15000);
}

sourceTest("starting worker that finishes between selection and delivery is skipped without another run", async () => {
  const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
  const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "manager-link-finished-"));
  const template = `source-link-finished-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  const startupExtension = new URL("./link-startup-extension.ts", import.meta.url).pathname;
  mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${startupExtension}\n---\n`);
  const manager = new AgentManager({ modelResponseTimeoutMs: 10000 });
  let spawn: Promise<unknown> | undefined;
  let currentCwd = root;
  try {
    await manager.ready();
    for (let attempt = 0; attempt < 3; attempt++) {
      const cwd = join(root, String(attempt));
      currentCwd = cwd;
      mkdirSync(cwd);
      const parentId = randomUUID();
      const message: LinkDelivery = { from: "root", fromSessionId: randomUUID(), id: randomUUID(), content: "must not wake finished worker" };
      spawn = manager.spawnAgent({ task_name: "finishes", message: "instant native final response", agent_type: template,
        cwd, parentSessionId: parentId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => existsSync(join(cwd, "startup-started")), "instant worker waits real startup barrier");
      const info = structuredClone(manager.getAgentInfo("finishes", parentId));
      expect(info.status).toBe("starting");
      expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(0);
      // This promise snapshots the live starting worker before the barrier releases.
      const broadcast = manager.broadcastLink(parentId, message);
      writeFileSync(join(cwd, "startup-release"), "release instant task");
      await spawn;
      const result = await broadcast;
      expect(result).toHaveLength(1);
      expect(result[0].workerId).toBe(info.id);
      expect(result[0].status, JSON.stringify(result)).toBe("skipped");
      await until(() => manager.getAgentInfo("finishes", parentId).status === "completed", "instant worker finishes its original run");
      expect(jsonl(providerCallsFile(info.sessionFile))).toHaveLength(1);
      expect(jsonl(info.sessionFile).some(entry => admittedLink(entry, parentId, info.id)?.id === message.id)).toBe(false);
      expect(manager.getAgentInfo("finishes", parentId).messageCount).toBe(1);
    }
  } finally {
    writeFileSync(join(currentCwd, "startup-release"), "cleanup releases owned startup");
    await spawn?.catch(() => {});
    await manager.shutdown();
    rmSync(templateFile, { force: true });
    rmSync(root, { recursive: true, force: true });
  }
}, 20000);
