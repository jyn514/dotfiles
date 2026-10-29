import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  createEventBus, createAgentSession, DefaultResourceLoader, discoverAndLoadExtensions,
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

async function network(t, names = ["hub", "alice", "bob"], { startup = false, disconnected = [], identities = {} } = {}) {
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
  const fixturePath = join(directory, "extension/index.ts");
  await mkdir(dirname(fixturePath));
  // Keep source overrides usable for historical single-file baselines, while
  // loading sibling production modules through the same native loader as index.
  for (const name of await readdir(dirname(sourcePath))) {
    if (!name.endsWith(".ts") && !name.endsWith(".mjs")) continue;
    const source = join(dirname(sourcePath), name);
    const copy = join(dirname(fixturePath), name);
    execFileSync("cp", [source, copy]);
    execFileSync("cmp", [source, copy]);
  }
  // Consume the byte-verified index copy, including explicit baseline inputs.
  execFileSync("cp", [sourcePath, fixturePath]);
  execFileSync("cmp", [sourcePath, fixturePath]);
  const original = await readFile(fixturePath, "utf8");
  assert.equal((original.match(/const DEFAULT_PORT = 9900;/g) || []).length, 1,
    "fixture may substitute only the production DEFAULT_PORT");
  await writeFile(fixturePath, original.replace("const DEFAULT_PORT = 9900;", `const DEFAULT_PORT = ${port};`));
  // Root SDK/typebox resolution plus an extension-local override of its own locked ws.
  await symlink(join(root, "node_modules"), join(directory, "node_modules"), "dir");
  await mkdir(join(directory, "extension/node_modules"));
  await symlink(dirname(lockedRequire.resolve("ws/package.json")), join(directory, "extension/node_modules/ws"), "dir");

  async function addPeer(name, restoredSessionManager, options = identities[name] ?? {}) {
    const cwd = join(directory, name);
    const agentDir = join(cwd, "agent");
    await mkdir(agentDir, { recursive: true });
    const eventBus = createEventBus();
    const loaded = await discoverAndLoadExtensions([fixturePath], cwd, agentDir, eventBus);
    assert.deepEqual(loaded.errors, [], "native extension discovery must load without errors");
    assert.equal(loaded.extensions.length, 1);
    assert.equal(loaded.extensions[0].path, fixturePath);
    const requests = [];
    const outgoing = [];
    const provider = fauxProvider({ provider: `pi-link-fixture-${name}`, api: "anthropic-messages" });
    const peer = { name, requests, outgoing, provider, eventBus, hold: null };
    provider.setResponses(Array.from({ length: 100 }, () => async (context) => {
      requests.push(JSON.parse(JSON.stringify(context)));
      if (peer.hold) {
        const hold = peer.hold;
        peer.hold = null;
        hold.entered();
        return await hold.response;
      }
      const call = outgoing.shift();
      return call ? fauxAssistantMessage(fauxToolCall(call.tool, call.args), { stopReason: "toolUse" }) :
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
    if (options.legacyName) {
      sessionManager.appendCustomEntry("link-name", { name: options.legacyName });
      sessionManager.appendMessage(fauxAssistantMessage("Fixture legacy identity saved."));
      sessionManager = SessionManager.open(sessionManager.getSessionFile());
    }
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
      sessionManager, model: provider.getModel(), tools: ["link_send", "link_list", "link_compact", "link_set_identity", "link_reply"] });
    peer.session = session;
    peer.sessionManager = sessionManager;
    peers.push(peer);
    const runner = session.extensionRunner;
    if (!options.generated && !options.legacyName && !options.saved) {
      if (startup) session.setSessionName(name);
      else runner.setFlagValue("link-name", name);
    }
    await session.bindExtensions({ onError: (error) => { peer.extensionError = error; } });
    // Ordinary routing tests connect explicitly; startup tests use no flag or command.
    if (!startup) await runner.getCommand("link-connect").handler("", runner.createCommandContext());
    await until(() => !peer.extensionError && runner.getToolDefinition("link_list"), "loaded tools");
    return peer;
  }
  for (const name of names) await addPeer(name);
  const connected = peers.filter((peer) => !disconnected.includes(peer.name));
  const assigned = new Map();
  // Each native registration must complete, even when group isolation deliberately
  // prevents the hub's public roster from listing peers in the other group.
  for (const peer of peers) {
    await until(async () => {
      assert.equal(peer.extensionError, undefined);
      const result = await roster(peer);
      if (disconnected.includes(peer.name)) return result.error === "not_connected";
      const ownName = Object.keys(result.sessionIds ?? {}).find((name) =>
        result.sessionIds[name] === peer.sessionManager.getSessionId());
      if (ownName) assigned.set(peer, ownName);
      return ownName && result.role === (peer === peers[0] ? "hub" : "client");
    }, `native registration for ${peer.name}`);
  }
  const group = (name) => name.includes("@") ? name.slice(name.indexOf("@") + 1) : "";
  for (const peer of connected) {
    const expected = connected.filter((other) => group(assigned.get(other)) === group(assigned.get(peer)))
      .map((other) => other.sessionManager.getSessionId()).sort();
    await until(async () => {
      const result = await roster(peer);
      return JSON.stringify(Object.values(result.sessionIds ?? {}).sort()) === JSON.stringify(expected);
    }, `same-group roster for ${peer.name}`);
  }
  return { peers, port, sockets, addPeer };
}

async function tool(peer, name, args) {
  await until(() => !peer.session.isStreaming, "tool caller idle");
  const results = () => peer.session.messages.filter((entry) => entry.role === "toolResult" && entry.toolName === name);
  const before = results().length;
  peer.outgoing.push({ tool: name, args });
  await peer.session.prompt(`Perform the scripted ${name} call.`);
  assert.equal(results().length, before + 1, `each model-issued ${name} must produce its own native tool result`);
  assert.equal(peer.outgoing.length, 0);
  return results().at(-1);
}
async function send(peer, to, message, replyTo) {
  const result = await tool(peer, "link_send", { to, message, ...(replyTo === undefined ? {} : { replyTo }) });
  if (typeof to === "string" && !result.isError && !result.details?.error) {
    assert.match(result.details.messageId, uuid, "ordinary direct sends retain their original messageId detail");
  }
  return result;
}
async function command(peer, name, args = "") {
  await until(() => !peer.session.isStreaming, "command caller idle");
  const runner = peer.session.extensionRunner;
  await runner.getCommand(name).handler(args, runner.createCommandContext());
}
async function roster(peer) {
  const runner = peer.session.extensionRunner;
  return (await runner.getToolDefinition("link_list").execute("roster", {}, undefined, undefined, runner.createContext())).details;
}
async function named(peer, expected) {
  await until(async () => (await roster(peer)).terminals?.includes(expected), `roster includes ${expected}`);
}
function refused(result) {
  const outcomes = result.details?.outcomes;
  const failedReceipt = Array.isArray(outcomes) && outcomes.length > 0 &&
    outcomes.every((outcome) => ["failed", "unsupported", "skipped"].includes(outcome.status));
  assert.ok(result.isError || result.details?.error || failedReceipt,
    `operation must explicitly fail: ${JSON.stringify(result)}`);
  if (Array.isArray(outcomes)) {
    assert.ok(!outcomes.some((outcome) => outcome.status === "submitted"),
      "a rejected routing call must not report any accepted copy");
  } else {
    assert.equal(result.details?.messageId, undefined);
  }
}
async function noDelivery(peers, body) {
  // Observe past the real inbox batching window, including the receiver's model.
  await pause(350);
  for (const peer of peers) {
    assert.ok(!hasReceived(peer, body), `${peer.name} must not receive ${body}`);
    const deliveries = peer.requests.flatMap((request) => request.messages)
      .filter((message) => message.role === "user" && text(message).startsWith("[Link:"));
    assert.ok(!deliveries.some((message) => text(message).includes(body)),
      `${peer.name}'s model must not receive a link delivery of ${body}`);
  }
}
function messageId(result) {
  assert.equal(result.isError, false);
  assert.equal(result.details.error, undefined);
  const id = result.details.messageId ?? result.details.id;
  assert.match(id, uuid, "successful sends and replies expose a full UUID in details");
  assert.ok(text(result).includes(id), "full ID must be visible in tool-result text, not only details");
  return id;
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

test("image cache inputs load pi-link with its sibling modules", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "pi-link-image-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const imageRoot = join(directory, "image");
  const agentDir = join(imageRoot, "home/codex/.pi/agent");
  const extensionDir = join(agentDir, "pi-link");
  await mkdir(extensionDir, { recursive: true });
  // Match the Dockerfile's explicit local source copies, not the repository tree:
  // loading from a bootstrap symlink hides modules omitted from the image.
  const dockerfile = await readFile(join(root, "tools/codex-sandbox/image/Dockerfile"), "utf8");
  for (const line of dockerfile.split("\n")) {
    const fields = line.trim().split(/\s+/);
    if (fields[0] !== "COPY" || fields[1].startsWith("--")) continue;
    const destination = fields.at(-1);
    if (!destination.startsWith("/home/codex/.pi/agent/pi-link/")) continue;
    for (const source of fields.slice(1, -1)) {
      if (!source.endsWith(".ts") && !source.endsWith(".mjs")) continue;
      execFileSync("cp", [join(root, source), join(imageRoot, destination)]);
    }
  }
  await symlink(join(root, "node_modules"), join(directory, "node_modules"), "dir");
  await mkdir(join(extensionDir, "node_modules"));
  await symlink(dirname(lockedRequire.resolve("ws/package.json")), join(extensionDir, "node_modules/ws"), "dir");
  const loaded = await discoverAndLoadExtensions([join(extensionDir, "index.ts")], directory, agentDir);
  assert.deepEqual(loaded.errors, [], "the image must copy every module needed by the native Pi loader");
  assert.equal(loaded.extensions.length, 1);
  assert.ok(loaded.extensions[0].tools.has("link_set_identity"));
  assert.ok(loaded.extensions[0].tools.has("link_reply"));
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
  // A fork now inherits saved identity provenance. Give this native fork its
  // test identity through the real naming command, not a lower-priority fallback.
  await command(child, "link-name", "child");
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
  let enterTimer;
  try {
    await Promise.race([entered, new Promise((_, reject) => {
      enterTimer = setTimeout(() => reject(new Error("manual compaction did not reach summarizer")), 5000);
    })]);
  } finally {
    clearTimeout(enterTimer);
  }
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

// These cases exercise the public tools through model-issued native calls. A
// refactor may change receipt layout or transport internals without changing the
// authoritative delivery, ownership, or connection-state observations below.
test("broadcast selects only other roots in the current group and preserves one marked UUID", async (t) => {
  const { peers: [hub, alice, bob, outsider] } = await network(t,
    ["hub@review", "alice@review", "bob@review", "outsider@other"]);
  for (const sender of [hub, alice]) {
    const body = `group correction from ${sender.name}`;
    const result = await tool(sender, "link_send", { to: { broadcast: true }, message: body });
    const id = messageId(result);
    const recipients = [hub, alice, bob].filter((peer) => peer !== sender);
    for (const recipient of recipients) {
      const entry = await received(recipient, body);
      assert.ok(text(entry).includes(id), "all copies expose the same full UUID");
      assert.ok(text(entry).includes(sender.name), "broadcast retains original sender attribution");
      assert.match(text(entry), /broadcast/i, "model can distinguish a broadcast from a private assignment");
    }
    await noDelivery([sender, outsider], body);
  }
  const workers = await tool(alice, "link_send", {
    to: { broadcast: true }, message: "root correction with unavailable workers", includeSubagents: true,
  });
  messageId(workers);
  await received(hub, "root correction with unavailable workers");
  await received(bob, "root correction with unavailable workers");
  assert.match(text(workers), /unsupported|unavailable/i, "missing manager integration must not claim worker success");
  for (const owner of [hub, alice, bob]) {
    assert.ok(workers.details.outcomes.some((outcome) =>
      outcome.sessionId === owner.sessionManager.getSessionId() &&
      ["workers", "worker"].includes(outcome.kind) && outcome.status === "unsupported"),
    "receipt must explicitly report unavailable worker delivery for every owner, including sender");
  }
  await noDelivery([alice, outsider], "root correction with unavailable workers");
});

test("all and star remain ordinary direct names and invalid broadcast forms never fan out", async (t) => {
  const { peers: [hub, all, star] } = await network(t, ["hub", "all", "*"]);
  for (const [target, sibling] of [[all, star], [star, all]]) {
    const body = `direct literal ${target.name}`;
    const id = messageId(await send(hub, target.name, body));
    assertHeader(await received(target, body), "hub", id);
    await noDelivery([hub, sibling], body);
  }
  for (const args of [
    { to: "all", includeSubagents: true },
    { to: { broadcast: false } },
    { to: { broadcast: true, extra: true } },
  ]) {
    const body = `invalid routing ${JSON.stringify(args)}`;
    refused(await tool(hub, "link_send", { ...args, message: body }));
    await noDelivery([hub, all, star], body);
  }
});

test("reply-only resolves received direct and broadcast references into chained private conversations", async (t) => {
  const { peers: [hub, alice, bob] } = await network(t);
  for (const broadcast of [false, true]) {
    const correction = `correction ${broadcast ? "broadcast" : "direct"}`;
    const original = messageId(await send(hub, broadcast ? { broadcast: true } : "alice", correction));
    await received(alice, correction);
    if (broadcast) await received(bob, correction);
    const question = `private question ${broadcast}`;
    const questionId = messageId(await tool(alice, "link_reply", { replyTo: original, message: question }));
    assertHeader(await received(hub, question), "alice", questionId, original);
    const answer = `private answer ${broadcast}`;
    const answerId = messageId(await tool(hub, "link_reply", { replyTo: questionId, message: answer }));
    assertHeader(await received(alice, answer), "hub", answerId, questionId);
    const continuation = `private continuation ${broadcast}`;
    const continuationId = messageId(await tool(alice, "link_reply", { replyTo: answerId, message: continuation }));
    assertHeader(await received(hub, continuation), "alice", continuationId, answerId);
    await noDelivery([bob], question);
    await noDelivery([bob], answer);
    await noDelivery([bob], continuation);
    if (!broadcast) {
      refused(await tool(bob, "link_reply", { replyTo: original, message: "guessed but never received" }));
      await noDelivery([hub, alice], "guessed but never received");
    }
  }
  refused(await tool(alice, "link_reply", {
    replyTo: "a57b57aa-81f1-43b4-99ad-825c4517d9f1", message: "unknown reference",
  }));
  await noDelivery([hub, bob], "unknown reference");
  const schema = alice.session.extensionRunner.getToolDefinition("link_reply").parameters;
  assert.deepEqual([...schema.required].sort(), ["message", "replyTo"]);
  assert.deepEqual(Object.keys(schema.properties).sort(), ["message", "replyTo"]);
});

test("reply routing follows original Pi identity across rename and name reuse, but not a group move", async (t) => {
  const { peers: [hub, alice, sibling], addPeer } = await network(t, ["origin@review", "alice@review", "sibling@review"], {
    identities: { "origin@review": { generated: true } },
  });
  await tool(hub, "link_set_identity", { name: "origin", group: "review" });
  await named(alice, "origin@review");
  const originalSessionId = hub.sessionManager.getSessionId();
  const original = messageId(await send(hub, "alice@review", "remember original author"));
  await received(alice, "remember original author");
  await tool(hub, "link_set_identity", { name: "renamed" });
  await named(alice, "renamed@review");
  const replacement = await addPeer("origin@review", undefined, {});
  await named(alice, "origin@review");
  assert.equal((await roster(alice)).sessionIds["renamed@review"], originalSessionId);
  const reply = messageId(await tool(alice, "link_reply", { replyTo: original, message: "only the original author" }));
  assertHeader(await received(hub, "only the original author"), "alice@review", reply, original);
  await noDelivery([replacement, sibling], "only the original author");
  await tool(hub, "link_set_identity", { group: "elsewhere" });
  await named(hub, "renamed@elsewhere");
  refused(await tool(alice, "link_reply", { replyTo: original, message: "group move must fail closed" }));
  await noDelivery([hub, replacement, sibling], "group move must fail closed");
});

test("identity fields have independent user ownership and protected updates are atomic", async (t) => {
  const { peers: [hub] } = await network(t, ["manual"]);
  const moved = await tool(hub, "link_set_identity", { group: "agent group@nested" });
  assert.equal(moved.details.error, undefined);
  assert.deepEqual(moved.details.preferred, {
    name: "manual", group: "agent group@nested", nameOrigin: "user", groupOrigin: "agent",
  });
  assert.equal(moved.details.assignedName, "manual@agent group@nested");
  assert.equal(moved.details.connectionState, "hub");
  assert.equal(moved.details.pending, false);
  for (const value of ["manual", "agent group@nested", "user", "agent", "manual@agent group@nested", "hub"]) {
    assert.ok(text(moved).includes(value), `identity success exposes ${value} in model-visible text`);
  }
  const blocked = await tool(hub, "link_set_identity", { name: "agent replacement", group: "must not commit" });
  refused(blocked);
  assert.deepEqual(blocked.details.protectedFields, ["name"]);
  assert.deepEqual(blocked.details.preferred, moved.details.preferred, "reject both fields without partial group mutation");
  assert.equal(blocked.details.assignedName, moved.details.assignedName);
  for (const value of ["manual", "agent group@nested", "user", "agent", "manual@agent group@nested", "hub"]) {
    assert.ok(text(blocked).includes(value), `identity refusal exposes unchanged ${value} in model-visible text`);
  }
  refused(await tool(hub, "link_set_identity", {}));
  for (const name of ["  ", "local@hidden-group"]) refused(await tool(hub, "link_set_identity", { name }));
  const unchanged = await tool(hub, "link_set_identity", { name: "manual", group: "" });
  assert.equal(unchanged.details.preferred.nameOrigin, "user", "unchanged protected field is a no-op, not released ownership");
  assert.equal(unchanged.details.preferred.group, "");
});

test("generated identity can change without renaming the Pi session and offline updates do not reconnect", async (t) => {
  const { peers: [hub, generated] } = await network(t, ["hub", "generated"], {
    identities: { generated: { generated: true } },
  });
  const initial = await tool(generated, "link_set_identity", {});
  refused(initial);
  assert.equal(initial.details.preferred.nameOrigin, "generated");
  assert.equal(initial.details.preferred.groupOrigin, "generated");
  const before = {
    id: generated.sessionManager.getSessionId(), file: generated.sessionManager.getSessionFile(),
    name: generated.sessionManager.getSessionName(),
  };
  const first = await tool(generated, "link_set_identity", { name: "  chosen   reviewer ", group: "review" });
  assert.equal(first.details.error, undefined);
  assert.deepEqual(first.details.preferred, {
    name: "chosen reviewer", group: "review", nameOrigin: "agent", groupOrigin: "agent",
  });
  if (first.details.pending) {
    assert.notEqual(first.details.assignedName, "chosen reviewer@review", "requested name must not be reported as assigned early");
    assert.equal(first.details.assignedName,
      first.details.connectionState === "disconnected" ? null : initial.details.assignedName,
      "a closing client reports only its actual old assignment, or null once disconnected");
  } else {
    assert.equal(first.details.assignedName, "chosen reviewer@review");
    assert.equal(first.details.connectionState, "client");
  }
  await named(generated, "chosen reviewer@review");
  assert.deepEqual({
    id: generated.sessionManager.getSessionId(), file: generated.sessionManager.getSessionFile(),
    name: generated.sessionManager.getSessionName(),
  }, before, "link identity must not change the Pi session identity, title or file");
  await command(generated, "link-disconnect");
  const offline = await tool(generated, "link_set_identity", { name: "saved offline", group: "later" });
  assert.equal(offline.details.error, undefined);
  assert.equal(offline.details.assignedName, null);
  assert.equal(offline.details.connectionState, "disconnected");
  assert.equal(offline.details.pending, false, "explicit disconnect must suppress reconnect");
  // Observe beyond the documented 2–5s reconnect backoff, not just the next tick.
  await pause(5200);
  assert.equal((await roster(generated)).error, "not_connected");
  assert.ok(!(await roster(hub)).terminals.includes("saved offline@later"));
  await command(generated, "link-connect");
  await named(generated, "saved offline@later");
});

test("native resume protects legacy identities and manual same-name claims persist ownership", async (t) => {
  const { peers: [hub, legacy, generated], addPeer } = await network(t, ["hub", "legacy", "generated"], {
    identities: { legacy: { legacyName: "t-1234@old" }, generated: { generated: true } },
  });
  const rejectedLegacy = await tool(legacy, "link_set_identity", { name: "new", group: "new" });
  refused(rejectedLegacy);
  assert.deepEqual(rejectedLegacy.details.protectedFields, ["name", "group"]);
  assert.equal(rejectedLegacy.details.preferred.name, "t-1234", "generated-looking legacy spelling is not authority");
  const chosen = await tool(generated, "link_set_identity", { name: "claimed", group: "review" });
  assert.equal(chosen.details.error, undefined);
  await named(generated, "claimed@review");
  await command(generated, "link-name", "claimed@review");
  const claimed = await tool(generated, "link_set_identity", { name: "other", group: "other" });
  refused(claimed);
  assert.deepEqual(claimed.details.protectedFields, ["name", "group"], "same-text user command must claim both explicit fields");
  for (const [peer, savedName] of [[legacy, "t-1234@old"], [generated, "claimed@review"]]) {
    await until(() => !peer.session.isStreaming, "identity session persisted");
    const savedFile = peer.sessionManager.getSessionFile();
    await command(peer, "link-disconnect");
    const resumed = await addPeer(`resumed-${peer.name}`, SessionManager.open(savedFile), { saved: true });
    await named(resumed, savedName);
    const blocked = await tool(resumed, "link_set_identity", { name: "after resume", group: "after resume" });
    refused(blocked);
    assert.deepEqual(blocked.details.protectedFields, ["name", "group"]);
    assert.equal(blocked.details.preferred.nameOrigin, "user");
    assert.equal(blocked.details.preferred.groupOrigin, "user");
  }
  assert.equal((await roster(hub)).role, "hub");
});

test("collision assignment stays in the preferred group and reports actual assigned name", async (t) => {
  const { peers: [hub, alice, outsider] } = await network(t, ["shared@review", "generated", "outsider@other"], {
    identities: { generated: { generated: true } },
  });
  const previous = await tool(alice, "link_set_identity", {});
  refused(previous);
  const result = await tool(alice, "link_set_identity", { name: "shared", group: "review" });
  assert.equal(result.details.error, undefined);
  assert.equal(result.details.preferred.name, "shared");
  assert.equal(result.details.preferred.group, "review");
  if (result.details.pending) {
    assert.equal(result.details.assignedName,
      result.details.connectionState === "disconnected" ? null : previous.details.assignedName);
    assert.notEqual(result.details.assignedName, "shared@review");
  } else assert.equal(result.details.assignedName, "shared-2@review");
  await named(alice, "shared-2@review");
  const settled = await tool(alice, "link_set_identity", {});
  refused(settled);
  assert.equal(settled.details.assignedName, "shared-2@review");
  assert.equal(settled.details.pending, false);
  assert.equal(settled.details.connectionState, "client");
  const id = messageId(await send(alice, { broadcast: true }, "collision peer still in review"));
  assert.ok(text(await received(hub, "collision peer still in review")).includes(id));
  await noDelivery([alice, outsider], "collision peer still in review");
});


test("native session resume restores only that session's received direct and broadcast reply authority", async (t) => {
  const { peers: [hub, alice, sibling], addPeer } = await network(t);
  const direct = messageId(await send(hub, "alice", "direct correction before resume"));
  await received(alice, "direct correction before resume");
  const broadcast = messageId(await send(hub, { broadcast: true }, "broadcast correction before resume"));
  await received(alice, "broadcast correction before resume");
  await received(sibling, "broadcast correction before resume");
  const otherSession = messageId(await send(hub, sibling.name, "only the sibling received this reference"));
  await received(sibling, "only the sibling received this reference");
  await noDelivery([alice], "only the sibling received this reference");
  await until(() => !alice.session.isStreaming, "received messages saved before resume");
  const savedFile = alice.sessionManager.getSessionFile();
  const sessionId = alice.sessionManager.getSessionId();
  await command(alice, "link-disconnect");
  await until(async () => !(await roster(hub)).terminals.includes("alice"), "original recipient disconnected");
  const resumed = await addPeer("resumed-alice", SessionManager.open(savedFile), { saved: true });
  await named(resumed, "alice");
  assert.equal(resumed.sessionManager.getSessionId(), sessionId, "resume retains the original receiving Pi session");
  for (const body of ["direct correction before resume", "broadcast correction before resume"]) {
    assert.ok(hasReceived(resumed, body), "native restore retains the original model-visible delivery");
  }
  for (const [reference, kind] of [[direct, "direct"], [broadcast, "broadcast"]]) {
    const body = `private ${kind} clarification after native resume`;
    const id = messageId(await tool(resumed, "link_reply", { replyTo: reference, message: body }));
    assertHeader(await received(hub, body), "alice", id, reference);
    await noDelivery([alice, sibling], body);
  }
  for (const [reference, kind] of [
    [otherSession, "other-session"],
    ["db9835a8-8be4-4607-8a3f-bf66adc03c87", "unknown"],
  ]) {
    const body = `rejected ${kind} reference after native resume`;
    refused(await tool(resumed, "link_reply", { replyTo: reference, message: body }));
    await noDelivery([hub, alice, sibling], body);
  }
});

test("reader and legacy-saved reader@ remain distinct exact direct targets through native resume", async (t) => {
  const { peers: [hub, reader, explicitEmpty], addPeer } = await network(t, ["hub", "reader", "legacy-empty-group"], {
    identities: { "legacy-empty-group": { legacyName: "reader@" } },
  });
  const expected = {
    hub: hub.sessionManager.getSessionId(),
    reader: reader.sessionManager.getSessionId(),
    "reader@": explicitEmpty.sessionManager.getSessionId(),
  };
  assert.deepEqual({ ...(await roster(hub)).sessionIds }, expected,
    "an explicit empty suffix must not collapse into the plain terminal name or acquire a collision suffix");
  for (const [target, recipient, excluded] of [
    ["reader", reader, explicitEmpty], ["reader@", explicitEmpty, reader],
  ]) {
    const body = `exact empty-group spelling ${target}`;
    const id = messageId(await send(hub, target, body));
    assertHeader(await received(recipient, body), "hub", id);
    await noDelivery([excluded], body);
  }
  const reverse = messageId(await send(explicitEmpty, "reader", "explicit suffix author attribution"));
  assertHeader(await received(reader, "explicit suffix author attribution"), "reader@", reverse);
  await until(() => !explicitEmpty.session.isStreaming, "explicit empty suffix identity persisted");
  const savedFile = explicitEmpty.sessionManager.getSessionFile();
  await command(explicitEmpty, "link-disconnect");
  await until(async () => !(await roster(hub)).terminals.includes("reader@"), "explicit suffix peer disconnected");
  const resumed = await addPeer("resumed-explicit-empty", SessionManager.open(savedFile), { saved: true });
  await named(resumed, "reader@");
  assert.deepEqual({ ...(await roster(hub)).sessionIds }, expected, "native resume preserves both exact distinct names");
  const body = "only resumed explicit suffix target";
  const id = messageId(await send(hub, "reader@", body));
  assertHeader(await received(resumed, body), "hub", id);
  await noDelivery([reader, explicitEmpty], body);
});


test("cleared queued correction grants no reply authority; admitted message_end survives native resume", async (t) => {
  const { peers: [hub, alice, sibling], addPeer } = await network(t);
  const admitted = [];
  const unsubscribe = alice.session.subscribe((event) => {
    if (event.type === "message_end" && event.message.role === "custom" && event.message.customType === "link") {
      admitted.push(event.message);
    }
  });
  t.after(unsubscribe);
  let holding = false;
  let release;
  const response = new Promise((done) => { release = done; });
  alice.hold = { entered: () => { holding = true; }, response };
  const heldPrompt = alice.session.prompt("Hold this provider request while a correction arrives.");
  const correction = "correction cleared before Pi model admission";
  let queuedId;
  try {
    await until(() => holding && alice.session.isStreaming, "recipient held inside its native provider request");
    assert.equal(alice.session.agent.hasQueuedMessages(), false, "no earlier native steering is pending");
    queuedId = messageId(await send(hub, "alice", correction));
    await pause(350);
    assert.equal(alice.session.agent.hasQueuedMessages(), true, "the real link flush enqueued native steering");
    assert.equal(admitted.length, 0, "enqueuing is not a custom link message_end admission");
    assert.equal(hasReceived(alice, correction), false, "queued steering is not yet a transcript message");
    assert.ok(!providerText(alice).includes(correction), "the held model has not received the queued correction");
    alice.session.clearQueue();
    assert.equal(alice.session.agent.hasQueuedMessages(), false, "native clearQueue removed the pending copy");
  } finally {
    release(fauxAssistantMessage("Held fixture request completed."));
    await heldPrompt;
  }
  await noDelivery([alice], correction);
  assert.equal(admitted.length, 0, "the discarded copy never emitted message_end");
  const rejectedBody = "must not reply to a cleared correction";
  const rejected = await tool(alice, "link_reply", { replyTo: queuedId, message: rejectedBody });
  assert.equal(rejected.details.error, "unknown_reference", "transport queueing must confer no received-message capability");
  refused(rejected);
  await noDelivery([hub, sibling], rejectedBody);

  const validBody = "correction actually admitted to Pi";
  const validId = messageId(await send(hub, "alice", validBody));
  await received(alice, validBody);
  await until(() => admitted.some((message) => text(message).includes(validBody)), "actual custom message_end admission");
  const liveBody = "reply to an admitted correction before resume";
  const liveId = messageId(await tool(alice, "link_reply", { replyTo: validId, message: liveBody }));
  assertHeader(await received(hub, liveBody), "alice", liveId, validId);
  await noDelivery([sibling], liveBody);
  await until(() => !alice.session.isStreaming, "admitted correction persisted");
  const savedFile = alice.sessionManager.getSessionFile();
  await command(alice, "link-disconnect");
  await until(async () => !(await roster(hub)).terminals.includes("alice"), "original admitted recipient disconnected");
  const resumed = await addPeer("resumed-after-clear", SessionManager.open(savedFile), { saved: true });
  await named(resumed, "alice");
  assert.ok(hasReceived(resumed, validBody));
  assert.equal(hasReceived(resumed, correction), false);
  const resumedBody = "reply to admitted message_end after resume";
  const resumedId = messageId(await tool(resumed, "link_reply", { replyTo: validId, message: resumedBody }));
  assertHeader(await received(hub, resumedBody), "alice", resumedId, validId);
  await noDelivery([alice, sibling], resumedBody);
  const stillRejectedBody = "cleared correction must remain unauthorized after resume";
  const stillRejected = await tool(resumed, "link_reply", { replyTo: queuedId, message: stillRejectedBody });
  assert.equal(stillRejected.details.error, "unknown_reference");
  refused(stillRejected);
  await noDelivery([hub, alice, sibling], stillRejectedBody);
});

test("broadcast correlation handles omitted, empty, and nonempty values from both root roles", async (t) => {
  const { peers: [hub, client] } = await network(t, ["hub@review", "client@review"]);
  for (const [sender, recipient] of [[hub, client], [client, hub]]) {
    for (const replyTo of [undefined, "", "correlation-not-target"]) {
      const body = `${sender.name} correlation ${JSON.stringify(replyTo)}`;
      const result = await send(sender, { broadcast: true }, body, replyTo);
      const id = messageId(result);
      assert.deepEqual(result.details.outcomes, [{ kind: "root", name: recipient.name,
        sessionId: recipient.sessionManager.getSessionId(), status: "submitted" }]);
      assertHeader(await received(recipient, body), sender.name, id, replyTo || undefined);
    }
  }
});

test("client collision assignment stays connected for unchanged preferences and reconnects for a changed name", async (t) => {
  const { peers: [hub, client] } = await network(t, ["shared@review", "generated-client"], {
    identities: { "generated-client": { generated: true } },
  });
  await tool(client, "link_set_identity", { name: "shared", group: "review" });
  await named(client, "shared-2@review");
  const runner = client.session.extensionRunner;
  const identity = runner.getToolDefinition("link_set_identity");
  const execute = (args) => identity.execute("client-identity", args, undefined, undefined, runner.createContext());
  // Inspect the synchronous tool result before a socket close/reconnect can hide
  // an unwanted disconnect behind a successful later roster query.
  for (const update of [{ group: "review" }, { name: "shared" }, { name: "shared", group: "review" }]) {
    const repeated = await execute(update);
    assert.equal(repeated.details.error, undefined);
    assert.equal(repeated.details.pending, false, "unchanged preferences must not disconnect a collision-suffixed client");
    assert.equal(repeated.details.assignedName, "shared-2@review");
    assert.equal(repeated.details.connectionState, "client");
  }
  const body = "client remains reachable after unchanged identity updates";
  const id = messageId(await send(hub, "shared-2@review", body));
  assertHeader(await received(client, body), "shared@review", id);
  const changed = await execute({ name: "changed-client" });
  assert.equal(changed.details.error, undefined);
  assert.equal(changed.details.pending, true, "a genuinely changed preference still reconnects");
  await named(hub, "changed-client@review");
  await named(client, "changed-client@review");
});

test("hub collision assignment remains stable when an unchanged preferred group is repeated", async (t) => {
  const { peers: [hub, client] } = await network(t, ["generated-hub", "shared@review"], {
    identities: { "generated-hub": { generated: true } },
  });
  const first = await tool(hub, "link_set_identity", { name: "shared", group: "review" });
  assert.equal(first.details.error, undefined);
  assert.equal(first.details.assignedName, "shared-2@review");
  await named(client, "shared-2@review");
  const repeated = await tool(hub, "link_set_identity", { group: "review" });
  assert.equal(repeated.details.error, undefined);
  assert.deepEqual(repeated.details.preferred, first.details.preferred);
  assert.equal(repeated.details.assignedName, "shared-2@review", "an unchanged preference must retain its actual collision assignment");
  assert.equal(repeated.details.pending, false);
  assert.equal(repeated.details.connectionState, "hub");
  const rosterAfter = await roster(hub);
  assert.deepEqual(rosterAfter.terminals.slice().sort(), ["shared-2@review", "shared@review"]);
});

test("explicit disconnect cancels an in-flight client rename while preserving its next-connection preference", async (t) => {
  const { peers: [hub, alice] } = await network(t, ["hub", "generated-client"], {
    identities: { "generated-client": { generated: true } },
  });
  const runner = alice.session.extensionRunner;
  const identity = runner.getToolDefinition("link_set_identity");
  const execute = (args) => identity.execute("deterministic-rename-race", args, undefined, undefined, runner.createContext());
  // Execute the registered public tool without a model round trip, so no socket
  // event can finish reconnecting before the immediately following user command.
  const rename = await execute({ name: "requested-before-disconnect" });
  assert.equal(rename.details.error, undefined);
  assert.equal(rename.details.pending, true, "the native client rename must actually be in flight");
  await runner.getCommand("link-disconnect").handler("", runner.createCommandContext());
  const offline = await execute({ name: "saved-next-connection", group: "review" });
  assert.equal(offline.details.error, undefined);
  assert.equal(offline.details.pending, false, "explicit disconnect must cancel pending assignment, not just its socket");
  assert.equal(offline.details.assignedName, null);
  assert.equal(offline.details.connectionState, "disconnected");
  assert.equal(offline.details.preferred.name, "saved-next-connection");
  assert.equal(offline.details.preferred.group, "review");
  assert.equal((await roster(alice)).error, "not_connected");
  await command(hub, "link-disconnect");
  // Let the old server's close event finish before one explicit connection attempt.
  await pause(50);
  await runner.getCommand("link-connect").handler("", runner.createCommandContext());
  await named(alice, "saved-next-connection@review");
  const connected = await execute({});
  assert.equal(connected.details.assignedName, "saved-next-connection@review");
  assert.equal(connected.details.pending, false);
  assert.equal(connected.details.connectionState, "hub");
});


test("installed root bridge discovers per operation and transports worker replies without parent delivery", async (t) => {
  // A structural manager fixture, not proof of the actual subagent manager/helper.
  const { peers: [hub, owner, author] } = await network(t);
  const ownerSessionId = owner.sessionManager.getSessionId();
  const worker = { workerId: "native-stable-worker", taskName: "clarifier" };
  const deliveries = [];
  const answers = [];
  const stop = owner.eventBus.on("pi-link:workers:v1", (event) => {
    assert.equal(event.version, 1); assert.equal(event.ownerSessionId, ownerSessionId);
    event.provide({ broadcast: async (message) => { deliveries.push(message); return [{ ...worker, status: "submitted" }]; },
      reply: async (target, message) => { answers.push({ target, message }); return { status: "submitted" }; } });
  });
  const correction = messageId(await tool(author, "link_send", { to: { broadcast: true }, message: "native worker correction", includeSubagents: true }));
  assert.equal(deliveries.length, 1);
  assert.equal(deliveries[0].id, correction);
  // Manager supplies actual child admission; root transcript need not admit it.
  const reference = { ...deliveries[0], id: "child-transcript-only-reference" };
  let response;
  owner.eventBus.emit("pi-link:worker-reply:v1", { version: 1, ownerSessionId, worker, reference,
    message: "native worker private question", respond(promise) { response = promise; } });
  assert.ok(response instanceof Promise, "respond is called synchronously during emit");
  const workerResult = await response;
  assert.notEqual(workerResult.isError, true);
  const question = workerResult.details.messageId;
  assert.match(question, uuid);
  const entry = await received(author, "native worker private question");
  assert.ok(text(entry).includes(worker.taskName));
  const answer = messageId(await tool(author, "link_reply", { replyTo: question, message: "native private worker answer" }));
  assert.equal(answers.length, 1);
  assert.deepEqual(answers[0].target, worker);
  assert.equal(answers[0].message.id, answer);
  assert.ok(!providerText(owner).includes("native private worker answer"));
  assert.ok(!providerText(hub).includes("native worker private question"));
  let mismatched = false;
  owner.eventBus.emit("pi-link:worker-reply:v1", { version: 1, ownerSessionId: "wrong-owner", worker, reference,
    message: "must not route", respond() { mismatched = true; } });
  assert.equal(mismatched, false);
  stop();
  const missing = await tool(author, "link_send", { to: { broadcast: true }, message: "bridge removed", includeSubagents: true });
  assert.ok(missing.details.outcomes.some(o => o.sessionId === ownerSessionId && o.reason === "worker_integration_unavailable"));

  // Once a helper claims a reference, an unknown outcome must not fall through
  // to the independent endpoint's otherwise-valid reply route and send again.
  const direct = messageId(await send(author, "alice", "claim-once reference"));
  await received(owner, "claim-once reference");
  const claimed = { content: [{ type: "text", text: "unknown managed outcome" }],
    details: { status: "unknown", reason: "worker_routing_deadline" } };
  const stopChild = owner.eventBus.on("pi-link:child-reply:v1", (request) => {
    assert.equal(request.version, 1);
    if (request.replyTo === direct) request.respond(Promise.resolve(claimed));
  });
  const settled = await tool(owner, "link_reply", { replyTo: direct, message: "must not retry on endpoint" });
  assert.deepEqual(settled.details, claimed.details);
  stopChild();
  await pause(300);
  assert.ok(!providerText(author).includes("must not retry on endpoint"));
});

test("managed child loading the configured package registers ordinary link tools and hooks", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-link-child-enabled-"));
  const previous = process.env.PI_SUBAGENT_OWNER_TOKEN;
  try {
    process.env.PI_SUBAGENT_OWNER_TOKEN = "fixture-owner-token";
    const loaded = await discoverAndLoadExtensions([sourcePath], directory, join(directory, "agent"));
    assert.deepEqual(loaded.errors, []);
    const extension = loaded.extensions[0];
    assert.deepEqual([...extension.tools.keys()].sort(),
      ["link_compact", "link_list", "link_reply", "link_send", "link_set_identity"]);
    assert.ok(extension.flags.has("link"));
    assert.ok(extension.handlers.has("session_start"));
    assert.ok(extension.commands.has("link-connect"));
  } finally {
    if (previous === undefined) delete process.env.PI_SUBAGENT_OWNER_TOKEN;
    else process.env.PI_SUBAGENT_OWNER_TOKEN = previous;
    await rm(directory, { recursive: true, force: true });
  }
});
