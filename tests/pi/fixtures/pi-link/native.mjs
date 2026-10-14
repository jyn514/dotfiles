import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, realpath, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  createAgentSession, DefaultResourceLoader, discoverAndLoadExtensions,
  initTheme, ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider, fauxAssistantMessage, fauxToolCall, InMemoryCredentialStore } from "@earendil-works/pi-ai";
import { Box, Text } from "@earendil-works/pi-tui";

initTheme("dark", false);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
// This override is explicit fixture input for baseline experiments, never a checkout rewrite.
const sourcePath = process.env.PI_LINK_TEST_SOURCE || join(root, "tools/pi-link/index.ts");
const lockedRequire = createRequire(join(root, "tools/pi-link/package.json"));
const { WebSocket } = lockedRequire("ws");
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(predicate, label) {
  const deadline = Date.now() + 5000;
  while (!await predicate()) {
    assert.ok(Date.now() < deadline, `Timed out: ${label}`);
    await pause(10);
  }
}
function text(message) {
  return typeof message.content === "string" ? message.content :
    message.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
}
const links = (peer) => peer.session.messages.filter((message) => message.role === "custom" && message.customType === "link");
const providerText = (peer) => peer.requests.flatMap((request) => request.messages.map(text)).join("\n");
const theme = { fg: (_role, s) => s, bg: (_role, s) => s, bold: (s) => s };
const plainRows = (component, width) => component.render(width).map((row) => row.replace(/\x1b\[[0-9;]*m/g, "").trim());

async function network(t, names = ["hub", "alice", "bob"], { startup = false, disconnected = [] } = {}) {
  const directory = await mkdtemp(join(tmpdir(), "pi-link-native-"));
  const peers = [];
  const sockets = [];
  t.after(async () => {
    for (const socket of sockets) socket.terminate();
    // Stop clients before their hub, preventing election against a departing fixture.
    for (const peer of [...peers].reverse()) {
      await peer.session.abort();
      await peer.session.extensionRunner.emit({ type: "session_shutdown" });
      peer.session.dispose();
    }
    await rm(directory, { recursive: true, force: true });
  });
  const reservation = createServer();
  await new Promise((done) => reservation.listen(0, "127.0.0.1", done));
  const port = reservation.address().port;
  assert.notEqual(port, 9900);
  await new Promise((done) => reservation.close(done));
  const original = await readFile(sourcePath, "utf8");
  assert.equal((original.match(/const DEFAULT_PORT = 9900;/g) || []).length, 1,
    "fixture may substitute only the production DEFAULT_PORT");
  const fixturePath = join(directory, "extension/index.ts");
  await mkdir(dirname(fixturePath));
  await writeFile(fixturePath, original.replace("const DEFAULT_PORT = 9900;", `const DEFAULT_PORT = ${port};`));
  // Root SDK/typebox resolution plus an extension-local override of its own locked ws.
  await symlink(join(root, "node_modules"), join(directory, "node_modules"), "dir");
  await mkdir(join(directory, "extension/node_modules"));
  await symlink(dirname(lockedRequire.resolve("ws/package.json")), join(directory, "extension/node_modules/ws"), "dir");

  async function addPeer(name, restoredSessionManager) {
    const cwd = join(directory, name);
    const agentDir = join(cwd, "agent");
    await mkdir(agentDir, { recursive: true });
    const loaded = await discoverAndLoadExtensions([fixturePath], cwd, agentDir);
    assert.deepEqual(loaded.errors, [], "native extension discovery must load without errors");
    assert.equal(loaded.extensions.length, 1);
    assert.equal(loaded.extensions[0].path, fixturePath);
    const requests = [];
    const outgoing = [];
    const provider = fauxProvider({ provider: `pi-link-fixture-${name}`, api: "anthropic-messages" });
    const peer = { name, requests, outgoing, provider, hold: null };
    provider.setResponses(Array.from({ length: 100 }, () => async (context) => {
      requests.push(JSON.parse(JSON.stringify(context)));
      if (peer.hold) {
        const hold = peer.hold;
        peer.hold = null;
        hold.entered();
        return await hold.response;
      }
      const call = outgoing.shift();
      return call ? fauxAssistantMessage(fauxToolCall("link_send", call), { stopReason: "toolUse" }) :
        fauxAssistantMessage("offline fixture acknowledgement");
    }));
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false, keepRecentTokens: 1 }, retry: { enabled: false } });
    const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
      modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false });
    modelRuntime.registerNativeProvider(provider.provider);
    const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      extensionsOverride: () => loaded, systemPrompt: "Offline link regression fixture." });
    await loader.reload();
    let sessionManager = restoredSessionManager ?? SessionManager.create(cwd, join(cwd, "sessions"));
    if (disconnected.includes(name)) {
      sessionManager.appendCustomEntry("link-active", { active: false });
      // Pi buffers a new session until its first assistant message.
      sessionManager.appendMessage(fauxAssistantMessage("Fixture session saved."));
      sessionManager = SessionManager.open(sessionManager.getSessionFile());
      assert.ok(sessionManager.getBranch().some((entry) =>
        entry.type === "custom" && entry.customType === "link-active" && entry.data.active === false),
      "restored fixture must contain the saved disconnect");
    }
    const { session } = await createAgentSession({ cwd, agentDir, settingsManager, modelRuntime, resourceLoader: loader,
      sessionManager, model: provider.getModel(), tools: ["link_send", "link_list"] });
    peer.session = session;
    peer.sessionManager = sessionManager;
    peers.push(peer);
    const runner = session.extensionRunner;
    if (startup) session.setSessionName(name);
    else runner.setFlagValue("link-name", name);
    await session.bindExtensions({ onError: (error) => { peer.extensionError = error; } });
    // Ordinary routing tests connect explicitly; startup tests use no flag or command.
    if (!startup) await runner.getCommand("link-connect").handler("", runner.createCommandContext());
    await until(() => !peer.extensionError && runner.getToolDefinition("link_list"), "loaded tools");
    return peer;
  }
  for (const name of names) await addPeer(name);
  const roster = async () => peers[0].session.extensionRunner.getToolDefinition("link_list")
    .execute("roster", {}, undefined, undefined, peers[0].session.extensionRunner.createContext());
  const connectedNames = names.filter((name) => !disconnected.includes(name));
  // WebSocket registration is asynchronous; wait for the authoritative hub roster.
  for (let i = 0; i < 500; i++) {
    if ((await roster()).details.terminals?.length === connectedNames.length) break;
    assert.ok(i < 499, `all fixture peers must register: ${JSON.stringify({
      roster: (await roster()).details,
      peers: peers.map((peer) => ({ name: peer.name, flags: [...peer.session.extensionRunner.getFlagValues()],
        error: peer.extensionError, intent: peer.sessionManager.getBranch().filter((entry) =>
          entry.type === "custom" && entry.customType === "link-active") })),
    })}`);
    await pause(10);
  }
  for (const peer of peers) {
    assert.equal(peer.extensionError, undefined);
    const runner = peer.session.extensionRunner;
    const result = await runner.getToolDefinition("link_list").execute("roster", {}, undefined, undefined, runner.createContext());
    if (disconnected.includes(peer.name)) assert.equal(result.details.error, "not_connected");
    else assert.equal(result.details.role, peer === peers[0] ? "hub" : "client");
  }
  return { peers, port, sockets, addPeer };
}

