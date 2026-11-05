import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { LINK_MESSAGE_TYPE } from "../link.ts";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, productionIndex, sourceRpc, until } from "./source-runtime.ts";

// pi-link is independently deployed, not a dependency of this package. Opt in
// with its actual source so this tests both production extensions, not a fake bus.
const linkSource = process.env.PI_TEST_LINK_SOURCE;
const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG || !linkSource);
type Peer = ReturnType<typeof sourceRpc>;
const rootLinks = (entries: any[]) => entries.filter(entry => entry.type === "custom_message" && entry.customType === "link");
const workerLinks = (file: string) => jsonl(file).filter(entry => entry.type === "custom_message" && entry.customType === LINK_MESSAGE_TYPE);

async function entries(peer: Peer) { return (await peer.request({ type: "get_entries" })).entries; }
async function tool(peer: Peer, name: string, args: unknown): Promise<any> {
  await until(async () => !(await peer.request({ type: "get_state" })).isStreaming, `idle before ${name}`);
  const start = peer.records.length;
  await peer.request({ type: "prompt", message: `invoke-tool:${JSON.stringify({ name, args })}` });
  await until(() => peer.records.slice(start).some(event => event.type === "tool_execution_end" && event.toolName === name), `${name} completes`);
  const event = peer.records.slice(start).find(event => event.type === "tool_execution_end" && event.toolName === name);
  expect(event.isError, JSON.stringify(event.result)).not.toBe(true);
  return event.result;
}

async function disposableLink(cwd: string): Promise<string> {
  const reservation = createServer();
  await new Promise<void>(done => reservation.listen(0, "127.0.0.1", done));
  const port = (reservation.address() as { port: number }).port;
  await new Promise<void>(done => reservation.close(() => done()));
  const extensionDir = join(cwd, "link");
  mkdirSync(extensionDir);
  // The production extension has a fixed loopback port. Change only that value
  // in byte-verified disposable copies, never the authoritative checkout.
  for (const name of readdirSync(dirname(linkSource!)).filter(name => /\.[cm]?[jt]s$/.test(name))) {
    const from = join(dirname(linkSource!), name);
    const to = join(extensionDir, name);
    copyFileSync(from, to);
    expect(readFileSync(to).equals(readFileSync(from))).toBe(true);
  }
  const fixtureLink = join(extensionDir, "index.ts");
  const original = readFileSync(fixtureLink, "utf8");
  expect(original.match(/const DEFAULT_PORT = 9900;/g)).toHaveLength(1);
  writeFileSync(fixtureLink, original.replace("const DEFAULT_PORT = 9900;", `const DEFAULT_PORT = ${port};`));
  symlinkSync(join(dirname(linkSource!), "node_modules"), join(extensionDir, "node_modules"), "dir");
  return fixtureLink;
}

