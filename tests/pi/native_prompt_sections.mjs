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

// Use a built-in provider, not faux: faux skips before_provider_request. Only
// fetch and the editor surface are replaced; native hook/command dispatch stays real.
for (const guest of [false, true]) {
  test(`prepared-prompt viewers survive settlement and clear on reload (guest=${guest})`, async (t) => {
    const root = await mkdtemp(join(tmpdir(), "pi-native-prompt-viewers-"));
    const keys = ["CODEX_SANDBOX_TOOL_CONTAINER", "CODEX_SANDBOX_GUEST_CWD",
      "CODEX_SANDBOX_PI_RESOURCE_PATHS", "CODEX_SANDBOX_PREVIOUS_CWD"];
    const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
    t.after(async () => {
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
      await rm(root, { recursive: true, force: true });
    });
    for (const key of keys) delete process.env[key];
    const cwd = join(root, "project");
    const agentDir = join(root, "agent");
    await Promise.all([mkdir(cwd), mkdir(agentDir)]);
    const includePath = join(cwd, "rules.md");
    const firstMarker = "First expanded instruction marker.";
    const secondMarker = "Second expanded instruction marker with a different size.";
    await writeFile(includePath, firstMarker);
    if (guest) {
      process.env.CODEX_SANDBOX_TOOL_CONTAINER = "offline-fixture-not-contacted";
      process.env.CODEX_SANDBOX_GUEST_CWD = "/guest/project";
      process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({
        "/host/policy.md": "/guest/policy.md", [includePath]: "/guest/rules.md",
      });
    }
    const baseUrl = "http://pi-native-prompt-viewers.invalid/v1";
    const requests = [];
    t.mock.method(globalThis, "fetch", async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      assert.equal(url, `${baseUrl}/chat/completions`, "no real network requests are allowed");
      requests.push(JSON.parse(init?.body ?? await input.clone().text()));
      const chunks = [
        { id: "viewer_fixture", object: "chat.completion.chunk", choices: [{ index: 0,
          delta: { role: "assistant", content: "Offline viewer answer." }, finish_reason: null }] },
        { id: "viewer_fixture", object: "chat.completion.chunk", choices: [{ index: 0,
          delta: {}, finish_reason: "stop" }] },
      ];
      return new Response(chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("") +
        "data: [DONE]\n\n", { status: 200, headers: { "content-type": "text/event-stream" } });
    });
    const model = { id: "fixture", name: "Offline fixture", provider: "offline-prompt-viewers",
      api: "openai-completions", baseUrl, reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 256 };
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(), modelsPath: null,
      modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
    });
    await modelRuntime.setRuntimeApiKey(model.provider, "offline-not-a-credential");
    const prepared = [];
    const loader = new DefaultResourceLoader({
      cwd, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: ["pi-instruction-includes", "system-prompt", "context-breakdown",
        ...(guest ? ["guest-tools"] : [])].map((name) => join(extensionDir, `${name}.ts`)),
      agentsFilesOverride: () => ({ agentsFiles: [{ path: join(cwd, "AGENTS.md"), content: "@rules.md" }] }),
      systemPrompt: "Native viewer base instructions. Host reference: /host/policy.md",
      extensionFactories: [(pi) => {
        pi.registerProvider(model.provider, { baseUrl, api: model.api, apiKey: "offline-not-a-credential",
          models: [model] });
        pi.on("before_provider_request", (_event, ctx) => { prepared.push(ctx.getSystemPrompt()); });
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const { session, extensionsResult } = await createAgentSession({
      cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager: SessionManager.inMemory(cwd), model, tools: [],
    });
    t.after(() => session.dispose());
    assert.deepEqual(extensionsResult.errors, []);
    const editors = [];
    const notifications = [];
    await session.bindExtensions({ mode: "tui", uiContext: {
      editor: async (title, text) => { editors.push({ title, text }); return "ignored edit"; },
      notify: (text, level) => notifications.push({ text, level }),
    } });
    const inspect = async () => {
      await session.prompt("/system-prompt");
      await session.prompt("/context-breakdown");
    };
    await inspect();
    assert.equal(editors.length, 0, "startup must not display the untransformed base prompt");
    assert.equal(notifications.length, 2);
    assert.ok(notifications.every(({ text }) => text.includes("No system prompt captured")));
    assert.equal(requests.length, 0, "viewer commands must not call the provider");

    await session.prompt("First native request.");
    assert.equal(requests.length, 1);
    assert.equal(prepared.length, 1, "the native provider fires the actual capture hook");
    assert.equal(session.messages.at(-1).stopReason, "stop", session.messages.at(-1).errorMessage);
    assert.ok(!session.systemPrompt.includes(firstMarker), "Pi's getter reverted after settlement");
    const firstSystem = requests[0].messages.find((message) => ["system", "developer"].includes(message.role));
    assert.equal(firstSystem.content, prepared[0], "capture matches the built-in provider's first serialized prompt");
    await inspect();
    assert.ok(editors[0].text.endsWith(`\n\n${prepared[0]}`), "viewer retains the complete transformed prompt");
    assert.ok(editors[0].text.includes(firstMarker));
    assert.ok(editors[0].text.includes(`Selected model: ${model.provider}/${model.id}`));
    assert.match(editors[0].text, /Captured at: \d{4}-\d{2}-\d{2}T/);
    assert.ok(editors[1].text.includes(`Prompt subtotal: ${Math.ceil(prepared[0].length / 4).toLocaleString("en-US")}`));
    if (guest) {
      assert.ok(editors[0].text.includes("/guest/policy.md"));
      assert.ok(!editors[0].text.includes("/host/policy.md"));
    }
    assert.equal(requests.length, 1);

    await writeFile(includePath, secondMarker);
    await session.prompt("Second native request.");
    await inspect();
    assert.equal(requests.length, 2);
    assert.ok(editors[2].text.endsWith(`\n\n${prepared[1]}`));
    assert.ok(editors[2].text.includes(secondMarker));
    assert.ok(!editors[2].text.includes(firstMarker), "latest capture replaces previous instructions");
    assert.ok(editors[3].text.includes(`Prompt subtotal: ${Math.ceil(prepared[1].length / 4).toLocaleString("en-US")}`));

    await session.reload();
    await inspect();
    assert.equal(editors.length, 4, "reload must not show a stale snapshot or idle base prompt");
    assert.equal(notifications.length, 4);
    assert.ok(notifications.slice(2).every(({ text }) => text.includes("No system prompt captured")));
    assert.equal(requests.length, 2);
    await session.prompt("New request after reload.");
    await inspect();
    assert.equal(requests.length, 3);
    assert.ok(editors[4].text.endsWith(`\n\n${prepared[2]}`));
    assert.ok(editors[4].text.includes(secondMarker), "capture resumes in the reloaded runtime");
  });
}

// Exercise the actual client route and shared/reference sources, not a second
// copy of their policy prose. Only the reference's explicit read reaches tools.
test("native prompt expands shared instructions but reads task evidence only explicitly", async (t) => {
  const { copyFile, cp, realpath } = await import("node:fs/promises");
  const { execFile } = await import("node:child_process");
  const { promisify } = await import("node:util");
  const { fauxToolCall } = await import(pathToFileURL(resolve(aiPackageDir, aiManifest.exports["."].import)).href);
  const repository = resolve(extensionDir, "../../..");
  const root = await mkdtemp(join(tmpdir(), "pi-native-evidence-route-"));
  const keys = ["HOME", "CODEX_SANDBOX_TOOL_CONTAINER", "CODEX_SANDBOX_GUEST_CWD",
    "CODEX_SANDBOX_PI_RESOURCE_PATHS", "CODEX_SANDBOX_PREVIOUS_CWD"];
  const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
  t.after(async () => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(root, { recursive: true, force: true });
  });
  for (const key of keys) delete process.env[key];
  const home = join(root, "home");
  process.env.HOME = home;
  const cwd = join(root, "project");
  const agentDir = join(home, ".pi/agent");
  await Promise.all([cwd, agentDir, join(home, ".agents"), join(root, "checkout")]
    .map((path) => mkdir(path, { recursive: true })));
  const manifest = JSON.parse(await readFile(join(repository, "install.conf.json"), "utf8"));
  const destinations = ["$HOME/.agents/shared.md", "$HOME/.agents/skills"];
  const links = {};
  const defaults = [];
  for (const entry of manifest) {
    if (entry.defaults) defaults.push(entry);
    for (const [destination, spec] of Object.entries(entry.link ?? {})) {
      assert.notEqual(destination, "$HOME/.agents/change-with-evidence.md", "no new top-level link");
      assert.notEqual(destination, "$HOME/.agents/skills/references/change-with-evidence.md", "no individual link");
      if (!destinations.includes(destination)) continue;
      assert.equal(links[destination], undefined, "one authority per installed role");
      links[destination] = spec;
      const source = typeof spec === "string" ? spec : spec.path;
      await cp(join(repository, source), join(root, "checkout", source), { recursive: true });
    }
  }
  assert.deepEqual(Object.keys(links).sort(), destinations.toSorted());
  const config = join(root, "checkout/install.conf.json");
  await writeFile(config, JSON.stringify([...defaults, { link: links }]));
  await promisify(execFile)(join(repository, "vendor/dotbot/bin/dotbot"),
    ["-d", join(root, "checkout"), "-c", config], { env: { ...process.env, HOME: home }, cwd: root });
  const skillsPath = join(home, ".agents/skills");
  const skillsSpec = links["$HOME/.agents/skills"];
  assert.equal(await realpath(skillsPath),
    join(root, "checkout", typeof skillsSpec === "string" ? skillsSpec : skillsSpec.path));
  const instructionsPath = join(agentDir, "AGENTS.md");
  await copyFile(join(repository, "config/pi-agent/AGENTS.md"), instructionsPath);
  const client = await readFile(instructionsPath, "utf8");
  const shared = await readFile(join(home, ".agents/shared.md"), "utf8");
  const routes = [...shared.matchAll(/\[Change with evidence\]\(([^)]+)\)/g)];
  assert.equal(routes.length, 1);
  assert.equal(routes[0][1], "~/.agents/skills/references/change-with-evidence.md");
  const referencePath = join(home, routes[0][1].slice(2));
  const reference = await readFile(referencePath, "utf8");
  assert.ok(!reference.startsWith("---"), "plain Markdown reference has no skill frontmatter");
  const referenceParagraphs = reference.trim().split(/\n\s*\n/)
    .filter((paragraph) => !paragraph.startsWith("#"));
  assert.ok(referenceParagraphs.length > 0, "reference must contain task rules");
  const faux = fauxProvider({ provider: "native-evidence-route", api: "anthropic-messages" });
  const requests = [];
  // Native tool declarations carry executable functions; capture only their
  // JSON projection alongside the text transcript consumed by the provider.
  const capture = (context) => {
    requests.push({ messages: JSON.parse(JSON.stringify(context.messages)) });
    return fauxAssistantMessage("offline evidence route check");
  };
  faux.setResponses([capture, (context) => {
    requests.push({ messages: JSON.parse(JSON.stringify(context.messages)) });
    return fauxAssistantMessage([fauxToolCall("read", { path: referencePath })], { stopReason: "toolUse" });
  }, capture]);
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalSkillPaths: [skillsPath],
    additionalExtensionPaths: [join(extensionDir, "pi-instruction-includes.ts")],
    agentsFilesOverride: () => ({ agentsFiles: [{ path: instructionsPath, content: client }] }),
    extensionFactories: [(pi) => { pi.registerProvider(faux.provider); }],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const skillMetadata = loader.getSkills().skills;
  assert.ok(skillMetadata.length > 0, "whole skills directory is actually scanned");
  assert.ok(skillMetadata.every((skill) => !skill.filePath.includes("/references/")),
    "references must not become startup skill metadata");
  assert.ok(!JSON.stringify(loader.getSkills()).includes(reference.trim()), "reference body is not metadata");
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: SessionManager.inMemory(cwd), model: faux.getModel(), tools: ["read"],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  await session.prompt("Prepare a startup prompt without opening task references.");
  assert.equal(requests.length, 1, session.messages.at(-1)?.errorMessage);
  const prepared = systems(requests[0]).map(getSystemMessageText).join("\n");
  assert.ok(prepared.includes(client.trim()), "native prompt retains the actual client route");
  assert.ok(prepared.includes(shared.trim()), "native prompt expands the authoritative shared rules");
  assert.ok(prepared.includes(routes[0][0]), "the task reference remains a Markdown route");
  for (const paragraph of referenceParagraphs) {
    assert.ok(!prepared.includes(paragraph), "task reference body must not enter the startup prompt");
  }
  assert.equal(session.messages.some((message) => message.role === "toolResult"), false);
  await session.prompt("Explicitly read the Change with evidence reference now.");
  assert.equal(requests.length, 3, "the explicit read and its result reach the offline provider");
  const readResult = requests[2].messages.find((message) => message.role === "toolResult" && message.toolName === "read");
  assert.ok(readResult, "the real native read tool returns the installed reference");
  assert.equal(readResult.isError, false);
  assert.ok(readResult.content.some((block) => block.type === "text" && block.text.includes(reference.trim())));
  for (const request of requests) {
    for (const system of systems(request)) {
      assert.ok(!getSystemMessageText(system).includes(reference.trim()), "explicit reading must not auto-include the body");
    }
  }
});