async function send(peer, to, message, replyTo) {
  await until(() => !peer.session.isStreaming, "sender idle");
  const before = peer.session.messages.filter((entry) => entry.role === "toolResult" && entry.toolName === "link_send").length;
  peer.outgoing.push({ to, message, ...(replyTo === undefined ? {} : { replyTo }) });
  await peer.session.prompt("Perform the scripted link send.");
  const results = peer.session.messages.filter((entry) => entry.role === "toolResult" && entry.toolName === "link_send");
  assert.equal(results.length, before + 1, `each model-issued send must produce its own native tool result: ${JSON.stringify(peer.session.messages)}`);
  assert.equal(peer.outgoing.length, 0);
  return results.at(-1);
}
function messageId(result) {
  assert.equal(result.isError, false);
  assert.equal(result.details.error, undefined);
  assert.match(result.details.messageId, uuid, "ordinary sends expose a full UUID in details");
  assert.ok(text(result).includes(result.details.messageId), "full ID must be visible in tool-result text, not only details");
  return result.details.messageId;
}
function hasReceived(peer, body) { return links(peer).some((entry) => text(entry).includes(body)); }
async function received(peer, body) {
  await until(() => hasReceived(peer, body) && providerText(peer).includes(body), `receiver transcript and model: ${body}`);
  return links(peer).find((entry) => text(entry).includes(body));
}
function assertHeader(entry, from, id, replyTo) {
  const content = text(entry);
  assert.ok(content.includes(`From "${from}" (Message ID: ${id})`), content);
  if (replyTo) assert.ok(content.includes(`Reply to ${replyTo}`), content);
}