sourceTest("two real linked roots deliver to owned active children and return private worker replies without relaying through the owner model", async () => {
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "link-native-"));
  const fixtureLink = await disposableLink(cwd);
  const template = `link-native-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(dirname(templateFile), { recursive: true });
  // This bridge-only template explicitly opts out of an independent endpoint.
  // The same configured extension is otherwise available to workers.
  writeFileSync(templateFile, `---\nname: ${template}\ntools: faux_hold\nextensions: ${heldExtension}, ${fixtureLink}\ndisabledExtensions: ${fixtureLink}\n---\n`);
  const peers: Peer[] = [];
  const markers: string[] = [];
  try {
    const start = async (name: string) => {
      const dir = join(cwd, name);
      mkdirSync(dir);
      const peer = sourceRpc(dir, join(dir, "session.jsonl"), false, [productionIndex, fixtureLink, heldExtension],
        { PI_LINK_NAME: `${name}@native-link` });
      peers.push(peer);
      await peer.request({ type: "get_state" });
      return peer;
    };
    const sender = await start("sender");
    const owner = await start("owner");
    await until(async () => {
      const result = await tool(sender, "link_list", {});
      return Object.keys(result.details?.sessionIds ?? {}).length === 2;
    }, "both roots join their link group");
    const senderId = (await sender.request({ type: "get_state" })).sessionId;
    const ownerId = (await owner.request({ type: "get_state" })).sessionId;
    const worker = async (peer: Peer, task: string) => {
      const marker = join(cwd, task);
      markers.push(marker);
      await tool(peer, "spawn_agent", { task_name: task, message: `hold-tool:${marker}`, agent_type: template });
      await until(() => existsSync(heldToolFiles(marker).started), `${task} runs its native held tool`);
      // Inspect owned persisted manager state to locate the child's native
      // transcript, without constructing another manager or issuing worker input.
      const stored = readdirSync(getRunsDir(), { recursive: true }) as string[];
      const infos = stored.filter(name => name.endsWith(".info.json"))
        .map(name => JSON.parse(readFileSync(join(getRunsDir(), name), "utf8")));
      const parentSessionId = (await peer.request({ type: "get_state" })).sessionId;
      const info = infos.find(info => info.taskName === task && info.parentSessionId === parentSessionId);
      expect(info).toBeDefined();
      return { marker, info };
    };
    const own = await worker(sender, "own-worker");
    const first = await worker(owner, "first-worker");
    const sibling = await worker(owner, "sibling-worker");
    const all = [own, first, sibling];
    for (const { info } of all) {
      const tools = jsonl(providerCallsFile(info.sessionFile))[0].tools;
      expect(tools).toContain("link_send");
      for (const forbidden of ["link_reply", "link_set_identity", "link_list", "link_compact"]) expect(tools).not.toContain(forbidden);
    }
    const broadcast = await tool(sender, "link_send", { to: { broadcast: true }, message: "ask-link-question", includeSubagents: true });
    const outcomes = broadcast.details.outcomes;
    expect(outcomes.filter((item: any) => item.kind === "root").map((item: any) => item.sessionId)).toEqual([ownerId]);
    expect(outcomes.filter((item: any) => item.kind === "worker")).toHaveLength(3);
    expect(outcomes.every((item: any) => item.status === "submitted"), JSON.stringify(outcomes)).toBe(true);
    for (const { marker, info } of all) {
      // Submission is queued while the held tool runs, not actual delivery yet.
      expect(workerLinks(info.sessionFile)).toHaveLength(0);
      writeFileSync(heldToolFiles(marker).release, "release");
    }
    await until(() => all.every(({ marker }) => existsSync(heldToolFiles(`${marker}.after-question`).started)),
      "three workers independently ask the same question and stay active");
    let questions: any[] = [];
    await until(async () => {
      questions = rootLinks(await entries(sender)).flatMap(entry => entry.details?.deliveries ?? []).filter(message => message.fromWorker);
      return questions.length === 3;
    }, "sender receives three actual worker-authored messages");
    expect(new Set(questions.map(message => message.id)).size).toBe(3);
    expect(new Set(questions.map(message => message.fromWorker.workerId))).toEqual(new Set(all.map(({ info }) => info.id)));
    for (const { info } of all) {
      const messages = workerLinks(info.sessionFile);
      expect(messages).toHaveLength(1);
      expect(messages[0].details.delivery.id).toBe(broadcast.details.messageId);
      expect(messages[0].details.delivery.fromSessionId).toBe(senderId);
    }
    // Native parent B history has only its own broadcast copy, never its workers'
    // questions; private routing is not a parent-model forwarding instruction.
    expect(rootLinks(await entries(owner)).flatMap(entry => entry.details?.deliveries ?? []).some(message => message.fromWorker)).toBe(false);
    const question = questions.find(message => message.fromWorker.workerId === first.info.id);
    const answer = await tool(sender, "link_send", { to: { authorOf: question.id }, message: "private-only-to-one" });
    expect(answer.details.outcomes).toEqual([expect.objectContaining({ kind: "worker", workerId: first.info.id,
      sessionId: ownerId, status: "submitted" })]);
    expect(JSON.stringify(rootLinks(await entries(owner)))).not.toContain("private-only-to-one");
    writeFileSync(heldToolFiles(`${first.marker}.after-question`).release, "release");
    await until(() => workerLinks(first.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one"),
      "private answer reaches the requesting worker");
    expect(workerLinks(sibling.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one")).toBe(false);
    expect(workerLinks(own.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one")).toBe(false);
    await until(() => JSON.parse(readFileSync(first.info.infoFile, "utf8")).status === "completed", "helper-only requester finishes its parent assignment");
    const original = JSON.parse(readFileSync(first.info.infoFile, "utf8"));
    const prefix = readFileSync(first.info.sessionFile, "utf8");
    const reopened = await tool(sender, "link_send", { to: { authorOf: question.id }, message: "completed-helper-only-followup" });
    expect(reopened.details.outcomes).toContainEqual(expect.objectContaining({ workerId: first.info.id, status: "submitted" }));
    let finalAnswer: any;
    await until(async () => {
      finalAnswer = rootLinks(await entries(sender)).find(entry => entry.content.includes(`Reply to ${reopened.details.messageId}`));
      return !!finalAnswer;
    }, "helper-only final answer returns automatically through the owner manager");
    // Root history stores minimal routing references, not answer/correlation
    // policy. The component bridge test checks answer:false on the wire.
    expect(finalAnswer.details.deliveries).toContainEqual(expect.objectContaining({
      fromWorker: expect.objectContaining({ workerId: first.info.id, ownerSessionId: ownerId }),
    }));
    await until(() => JSON.parse(readFileSync(first.info.infoFile, "utf8")).status === "completed", "helper-only followup completes");
    expect(readFileSync(first.info.sessionFile, "utf8").startsWith(prefix)).toBe(true);
    const after = JSON.parse(readFileSync(first.info.infoFile, "utf8"));
    expect(after.sessionId).toBe(original.sessionId);
    expect(after.peerEpisode.parentResult.finalResponse).toBe(original.finalResponse);
    expect(rootLinks(await entries(sender)).filter(entry => entry.content.includes(`Reply to ${reopened.details.messageId}`))).toHaveLength(1);
    expect(JSON.stringify(await entries(owner))).not.toContain("completed-helper-only-followup");
    expect(workerLinks(sibling.info.sessionFile).some(entry => entry.details.delivery.content === "completed-helper-only-followup")).toBe(false);
    const roster = await tool(sender, "link_list", {});
    expect(Object.keys(roster.details.sessionIds)).toHaveLength(2); // No worker joined as a root.
  } finally {
    for (const marker of markers) for (const path of [marker, `${marker}.after-question`]) writeFileSync(heldToolFiles(path).release, "release");
    for (const peer of peers.reverse()) await peer.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 45000);

sourceTest("configured pi-link workers expose selected tools and reply through both actual delivery paths", async () => {
  const { getAgentDir } = await import("@earendil-works/pi-coding-agent");
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "link-tools-"));
  const fixtureLink = await disposableLink(cwd);
  const settingsFile = join(getAgentDir(), "settings.json");
  mkdirSync(dirname(settingsFile), { recursive: true });
  writeFileSync(settingsFile, JSON.stringify({ extensions: [fixtureLink, heldExtension] }));
  const peers: Peer[] = [];
  const templates: string[] = [];
  const markers: string[] = [];
  try {
    const start = async (name: string, group: string, manager: boolean) => {
      const dir = join(cwd, name);
      mkdirSync(dir);
      const peer = sourceRpc(dir, join(dir, "session.jsonl"), false,
        manager ? [productionIndex, fixtureLink, heldExtension] : [fixtureLink, heldExtension],
        { PI_LINK_NAME: `${name}@${group}` });
      peers.push(peer);
      await peer.request({ type: "get_state" });
      return peer;
    };
    const owner = await start("owner", "native-managed", true);
    const author = await start("author", "native-managed", true);
    const endpoint = await start("endpoint", "native-tools", false);
    const ownerId = (await owner.request({ type: "get_state" })).sessionId;
    await until(async () => Object.keys((await tool(author, "link_list", {})).details.sessionIds ?? {}).length === 2,
      "owning roots connected");
    for (const [label, tools] of [
      ["ordinary", undefined], ["selected", "faux_hold,link_list,link_set_identity"], ["scout", "read,grep,find,ls"],
    ] as const) {
      const template = `link-tools-${randomUUID()}`;
      const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
      templates.push(templateFile);
      mkdirSync(dirname(templateFile), { recursive: true });
      writeFileSync(templateFile, `---\nname: ${template}\n${tools === undefined ? "" : `tools: ${tools}\n`}---\n`);
      const readOnly = label === "scout";
      const marker = join(cwd, label);
      markers.push(marker);
      await tool(owner, "spawn_agent", { task_name: label, agent_type: template,
        message: readOnly ? "Observe only" : `link-tool-access:${JSON.stringify({ path: marker, name: label, group: "native-tools" })}` });
      let info: any;
      await until(() => {
        const stored = readdirSync(getRunsDir(), { recursive: true }) as string[];
        info = stored.filter(name => name.endsWith(".info.json"))
          .map(name => JSON.parse(readFileSync(join(getRunsDir(), name), "utf8")))
          .find(info => info.taskName === label && info.parentSessionId === ownerId);
        return Boolean(info && (readOnly ? jsonl(providerCallsFile(info.sessionFile)).length : existsSync(heldToolFiles(marker).started)));
      }, `${label} native worker ready`);
      const actualTools = jsonl(providerCallsFile(info.sessionFile))[0].tools;
      expect(actualTools).toContain("link_send");
      if (readOnly) {
        expect(actualTools.sort()).toEqual(["find", "grep", "link_send", "ls", "peer_escalate", "peer_list", "peer_send", "read"]);
        continue;
      }
      for (const name of ["link_list", "link_set_identity"]) expect(actualTools).toContain(name);
      if (tools !== undefined) expect(actualTools.sort()).toEqual(["faux_hold", "link_list", "link_send", "link_set_identity", "peer_escalate", "peer_list", "peer_send"]);
      else for (const name of ["link_send", "link_compact"]) expect(actualTools).toContain(name);
      const identity = jsonl(info.sessionFile).find(entry => entry.message?.role === "toolResult" && entry.message.toolName === "link_set_identity");
      expect(identity.message.isError).not.toBe(true);
      expect(identity.message.details.preferred).toMatchObject({ name: label, group: "native-tools", nameOrigin: "agent", groupOrigin: "agent" });
      await until(async () => (await tool(endpoint, "link_list", {})).details.sessionIds?.[`${label}@native-tools`]
        === jsonl(info.sessionFile).find(entry => entry.type === "session").id, `${label} independently connected while held`);
      const direct = await tool(endpoint, "link_send", { to: `${label}@native-tools`, message: "native-access-request:direct" });
      const managed = await tool(author, "link_send", { to: { broadcast: true }, message: "native-access-request:managed", includeSubagents: true });
      expect(managed.details.outcomes).toContainEqual(expect.objectContaining({ kind: "worker", workerId: info.id, status: "submitted" }));
      // Keep the real tool held across the endpoint's 200ms batching window.
      // Native transcript admission and both resulting replies are checked below.
      await new Promise(done => setTimeout(done, 250));
      writeFileSync(heldToolFiles(marker).release, "release");
      await until(async () => {
        const directReplies = rootLinks(await entries(endpoint));
        const managedReplies = rootLinks(await entries(author));
        return directReplies.some(entry => entry.content.includes(`Reply to ${direct.details.messageId}`))
          && managedReplies.some(entry => entry.content.includes(`Reply to ${managed.details.messageId}`)
            && entry.details.deliveries.some(message => message.fromWorker?.workerId === info.id));
      }, `${label} replies through both transports`);
      const listing = jsonl(info.sessionFile).findLast(entry => entry.message?.role === "toolResult" && entry.message.toolName === "link_list");
      expect(listing.message.isError).not.toBe(true);
      expect(listing.message.details.sessionIds[`${label}@native-tools`]).toBe(jsonl(info.sessionFile).find(entry => entry.type === "session").id);
      expect(rootLinks(jsonl(info.sessionFile)).flatMap(entry => entry.details.deliveries).some(message => message.id === direct.details.messageId)).toBe(true);
      expect(workerLinks(info.sessionFile).some(entry => entry.details.delivery.id === managed.details.messageId)).toBe(true);
      const replies = jsonl(info.sessionFile).filter(entry => entry.message?.role === "toolResult" && entry.message.toolName === "link_send");
      expect(replies).toHaveLength(2);
      expect(replies.every(entry => !entry.message.isError && !entry.message.details.error)).toBe(true);
    }
  } finally {
    for (const marker of markers) writeFileSync(heldToolFiles(marker).release, "release");
    for (const peer of peers.reverse()) await peer.close();
    for (const template of templates) rmSync(template, { force: true });
    rmSync(settingsFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 45000);

sourceTest("parent-assigned task names become generated worker endpoints with inherited groups and collision handling", async () => {
  const { getAgentDir } = await import("@earendil-works/pi-coding-agent");
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "link-names-"));
  const fixtureLink = await disposableLink(cwd);
  const settingsFile = join(getAgentDir(), "settings.json");
  mkdirSync(dirname(settingsFile), { recursive: true });
  writeFileSync(settingsFile, JSON.stringify({ extensions: [fixtureLink, heldExtension] }));
  const template = `link-names-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(dirname(templateFile), { recursive: true });
  // The worker never assigns its own identity. Its only operation holds it alive
  // while the parent discovers the endpoint created by normal startup.
  writeFileSync(templateFile, `---\nname: ${template}\ntools: faux_hold,link_list\n---\n`);
  const peers: Peer[] = [];
  const markers: string[] = [];
  try {
    const start = async (directory: string, name: string) => {
      const dir = join(cwd, directory);
      mkdirSync(dir);
      const peer = sourceRpc(dir, join(dir, "session.jsonl"), false,
        [productionIndex, fixtureLink, heldExtension], { PI_LINK_NAME: name });
      peers.push(peer);
      await peer.request({ type: "get_state" });
      return peer;
    };
    // Vary the authoritative parent identity and spawn task, not a fixture copy
    // of the manager's child environment. Expected names come from the contract.
    for (const [parentName, group, taskName, preferredName, assignedName, collision] of [
      ["atlas", "qa-blue", "verify/edges", "t-atlas-verify/edges", "t-atlas-verify/edges", false],
      ["t-birch", "qa-green@nested", "scan_2", "t-birch-scan_2", "t-birch-scan_2", false],
      ["cedar", "qa-collision", "report", "t-cedar-report", "t-cedar-report-2", true],
    ] as const) {
      const owner = await start(parentName, `${parentName}@${group}`);
      const parentId = (await owner.request({ type: "get_state" })).sessionId;
      await until(async () => Boolean((await tool(owner, "link_list", {})).details.sessionIds?.[`${parentName}@${group}`]),
        `${parentName} joins its group`);
      if (collision) {
        const blocker = await start("collision-peer", `${preferredName}@${group}`);
        const blockerId = (await blocker.request({ type: "get_state" })).sessionId;
        await until(async () => (await tool(owner, "link_list", {})).details.sessionIds?.[`${preferredName}@${group}`] === blockerId,
          "existing endpoint occupies the worker preference before spawning");
      }
      const marker = join(cwd, `${parentName}-held`);
      markers.push(marker);
      await tool(owner, "spawn_agent", { task_name: taskName, agent_type: template, message: `hold-tool:${marker}` });
      await until(() => existsSync(heldToolFiles(marker).started), `${taskName} holds its native tool`);
      const stored = readdirSync(getRunsDir(), { recursive: true }) as string[];
      const info = stored.filter(name => name.endsWith(".info.json"))
        .map(name => JSON.parse(readFileSync(join(getRunsDir(), name), "utf8")))
        .find(info => info.parentSessionId === parentId && info.taskName === taskName);
      expect(info).toBeDefined();
      const nativeId = jsonl(info.sessionFile).find(entry => entry.type === "session").id;
      let roster: Record<string, string> = {};
      await until(async () => {
        roster = (await tool(owner, "link_list", {})).details.sessionIds ?? {};
        return Object.values(roster).includes(nativeId);
      }, `${taskName} joins as an independently discoverable endpoint`);
      expect(roster[`${assignedName}@${group}`]).toBe(nativeId);
      const identity = jsonl(info.sessionFile).findLast(entry => entry.type === "custom" && entry.customType === "link-identity")?.data;
      expect(identity).toMatchObject({ name: preferredName, group, nameOrigin: "generated", groupOrigin: "generated" });
      if (collision) expect(roster[`${preferredName}@${group}`]).not.toBe(nativeId);
    }
  } finally {
    for (const marker of markers) writeFileSync(heldToolFiles(marker).release, "release");
    for (const peer of peers.reverse()) await peer.close();
    rmSync(templateFile, { force: true });
    rmSync(settingsFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 45000);


for (const explicit of [false, true]) sourceTest(`native named author wakes the same completed child across independent owner groups with ${explicit ? "explicit" : "automatic"} private answer`, async () => {
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "native-wake-"));
  const fixtureLink = await disposableLink(cwd);
  const template = `native-wake-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(dirname(templateFile), { recursive: true });
  writeFileSync(templateFile, `---\nname: ${template}\nextensions: ${fixtureLink}, ${heldExtension}\n---\n`);
  const peers: Peer[] = [];
  const marker = join(cwd, "initial");
  try {
    const start = async (name: string) => {
      const dir = join(cwd, name.split("@")[0]); mkdirSync(dir, { recursive: true });
      const peer = sourceRpc(dir, join(dir, "session.jsonl"), false, [productionIndex, fixtureLink, heldExtension], { PI_LINK_NAME: name });
      peers.push(peer); await peer.request({ type: "get_state" }); return peer;
    };
    const owner = await start("wake-owner@owners");
    let requester = await start("wake-requester@workers");
    const parentId = (await owner.request({ type: "get_state" })).sessionId;
    await tool(owner, "spawn_agent", { task_name: "native-task", agent_type: template,
      message: `native-followup-task:${JSON.stringify({ name: "native-task", group: "workers", to: "wake-requester@workers", path: marker, explicit })}` });
    let info: any;
    await until(() => {
      info = (readdirSync(getRunsDir(), { recursive: true }) as string[]).filter(name => name.endsWith(".info.json"))
        .map(name => JSON.parse(readFileSync(join(getRunsDir(), name), "utf8")))
        .find(info => info.parentSessionId === parentId && info.taskName === "native-task");
      return Boolean(info && existsSync(heldToolFiles(marker).started));
    }, "native named sender connects while held");
    await until(async () => (await tool(requester, "link_list", {})).details.sessionIds?.["native-task@workers"] === info.sessionId,
      "native child joins requester group");
    writeFileSync(heldToolFiles(marker).release, "release");
    await until(() => JSON.parse(readFileSync(info.infoFile, "utf8")).status === "completed", "native sender completes");
    const before = JSON.parse(readFileSync(info.infoFile, "utf8"));
    const childPrefix = readFileSync(info.sessionFile, "utf8");
    let ping: any;
    await until(async () => {
      ping = rootLinks(await entries(requester)).flatMap(entry => entry.details.deliveries)
        .find(delivery => delivery.fromSessionId === info.sessionId);
      return Boolean(ping);
    }, "requester admits the original native ping");
    expect(ping.fromManagedWorker).toMatchObject({ ownerSessionId: parentId, workerId: info.id });
    if (!explicit) {
      const requesterId = (await requester.request({ type: "get_state" })).sessionId;
      await requester.close();
      requester = await start("wake-requester@workers");
      expect((await requester.request({ type: "get_state" })).sessionId).toBe(requesterId);
      await until(async () => (await tool(requester, "link_list", {})).details.sessionIds?.["wake-requester@workers"] === requesterId,
        "resumed requester reconnects with its durable admitted locator");
    }
    const ownerBefore = await entries(owner);
    const named = await tool(requester, "link_send", { to: "native-task@workers", message: "must not wake by offline name" });
    expect(named.details.error).toBeDefined();
    const reply = await tool(requester, "link_send", { to: { authorOf: ping.id }, message: "private-native-followup" });
    expect(reply.details.outcomes).toContainEqual(expect.objectContaining({ workerId: info.id, status: "submitted" }));
    await until(async () => rootLinks(await entries(requester)).some(entry => entry.content.includes(explicit ? "native-explicit-answer" : "native-automatic-answer")),
      "private final answer returns to requester");
    await until(() => JSON.parse(readFileSync(info.infoFile, "utf8")).status === "completed", "followup completes");
    const after = JSON.parse(readFileSync(info.infoFile, "utf8"));
    const answers = rootLinks(await entries(requester)).filter(entry =>
      entry.content.includes("native-explicit-answer") || entry.content.includes("native-automatic-answer"));
    expect(answers).toHaveLength(1);
    expect(answers[0].content).toContain(explicit ? "native-explicit-answer" : "native-automatic-answer");
    expect(after.sessionId).toBe(before.sessionId);
    expect(after.peerEpisode.parentResult.finalResponse).toBe("native-original-result");
    expect(jsonl(info.sessionFile).filter(entry => entry.type === "session")).toHaveLength(1);
    expect(readFileSync(info.sessionFile, "utf8").startsWith(childPrefix)).toBe(true);
    expect(workerLinks(info.sessionFile).filter(entry => entry.details.delivery.content === "private-native-followup")).toHaveLength(1);
    expect(JSON.stringify(await entries(owner))).not.toContain("private-native-followup");
    expect((await entries(owner)).filter((entry: any) => entry.customType === "pi-codex-subagent-completion").length)
      .toBe(ownerBefore.filter((entry: any) => entry.customType === "pi-codex-subagent-completion").length);
    const result = await tool(owner, "wait_agent", { targets: ["native-task"] });
    expect(JSON.stringify(result)).toContain("native-original-result");
    expect(JSON.stringify(result)).not.toContain("native-automatic-answer");
  } finally {
    writeFileSync(heldToolFiles(marker).release, "release");
    for (const peer of peers.reverse()) await peer.close();
    rmSync(templateFile, { force: true }); rmSync(cwd, { recursive: true, force: true });
  }
}, 45000);
