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

sourceTest("two real linked roots deliver to owned active children and return private worker replies without relaying through the owner model", async () => {
  const { SUBAGENT_DIR, getRunsDir } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "link-native-"));
  const reservation = createServer();
  await new Promise<void>(done => reservation.listen(0, "127.0.0.1", done));
  const port = (reservation.address() as { port: number }).port;
  await new Promise<void>(done => reservation.close(() => done()));
  const extensionDir = join(cwd, "link");
  mkdirSync(extensionDir);
  // The production extension has a fixed loopback port. Change only that value
  // in byte-verified disposable copies, never the authoritative checkout.
  for (const name of readdirSync(dirname(linkSource!)).filter(name => name.endsWith(".ts"))) {
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
  const template = `link-native-${randomUUID()}`;
  const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
  mkdirSync(dirname(templateFile), { recursive: true });
  // Deliberately load pi-link in the child template too: it must not create a
  // root connection or expose root tools in a managed worker.
  writeFileSync(templateFile, `---\nname: ${template}\ntools: faux_hold,link_send,link_set_identity,link_list,link_compact\nextensions: ${heldExtension}, ${fixtureLink}\n---\n`);
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
      expect(tools).toContain("link_reply");
      for (const forbidden of ["link_send", "link_set_identity", "link_list", "link_compact"]) expect(tools).not.toContain(forbidden);
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
    const answer = await tool(sender, "link_reply", { replyTo: question.id, message: "private-only-to-one" });
    expect(answer.details.outcomes).toEqual([expect.objectContaining({ kind: "worker", workerId: first.info.id,
      sessionId: ownerId, status: "submitted" })]);
    expect(JSON.stringify(rootLinks(await entries(owner)))).not.toContain("private-only-to-one");
    writeFileSync(heldToolFiles(`${first.marker}.after-question`).release, "release");
    await until(() => workerLinks(first.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one"),
      "private answer reaches the requesting worker");
    expect(workerLinks(sibling.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one")).toBe(false);
    expect(workerLinks(own.info.sessionFile).some(entry => entry.details.delivery.content === "private-only-to-one")).toBe(false);
    const roster = await tool(sender, "link_list", {});
    expect(Object.keys(roster.details.sessionIds)).toHaveLength(2); // No worker joined as a root.
  } finally {
    for (const marker of markers) for (const path of [marker, `${marker}.after-question`]) writeFileSync(heldToolFiles(path).release, "release");
    for (const peer of peers.reverse()) await peer.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 45000);