test("configured local package loads the fork and its skill through the bootstrap link", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "pi-link-package-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const agentDir = join(directory, ".pi/agent");
  await mkdir(agentDir, { recursive: true });
  const manifest = JSON.parse(await readFile(join(root, "install.conf.json"), "utf8"));
  const links = manifest.find((entry) => entry.link).link;
  const mapping = Object.entries(links).find(([, source]) => source === "tools/pi-link");
  assert.ok(mapping, "bootstrap must install the local fork, not upstream npm pi-link");
  const config = join(directory, "links.json");
  await writeFile(config, JSON.stringify([
    ...manifest.filter((entry) => entry.defaults), { link: Object.fromEntries([mapping]) },
  ]));
  execFileSync(join(root, "vendor/dotbot/bin/dotbot"), ["-d", root, "-c", config], {
    env: { ...process.env, HOME: directory },
  });
  const settingsFile = join(agentDir, "settings.json");
  execFileSync("cp", [join(root, "config/pi-agent/settings.json"), settingsFile]);
  execFileSync("cmp", [join(root, "config/pi-agent/settings.json"), settingsFile]);
  const settingsManager = SettingsManager.create(directory, agentDir);
  // Keep the configured local sources. Remote packages and the separate extension
  // bundle are outside this regression and must not load personal state or use network.
  settingsManager.setPackages(settingsManager.getPackages().filter((entry) =>
    (typeof entry === "string" ? entry : entry.source).startsWith("./")));
  settingsManager.setExtensionPaths([]);
  const loader = new DefaultResourceLoader({ cwd: directory, agentDir, settingsManager,
    noPromptTemplates: true, noThemes: true, noContextFiles: true });
  await loader.reload();
  const loaded = loader.getExtensions();
  assert.deepEqual(loaded.errors, []);
  const fork = loaded.extensions.find((extension) => extension.tools.has("link_send"));
  assert.ok(fork, "startup settings must discover the fork through the installed local package");
  assert.equal(await realpath(fork.path), await realpath(join(root, "tools/pi-link/index.ts")));
  assert.ok(fork.tools.get("link_send").definition.parameters.properties.replyTo,
    "the configured package must expose the fork's reply references");
  const { skills, diagnostics } = loader.getSkills();
  assert.deepEqual(diagnostics, []);
  const skill = skills.find((entry) => entry.name === "pi-link-tools");
  assert.ok(skill, "loading the package must also discover its bundled skill");
  assert.equal(await realpath(skill.filePath), await realpath(join(root, "tools/pi-link/skills/pi-link-tools/SKILL.md")));

  // Run the image's real install script with only its fixed image paths relocated.
  // A relative source must resolve from agentDir, not the neutral build workspace.
  const workspace = join(directory, "workspace");
  await mkdir(workspace);
  const cacheSource = process.env.PI_LINK_TEST_CACHE_SOURCE || join(root, "tools/codex-sandbox/image/cache-pi-extensions.mjs");
  const cacheScript = join(directory, "cache-pi-extensions.mjs");
  execFileSync("cp", [cacheSource, cacheScript]);
  execFileSync("cmp", [cacheSource, cacheScript]);
  let script = await readFile(cacheScript, "utf8");
  for (const [original, relocated] of [
    ['"/opt/agent-pi/src/packages/coding-agent/dist/bundle/index.js"', JSON.stringify(import.meta.resolve("@earendil-works/pi-coding-agent"))],
    ['const cwd = "/workspace";', `const cwd = ${JSON.stringify(workspace)};`],
    ['const agentDir = "/home/codex/.pi/agent";', `const agentDir = ${JSON.stringify(agentDir)};`],
  ]) {
    assert.equal(script.split(original).length, 2, `image fixture path must be unique: ${original}`);
    script = script.replace(original, relocated);
  }
  await writeFile(cacheScript, script);
  execFileSync(process.execPath, [cacheScript, "install"], { cwd: workspace });
  assert.ok(mapping[0].startsWith("$HOME/"));
  const installedLink = join(directory, mapping[0].slice("$HOME/".length));
  await unlink(installedLink);
  const missing = spawnSync(process.execPath, [cacheScript, "install"], { cwd: workspace, encoding: "utf8" });
  assert.notEqual(missing.status, 0, "missing local packages must fail instead of silently warming an incomplete cache");
  assert.ok(missing.stderr.includes(`Path does not exist: ${installedLink}`), missing.stderr);
});

