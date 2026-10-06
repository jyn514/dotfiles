// Deliberately avoid Bun's *_test filename pattern. dev/test runs this with
// Node so Bun's mock.module registrations cannot replace the installed SDK.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir, type, release } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifestPath = join(packageDir, "package.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
// Use the installed build: the locked test SDK predates structured prompt options.
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
  getReadmePath, getDocsPath, getExamplesPath } =
  await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
// pi-ai is import-only; createRequire.resolve() uses the unsupported require
// condition. Find its manifest through the installed SDK's dependency search
// paths, then import the declared public root export (never a private module).
let aiPackageDir;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  const candidate = join(modulesDir, "@earendil-works/pi-ai");
  try {
    await readFile(join(candidate, "package.json"));
    aiPackageDir = candidate;
    break;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
assert.ok(aiPackageDir, "pi-ai must resolve from the installed SDK");
const aiManifest = JSON.parse(await readFile(join(aiPackageDir, "package.json"), "utf8"));
assert.equal(aiManifest.name, "@earendil-works/pi-ai");
const { fauxProvider, fauxAssistantMessage, InMemoryCredentialStore, getSystemMessageText } =
  await import(pathToFileURL(resolve(aiPackageDir, aiManifest.exports["."].import)).href);
const extensionDir = resolve(dirname(fileURLToPath(import.meta.url)), "../../config/pi-agent/pi-extensions");
const extensionNames = ["current-date", "host-os", "pi-instruction-includes", "pi-web-search"];
const sectionNames = ["current_date", "host_os", "instruction_includes", "web_search"];

async function expectedHostName() {
  if (type() === "Linux") {
    for (const path of ["/etc/os-release", "/usr/lib/os-release"]) {
      let text;
      try { text = await readFile(path, "utf8"); } catch { continue; }
      const match = text.match(/^PRETTY_NAME=(.*)$/m);
      if (match) return match[1].trim().replace(/^(["'])(.*)\1$/, "$2").replace(/\\(["\\$`])/g, "$1");
      break;
    }
  }
  return `${type()} ${release()}`;
}

function systems(context) {
  return context.messages.filter((message) => message.role === "system");
}

// A returned full-prompt handler can still leave structured transcript patches.
// Inspect forceSystemPrompt after all four handlers as well as the provider's
// transcript; otherwise that old implementation could falsely pass this test.
test("native session renders four sections once and sends only changed-section patches", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "pi-native-sections-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "project");
  const agentDir = join(root, "agent");
  await mkdir(cwd);
  await mkdir(agentDir);
  const instructionsPath = join(cwd, "AGENTS.md");
  const includePath = join(cwd, "host-instructions.md");
  const loaderInstructions = "Loader-owned project instructions.\n@host-instructions.md";
  const includedInstructions = "Included from the actual host disk: preserve the release checklist.";
  await writeFile(instructionsPath, loaderInstructions);
  await writeFile(includePath, includedInstructions);

  const supported = fauxProvider({ provider: "native-sections-supported", api: "anthropic-messages" });
  const unsupported = fauxProvider({ provider: "native-sections-unsupported", api: "openai-completions" });
  const requests = [];
  const capture = (context) => {
    requests.push(structuredClone(context));
    return fauxAssistantMessage("offline native answer");
  };
  supported.setResponses([capture, capture, capture]);
  unsupported.setResponses([capture]);
  const inspections = [];
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"),
    allowModelNetwork: false, refreshOnCreate: false,
  });
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: extensionNames.map((name) => join(extensionDir, `${name}.ts`)),
    agentsFilesOverride: () => ({ agentsFiles: [{ path: instructionsPath, content: loaderInstructions }] }),
    systemPrompt: "Native regression base instructions.",
    appendSystemPrompt: ["Loader-owned appended instructions."],
    extensionFactories: [(pi) => {
      pi.registerProvider(supported.provider);
      pi.registerProvider(unsupported.provider);
      pi.on("before_agent_start", (event, ctx) => {
        inspections.push({
          force: event.systemPromptOptions.forceSystemPrompt,
          sections: structuredClone(event.systemPromptOptions.sections),
          prompt: ctx.getSystemPrompt(),
        });
      });
    }],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: SessionManager.inMemory(cwd), model: supported.getModel(), tools: [],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  assert.deepEqual(extensionsResult.extensions.slice(0, 4).map((extension) => extension.path),
    extensionNames.map((name) => join(extensionDir, `${name}.ts`)));

  // Local dates at noon avoid DST/midnight ambiguity; only Date is faked.
  t.mock.timers.enable({ apis: ["Date"], now: new Date(2026, 9, 6, 12).getTime() });
  await session.prompt("first turn");
  t.mock.timers.setTime(new Date(2026, 9, 7, 12).getTime());
  await session.prompt("after local date rollover");
  await session.prompt("unchanged third turn");
  await session.setModel(unsupported.getModel());
  await session.prompt("unsupported search model");
  assert.equal(requests.length, 4, "all turns reached the offline native provider");
  assert.equal(supported.state.callCount, 3);
  assert.equal(unsupported.state.callCount, 1);
  assert.deepEqual(inspections.map((inspection) => inspection.force), [undefined, undefined, undefined, undefined],
    "section contributors must never force a full leading prompt");
  assert.deepEqual(Object.keys(inspections[0].sections), sectionNames, "registration order is retained");

  const initial = systems(requests[0]);
  assert.equal(initial.length, 1);
  assert.equal(initial[0].content, "");
  const rendered = getSystemMessageText(initial[0]);
  for (const name of sectionNames) {
    assert.equal(rendered.split(`<${name}>`).length - 1, 1, `${name} rendered exactly once`);
    assert.equal(rendered.split(`</${name}>`).length - 1, 1, `${name} closed exactly once`);
  }
  for (const text of ["Native regression base instructions.", "Loader-owned appended instructions.",
    loaderInstructions, includedInstructions, `User's host OS: ${await expectedHostName()}.`,
    "Today's date: 2026-10-06.", "Web search is available through the active model provider."]) {
    assert.equal(rendered.split(text).length - 1, 1, `${text} occurs once in the model prompt`);
  }
  assert.match(initial[0].sections.instruction_includes, new RegExp(includePath));
  assert.equal(inspections[0].prompt, rendered);
  const customKeys = Object.keys(initial[0].sections).filter((name) => sectionNames.includes(name));
  assert.deepEqual(customKeys, sectionNames);

  const rollover = systems(requests[1]);
  assert.equal(rollover.length, 2);
  assert.deepEqual(rollover[0], initial[0], "cached initial system prefix remains intact");
  assert.equal(rollover[1].content, "");
  assert.deepEqual(rollover[1].sections, { current_date: "<current_date>\nToday's date: 2026-10-07.\n</current_date>" });
  assert.deepEqual(systems(requests[2]), rollover, "unchanged inputs append no system patch");
  const switched = systems(requests[3]);
  assert.equal(switched.length, 3);
  assert.deepEqual(switched.slice(0, 2), rollover);
  assert.equal(switched[2].content, "");
  assert.deepEqual(switched[2].sections, { web_search: null });
  assert.equal(inspections[3].sections.web_search, undefined);
  assert.equal(inspections[3].prompt.includes("<web_search>"), false);
  assert.equal(inspections[3].prompt.includes("Today's date: 2026-10-07."), true);
  assert.equal(inspections[3].prompt.includes(includedInstructions), true);
  assert.deepEqual(session.messages.filter((message) => message.role === "system"), switched,
    "the provider consumed the session's real system transcript");
});

// Compare against Pi's own generated docs instead of copying its path/routing
// template into the extension or test. The guest case reaches the forced-prompt
// projection received by a provider, not just the extension's options.
test("the bundle replaces only documentation policy and guest routing preserves it", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "pi-task-directed-docs-"));
  const environmentKeys = ["CODEX_SANDBOX_TOOL_CONTAINER", "CODEX_SANDBOX_GUEST_CWD",
    "CODEX_SANDBOX_PI_RESOURCE_PATHS", "CODEX_SANDBOX_PREVIOUS_CWD"];
  const saved = Object.fromEntries(environmentKeys.map((key) => [key, process.env[key]]));
  const sessions = [];
  t.after(async () => {
    for (const session of sessions) session.dispose();
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(root, { recursive: true, force: true });
  });
  for (const key of environmentKeys) delete process.env[key];
  const cwd = join(root, "project");
  const agentDir = join(root, "agent");
  const guestCwd = join(root, "guest");
  await Promise.all([cwd, agentDir, guestCwd].map((path) => mkdir(path)));
  const resourcePaths = {
    [getReadmePath()]: "/guest/pi/README.md",
    [getDocsPath()]: "/guest/pi/docs",
    [getExamplesPath()]: "/guest/pi/examples",
  };
  const faux = fauxProvider({ provider: "task-directed-docs", api: "anthropic-messages" });
  const requests = [];
  const capture = (context) => {
    requests.push(structuredClone(context));
    return fauxAssistantMessage("offline documentation policy check");
  };
  faux.setResponses([capture, capture, capture]);
  const inspections = [];
  const bundle = join(extensionDir, "index.ts");
  for (const extensionPaths of [[], [bundle], [bundle, join(extensionDir, "guest-tools.ts")]]) {
    if (extensionPaths.length === 2) {
      process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture-not-contacted";
      process.env.CODEX_SANDBOX_GUEST_CWD = guestCwd;
      process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify(resourcePaths);
    }
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(), modelsPath: null,
      modelsStorePath: join(agentDir, "models-store.json"),
      allowModelNetwork: false, refreshOnCreate: false,
    });
    const loader = new DefaultResourceLoader({
      cwd, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: extensionPaths,
      extensionFactories: [(pi) => {
        pi.registerProvider(faux.provider);
        pi.on("before_agent_start", (event) => {
          inspections.push({ force: event.systemPromptOptions.forceSystemPrompt,
            prompt: event.systemPrompt, docs: event.systemPromptOptions.sections.docs });
        });
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const { session } = await createAgentSession({
      cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager: SessionManager.inMemory(cwd), model: faux.getModel(), tools: [],
    });
    sessions.push(session);
    await session.prompt("check documentation policy");
  }
  assert.equal(requests.length, 3, "baseline, bundle, and guest all reached the provider");
  const prompts = requests.map((request) => getSystemMessageText(systems(request)[0]));
  const bodies = prompts.map((prompt) => {
    assert.equal(prompt.match(/^<docs>$/gm)?.length, 1, "docs renders exactly once");
    const body = prompt.match(/^<docs>\n([\s\S]*?)\n<\/docs>$/m)?.[1];
    assert.ok(body, "generated docs must remain present");
    return body;
  });
  const oldRule = (line) => line.startsWith("- When working on pi topics,") || line.startsWith("- Always read pi .md files");
  const newRule = (line) => line.startsWith("- Before implementing Pi-specific behavior,");
  assert.equal(bodies[0].split("\n").filter(oldRule).length, 2, "baseline contains the two rules being replaced");
  const retained = bodies[0].split("\n").filter((line) => !oldRule(line));
  for (const body of bodies.slice(1)) {
    assert.equal(body.split("\n").filter(oldRule).length, 0, "neither blanket rule may survive");
    const policy = body.split("\n").filter(newRule);
    assert.equal(policy.length, 1, "replacement policy occurs exactly once");
    assert.match(policy[0], /read the relevant documentation sections/);
    assert.match(policy[0], /Follow references when they define an API or constraint needed for the task/);
    assert.match(policy[0], /Read whole files only when the task requires understanding them as a whole/);
  }
  assert.deepEqual(bodies[1].split("\n").filter((line) => !newRule(line)), retained,
    "all generated documentation paths and topic routes are unchanged");
  assert.equal(inspections[1].force, undefined, "the policy extension must not force the full prompt");
  assert.equal(inspections[1].docs, bodies[1], "Pi wraps the replacement section once");
  let expectedGuest = bodies[1];
  for (const [host, guest] of Object.entries(resourcePaths)) {
    expectedGuest = expectedGuest.replaceAll(host, guest);
    assert.ok(bodies[2].includes(guest), "each documentation path is translated for guest tools");
    assert.equal(bodies[2].includes(host), false, "host documentation paths do not leak");
  }
  assert.equal(bodies[2], expectedGuest, "guest routing changes paths, not policy or topic routes");
  assert.equal(inspections[2].force, prompts[2], "provider receives the guest hook's final forced prompt");
  assert.equal(prompts[1], inspections[1].prompt);
});