test("startup connects without flags and preserves a restored session's opt-out", async (t) => {
  const { peers: [hub, alice, offline] } = await network(t, ["hub", "alice", "offline"], {
    startup: true, disconnected: ["offline"],
  });
  const id = messageId(await send(hub, "alice", "automatic startup delivery"));
  assertHeader(await received(alice, "automatic startup delivery"), "hub", id);
  const runner = offline.session.extensionRunner;
  await runner.getCommand("link-connect").handler("", runner.createCommandContext());
  await until(async () => {
    const roster = await runner.getToolDefinition("link_list")
      .execute("roster", {}, undefined, undefined, runner.createContext());
    return roster.details.terminals?.includes("hub");
  }, "explicit reconnect receives the hub roster");
  const reconnected = messageId(await send(offline, "hub", "explicitly reconnected"));
  assertHeader(await received(hub, "explicitly reconnected"), "offline", reconnected);
});

test("Pi session IDs identify native forks and survive link renames without retaining departed IDs", async (t) => {
  const { peers: [parent, observer], addPeer } = await network(t, ["parent", "observer"], { startup: true });
  messageId(await send(parent, "observer", "persist the parent before forking"));
  await received(observer, "persist the parent before forking");
  const selected = parent.sessionManager.getBranch().find((entry) =>
    entry.type === "message" && entry.message.role === "user");
  const forkedManager = SessionManager.open(parent.sessionManager.getSessionFile());
  assert.ok(forkedManager.createBranchedSession(selected.id));
  const child = await addPeer("child", forkedManager);
  assert.notEqual(child.sessionManager.getSessionId(), parent.sessionManager.getSessionId());
  const peers = [parent, observer, child];
  const roster = async (peer) => {
    const runner = peer.session.extensionRunner;
    return runner.getToolDefinition("link_list").execute("roster", {}, undefined, undefined, runner.createContext());
  };
  async function expectSessionIds(expected) {
    for (const peer of peers) {
      await until(async () => {
        const result = await roster(peer);
        return JSON.stringify(result.details.terminals?.slice().sort()) === JSON.stringify(Object.keys(expected).sort());
      }, "session ID roster membership");
      const result = await roster(peer);
      assert.deepEqual({ ...result.details.sessionIds }, expected);
      for (const id of Object.values(expected)) assert.ok(text(result).includes(id), "full Pi IDs reach the model");
      const definition = peer.session.extensionRunner.getToolDefinition("link_list");
      const rendered = definition.renderResult(result, { expanded: true }, theme);
      const visible = plainRows(rendered, 140).join("\n");
      for (const id of Object.values(expected)) assert.ok(visible.includes(id), "full Pi IDs reach the transcript");
    }
  }
  const parentId = parent.sessionManager.getSessionId();
  const observerId = observer.sessionManager.getSessionId();
  const childId = child.sessionManager.getSessionId();
  await expectSessionIds({ parent: parentId, observer: observerId, child: childId });
  const parentRunner = parent.session.extensionRunner;
  await parentRunner.getCommand("link-name").handler("parent-renamed", parentRunner.createCommandContext());
  const observerRunner = observer.session.extensionRunner;
  await observerRunner.getCommand("link-name").handler("observer-renamed", observerRunner.createCommandContext());
  await expectSessionIds({ "parent-renamed": parentId, "observer-renamed": observerId, child: childId });
  await child.session.extensionRunner.getCommand("link-disconnect")
    .handler("", child.session.extensionRunner.createCommandContext());
  peers.pop();
  await expectSessionIds({ "parent-renamed": parentId, "observer-renamed": observerId });
});

test("native sessions preserve full ordinary IDs and reply references in all WebSocket routing directions", async (t) => {
  const { peers: [hub, alice, bob] } = await network(t);
  const ids = [];
  for (const [sender, receiver] of [[hub, alice], [alice, hub], [alice, bob]]) {
    const body = `ordinary ${sender.name} -> ${receiver.name}`;
    const id = messageId(await send(sender, receiver.name, body));
    ids.push(id);
    assertHeader(await received(receiver, body), sender.name, id);
    assert.ok(providerText(receiver).includes(id), "receiving model sees the full message ID");
    assert.ok(providerText(sender).includes(id), "sending model sees its tool-result ID");
    const replyBody = `reply ${receiver.name} -> ${sender.name}`;
    const replyId = messageId(await send(receiver, sender.name, replyBody, id));
    ids.push(replyId);
    assertHeader(await received(sender, replyBody), receiver.name, replyId, id);
    assert.ok(providerText(sender).includes(replyId), "receiving model sees the reply's own full ID");
    assert.ok(providerText(sender).includes(`Reply to ${id}`), "receiving model sees the entire reply reference");
  }
  assert.equal(new Set(ids).size, ids.length, "distinct ordinary and reply occurrences must not share IDs");
  const schema = alice.session.extensionRunner.getToolDefinition("link_send").parameters;
  assert.ok(schema.required.includes("to"));
  assert.ok(schema.properties.replyTo, "replyTo is part of the loaded public tool schema");
  assert.ok(!schema.required.includes("replyTo"), "ordinary sends remain valid");
  // No outstanding ask/pending request exists; a caller may reference any prior full ID.
  const arbitrary = "487fe623-5eab-489b-a5c1-e6a492ea29f2";
  const freeId = messageId(await send(bob, "hub", "reference without pending ask", arbitrary));
  assertHeader(await received(hub, "reference without pending ask"), "bob", freeId, arbitrary);
});

test("two replies in one held inbox batch retain distinct references across real manual compaction", async (t) => {
  const { peers: [hub, alice, bob] } = await network(t);
  const first = messageId(await send(hub, "alice", "first conversation"));
  const second = messageId(await send(hub, "bob", "second conversation"));
  await received(alice, "first conversation");
  await received(bob, "second conversation");
  await until(() => !hub.session.isStreaming, "hub ready to compact");
  let enter;
  let release;
  const entered = new Promise((done) => { enter = done; });
  const response = new Promise((done) => { release = done; });
  hub.hold = { entered: enter, response };
  const compaction = hub.session.compact("Summarize the fixture conversation.");
  t.after(() => release(fauxAssistantMessage("Fixture summary.")));
  await Promise.race([entered, pause(5000).then(() => { throw new Error("manual compaction did not reach summarizer"); })]);
  const before = links(hub).length;
  const reply1 = messageId(await send(alice, "hub", "held reply one", first));
  const reply2 = messageId(await send(bob, "hub", "held reply two", second));
  await pause(350);
  assert.equal(links(hub).length, before, "manual compaction must hold delivery, not start a model turn");
  assert.ok(!providerText(hub).includes("held reply one"));
  release(fauxAssistantMessage("Fixture conversation summary."));
  await compaction;
  const batch = await received(hub, "held reply one");
  await received(hub, "held reply two");
  assert.equal(batch.details.count, 2, "both replies release together as separate messages in one batch");
  assertHeader(batch, "alice", reply1, first);
  assertHeader(batch, "bob", reply2, second);
  const content = text(batch);
  assert.equal(content.split(`Reply to ${first}`).length - 1, 1);
  assert.equal(content.split(`Reply to ${second}`).length - 1, 1);
  assert.ok(content.indexOf(`Reply to ${first}`) < content.indexOf("held reply one"));
  assert.ok(content.indexOf("held reply one") < content.indexOf(`Reply to ${second}`));
});

test("legacy wire frames and historic entries render with genuine Text/Box at narrow and wide widths", async (t) => {
  const { peers: [hub, alice], port, sockets } = await network(t, ["hub", "alice"]);
  const socket = new WebSocket(`ws://127.0.0.1:${port}`);
  sockets.push(socket);
  await new Promise((done, reject) => { socket.once("open", done); socket.once("error", reject); });
  const welcome = new Promise((done) => socket.once("message", (raw) => done(JSON.parse(raw.toString()))));
  socket.send(JSON.stringify({ type: "register", name: "legacy" }));
  assert.equal((await welcome).type, "welcome");
  await until(async () => {
    const runner = hub.session.extensionRunner;
    const roster = await runner.getToolDefinition("link_list").execute("roster", {}, undefined, undefined, runner.createContext());
    assert.equal(roster.details.sessionIds.legacy, undefined, "legacy peers have unknown IDs, never invented ones");
    return roster.details.terminals.includes("legacy");
  }, "legacy peer registration");
  for (const receiver of [hub, alice]) {
    const body = `legacy wire to ${receiver.name}`;
    socket.send(JSON.stringify({ type: "chat", from: "spoof", to: receiver.name, content: body }));
    const entry = await received(receiver, body);
    assert.ok(text(entry).includes(`From "legacy":\n${body}`), "old ID-less wire frame remains accepted under authoritative sender name");
    assert.ok(!text(entry).includes("Message ID:"));
  }
  const longBody = Array.from({ length: 12 }, (_, i) => `row ${i}: ${"rendered text ".repeat(10)}`).join("\n");
  const replyTo = "292b8f3c-834a-4b94-ac77-62cd2b4ceef1";
  const id = messageId(await send(hub, "alice", longBody, replyTo));
  const incoming = await received(alice, "row 11:");
  await until(() => !alice.session.isStreaming, "receiver persisted its turn");
  const restored = SessionManager.open(alice.sessionManager.getSessionFile());
  const restoredEntry = restored.buildSessionContext().messages.find((entry) =>
    entry.role === "custom" && entry.customType === "link" && text(entry).includes("row 11:"));
  assert.ok(restoredEntry, "native session restore retains the incoming custom message");
  assert.equal(text(restoredEntry), text(incoming), "restore preserves full ID/reply annotations without reinterpretation");
  assert.ok(text(restoredEntry).includes(`Reply to ${replyTo}`));
  const render = alice.session.extensionRunner.getMessageRenderer("link");
  const historic = { customType: "link", content: 'From "historic":\n' + longBody, details: { batched: true, count: 1 }, display: true };
  for (const entry of [incoming, restoredEntry, historic]) {
    for (const width of [38, 140]) {
      const expanded = render(entry, { expanded: true, outputPad: 2 }, theme);
      const collapsed = render(entry, { expanded: false, outputPad: 2 }, theme);
      // Jiti's loaded CJS class and this ESM import have different identities;
      // compare rendered output rather than implementation class identity.
      // Remove Box's top/bottom padding, but keep blank content rows: those
      // consume the same six-row budget as wrapped text.
      const all = plainRows(expanded, width).slice(1, -1);
      const preview = plainRows(collapsed, width).slice(1, -1);
      assert.deepEqual(preview.slice(0, 6), all.slice(0, 6), "six visual rows, including actual wrapping, are retained");
      assert.ok(preview.slice(6).join(" ").includes("to expand"));
      assert.ok(!preview.join(" ").includes("row 11:"));
      assert.ok(all.join(" ").includes("row 11:"));
      if (entry !== historic) {
        const joined = all.join("").replace(/\s/g, "");
        assert.ok(joined.includes(id), "expanded narrow/wide view retains every UUID character");
        assert.ok(joined.includes(`Replyto${replyTo}`), "expanded reply annotation survives wrapping");
        if (width === 140) assert.ok(preview.join(" ").includes(`Reply to ${replyTo}`), "reply annotation within six visual rows is not hidden");
      }
      const content = new Text(theme.fg("accent", "⚡ [link] ") + theme.fg("text", String(entry.content)), 0, 0);
      const expectedBox = new Box(2, 1, (s) => theme.bg("customMessageBg", s));
      expectedBox.addChild(content);
      assert.deepEqual(plainRows(expanded, width), plainRows(expectedBox, width), "loaded Box expansion matches genuine native Text/Box wrapping");
    }
  }
});

test("failed model-issued sends expose errors and never claim success or invent an ID", async (t) => {
  const { peers: [hub] } = await network(t, ["hub"]);
  for (const to of ["missing", "hub"]) {
    const result = await send(hub, to, "must not arrive", "b24f2c42-bc77-47fd-a574-a1bbb0aaf375");
    assert.ok(result.details.error);
    assert.equal(result.details.messageId, undefined);
    assert.ok(!/^Sent\b/.test(text(result)));
  }
  const invalid = await send(hub, undefined, "replyTo cannot replace to", "b24f2c42-bc77-47fd-a574-a1bbb0aaf375");
  assert.ok(invalid.isError || invalid.details?.error, "replyTo without a destination must not succeed");
  assert.equal(invalid.details?.messageId, undefined);
  assert.ok(!/^Sent\b/.test(text(invalid)));
  const runner = hub.session.extensionRunner;
  await runner.getCommand("link-disconnect").handler("", runner.createCommandContext());
  const result = await send(hub, "missing", "disconnected send");
  assert.equal(result.details.error, "not_connected");
  assert.equal(result.details.messageId, undefined);
  assert.ok(!/^Sent\b/.test(text(result)));
  assert.equal(links(hub).length, 0);
});
