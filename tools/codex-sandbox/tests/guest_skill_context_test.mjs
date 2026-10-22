import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const cli = join(homedir(), ".local/share/pi/node/node_modules/.bin/pi");
const packageDir = process.env.PI_PACKAGE_DIR && realpathSync(process.env.PI_PACKAGE_DIR);
const sdkEntry = packageDir
  ? pathToFileURL(join(packageDir, JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8")).exports["."].import)).href
  : existsSync(cli) ? new URL("../index.js", pathToFileURL(realpathSync(cli))).href : undefined;

test("guest context rewrites expanded skills in history without changing stored messages", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async () => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(
    sdkEntry
  );
  const directory = mkdtempSync(join(tmpdir(), "guest-skill-context-"));
  const savedEnvironment = { ...process.env };
  try {
    process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
    process.env.CODEX_SANDBOX_GUEST_CWD = "/src/repository";
    process.env.CODEX_SANDBOX_GUEST_REPO = "/src/repository";
    delete process.env.CODEX_SANDBOX_PREVIOUS_CWD;
    process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({
      "/home/jyn/.agents/skills": "/home/codex/.agents/skills",
    });
    const loaded = await discoverAndLoadExtensions([
      join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
    ], directory, directory);
    assert.deepEqual(loaded.errors, []);
    const runner = new ExtensionRunner(
      loaded.extensions, loaded.runtime, directory, SessionManager.inMemory(directory), {},
    );
    const errors = [];
    runner.onError((error) => errors.push(error));
    const skill = '<skill name="jj-workflow" location="/home/jyn/.agents/skills/jj-workflow/SKILL.md">\n'
      + 'References are relative to /home/jyn/.agents/skills/jj-workflow.\n\n'
      + 'Read /home/jyn/.agents/skills/spec-review/SKILL.md.\n</skill>\n\nreview this';
    const image = { type: "image", data: "fixture", mimeType: "image/png" };
    const messages = [
      { role: "user", content: skill, timestamp: 1 },
      { role: "user", content: [{ type: "text", text: skill }, image], timestamp: 2 },
      { role: "user", content: "inspect /home/jyn/.agents/skills", timestamp: 3 },
      { role: "assistant", content: [{ type: "text", text: skill }], timestamp: 4 },
      { role: "toolResult", content: [{ type: "text", text: skill }], timestamp: 5 },
    ];
    const original = structuredClone(messages);
    const rewritten = await runner.emitContext(messages);
    assert.deepEqual(errors, []);
    const expected = skill.replaceAll("/home/jyn/.agents/skills", "/home/codex/.agents/skills");
    assert.equal(rewritten[0].content, expected);
    assert.equal(rewritten[1].content[0].text, expected);
    assert.deepEqual(rewritten[1].content[1], image);
    assert.deepEqual(rewritten.slice(2), original.slice(2));
    assert.deepEqual(messages, original);
    assert.deepEqual(await runner.emitContext(rewritten), rewritten);

    // Goal-triggered runs skip before_agent_start; section patches and resumed
    // system messages still need the same guest view as ordinary prompts.
    const systems = [
      { role: "system", content: "Current working directory: /host/project", timestamp: 0,
        sections: { skills: skill, cwd: "<cwd>\n/host/project\n</cwd>" },
        toolsAdded: [{ name: "read", description: "fixture" }] },
      { role: "system", content: [{ type: "text", text: skill }], timestamp: 6,
        sections: { skills: skill, removed: null } },
    ];
    const storedSystems = structuredClone(systems);
    const projected = await runner.emitContext(systems);
    assert.equal(projected[0].content, "Current working directory: /src/repository");
    assert.equal(projected[0].sections.cwd, "<cwd>\n/src/repository\n</cwd>");
    assert.equal(projected[0].sections.skills, expected);
    assert.deepEqual(projected[0].toolsAdded, systems[0].toolsAdded);
    assert.equal(projected[1].content[0].text, expected);
    assert.equal(projected[1].sections.skills, expected);
    assert.equal(projected[1].sections.removed, null);
    assert.deepEqual(systems, storedSystems);
    assert.deepEqual(await runner.emitContext(projected), projected);
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  }
});

test("sandbox context projects link-list cwd metadata without changing identities or stored host paths", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async (t) => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(sdkEntry);
  const directory = mkdtempSync(join(tmpdir(), "guest-link-context-"));
  const savedEnvironment = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  });
  Object.assign(process.env, {
    CODEX_SANDBOX_GUEST_CWD: "/src/llms/pi/nested",
    CODEX_SANDBOX_GUEST_REPO: "/src/llms/pi",
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({
      "/host/src": "/src",
      "/host/src/dotfiles": "/src/launcher-dotfiles",
    }),
  });
  const cwds = [
    ["/host/src/llms/pi/nested", "/src/llms/pi/nested"],
    ["/host/src/llms/prose-eval", "/src/llms/prose-eval"],
    ["/host/src/dotfiles", "/src/launcher-dotfiles"],
    ["/outside/project", "/outside/project"],
    ["/host/src-old/project", "/host/src-old/project"],
  ];
  // A terminal name may itself contain a path. Only cwd metadata is a guest path.
  const heading = "Connected terminals:\n  • /host/src/llms/pi (you)\n    Pi session ID: fixture-session";
  const text = `${heading}\n${cwds.map(([host]) => `    cwd: ${host}`).join("\n")}`;
  const image = { type: "image", data: "fixture", mimeType: "image/png" };
  const messages = [
    { role: "toolResult", toolCallId: "list", toolName: "link_list", timestamp: 1, isError: false,
      content: [{ type: "text", text }, image], details: { cwds: { self: cwds[0][0] } } },
    { role: "toolResult", toolCallId: "read", toolName: "read", timestamp: 2, isError: false,
      content: [{ type: "text", text }] },
    { role: "user", content: text, timestamp: 3 },
    { role: "assistant", content: [{ type: "text", text }], timestamp: 4 },
  ];
  const original = structuredClone(messages);
  for (const sandbox of [false, true]) {
    if (sandbox) process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
    else delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
    const loaded = await discoverAndLoadExtensions([
      join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
    ], directory, directory);
    assert.deepEqual(loaded.errors, []);
    const runner = new ExtensionRunner(
      loaded.extensions, loaded.runtime, directory, SessionManager.inMemory(directory), {},
    );
    const errors = [];
    runner.onError((error) => errors.push(error));
    const projected = await runner.emitContext(messages);
    assert.deepEqual(errors, []);
    const expected = `${heading}\n${cwds.map(([host, guest]) => `    cwd: ${sandbox ? guest : host}`).join("\n")}`;
    assert.equal(projected[0].content[0].text, expected);
    assert.deepEqual(projected[0].content[1], image);
    assert.deepEqual(projected[0].details, original[0].details, "host UI metadata is unchanged");
    assert.deepEqual(projected.slice(1), original.slice(1), "other tool results and conversation text are unchanged");
    assert.deepEqual(messages, original, "saved messages keep host paths");
    assert.deepEqual(await runner.emitContext(projected), projected, "projection is idempotent after resume");
  }
});

test("native goal-first, ordinary, and resumed requests advertise guest resources", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async (t) => {
  const { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } =
    await import(sdkEntry);
  const require = createRequire(sdkEntry);
  const aiDir = require.resolve.paths("@earendil-works/pi-ai")
    .map((path) => join(path, "@earendil-works/pi-ai"))
    .find((path) => existsSync(join(path, "package.json")));
  assert.ok(aiDir);
  const aiManifest = JSON.parse(readFileSync(join(aiDir, "package.json"), "utf8"));
  const { fauxProvider, fauxAssistantMessage, fauxToolCall, InMemoryCredentialStore, getSystemMessageText } =
    await import(pathToFileURL(resolve(aiDir, aiManifest.exports["."].import)).href);
  const directory = mkdtempSync(join(tmpdir(), "guest-goal-context-"));
  const savedEnvironment = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  });
  const cwd = join(directory, "project");
  const home = join(directory, "home");
  const agentDir = join(home, ".pi/agent");
  const repositoryInstructions = join(cwd, ".agents/sandbox/AGENTS.md");
  const homeInstructions = join(home, ".agents/sandbox/AGENTS.md");
  mkdirSync(join(cwd, ".agents/sandbox"), { recursive: true });
  mkdirSync(join(home, ".agents/sandbox"), { recursive: true });
  writeFileSync(repositoryInstructions, "Repository sandbox rule.\n@nested.md\n");
  writeFileSync(join(cwd, ".agents/sandbox/nested.md"), "Nested repository sandbox rule.");
  // Dotbot installs the home rule as a symlink to source outside the active repository.
  const homeSource = join(home, "src/dotfiles/config/agents");
  mkdirSync(homeSource, { recursive: true });
  writeFileSync(join(homeSource, "sandbox-AGENTS.md"), "Home sandbox rule.\n@nested.md\n");
  symlinkSync(join(homeSource, "sandbox-AGENTS.md"), homeInstructions);
  writeFileSync(join(homeSource, "nested.md"), "Nested home sandbox rule.");
  const skillDir = join(cwd, ".agents/skills/ready-workqueue");
  mkdirSync(skillDir, { recursive: true });
  mkdirSync(agentDir, { recursive: true });
  writeFileSync(join(agentDir, "AGENTS.md"), "Ordinary host user instruction.");
  writeFileSync(join(skillDir, "SKILL.md"),
    "---\nname: ready-workqueue\ndescription: offline queue fixture\n---\nRead the queue.");
  const guestRepository = "/src/renamed-project";
  const guestCwd = `${guestRepository}/nested`;
  Object.assign(process.env, {
    HOME: home,
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_GUEST_CWD: guestCwd,
    CODEX_SANDBOX_GUEST_REPO: guestRepository,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({
      [cwd]: guestRepository,
      [home]: "/home/codex",
      [join(home, "src")]: "/src",
      [join(agentDir, "AGENTS.md")]: "/src/dotfiles/config/pi-agent/AGENTS.md",
      "/host/previous-project": "/src/previous-project",
    }),
    CODEX_SANDBOX_PREVIOUS_CWD: "/host/previous-project",
  });
  const faux = fauxProvider({ provider: "guest-goal-context", api: "anthropic-messages" });
  const requests = [];
  const capture = (context) => {
    requests.push(JSON.parse(JSON.stringify(context.messages)));
    return fauxAssistantMessage("offline answer");
  };
  // Pi's custom-message route initially sends only tool declarations. Its first
  // tool result prepares the catalog, as in the reported ls -> read failure.
  let firstGoalSystem;
  faux.setResponses([
    (context) => {
      firstGoalSystem = context.messages.filter((message) => message.role === "system")
        .map(getSystemMessageText).join("\n");
      return fauxAssistantMessage([fauxToolCall("context_probe", {})], { stopReason: "toolUse" });
    },
    capture, capture, capture,
  ]);
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: false }, retry: { enabled: false },
  });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"),
    allowModelNetwork: false, refreshOnCreate: false,
  });
  let beforeStarts = 0;
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
    additionalSkillPaths: [skillDir],
    additionalExtensionPaths: [join(root, "config/pi-agent/pi-extensions/guest-tools.ts")],
    extensionFactories: [(pi) => {
      pi.registerProvider(faux.provider);
      pi.registerTool({
        name: "context_probe", label: "context probe", description: "offline context probe",
        parameters: { type: "object", properties: {} },
        execute: async () => ({ content: [{ type: "text", text: "probe complete" }], details: {} }),
      });
      pi.on("before_agent_start", () => { beforeStarts++; });
    }],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const sessionManager = SessionManager.inMemory(cwd);
  const options = { cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager, model: faux.getModel(), tools: ["read", "context_probe"] };
  const { session, extensionsResult } = await createAgentSession(options);
  assert.deepEqual(extensionsResult.errors, []);
  t.after(() => session.dispose());
  await session.bindExtensions({});
  const goal = { customType: "pi-codex-goal", content: "/skill:ready-workqueue", display: false };
  await session.sendCustomMessage(goal, { triggerTurn: true });
  assert.equal(beforeStarts, 0, "goal-first request skips before_agent_start");
  writeFileSync(join(homeSource, "nested.md"), "Updated nested home sandbox rule.");
  writeFileSync(repositoryInstructions, "Updated repository sandbox rule.");
  await session.prompt("ordinary prompt");
  assert.equal(beforeStarts, 1);
  rmSync(homeInstructions);
  rmSync(repositoryInstructions);
  session.dispose();
  const { session: resumed } = await createAgentSession(options);
  t.after(() => resumed.dispose());
  await resumed.bindExtensions({});
  await resumed.sendCustomMessage(goal, { triggerTurn: true });
  assert.equal(beforeStarts, 1, "resumed goal also skips before_agent_start");
  assert.equal(requests.length, 3);
  const template = readFileSync(join(root, "config/agents/sandbox-context.md"), "utf8");
  const expectedSandbox = template.split("{{repository}}").join(guestRepository).trim();
  const incorrectSandbox = template.split("{{repository}}").join(guestCwd).trim();
  assert.ok(firstGoalSystem.includes(expectedSandbox), "the initial goal request also receives the sandbox context");
  const systemText = (messages) => messages.filter((message) => message.role === "system")
    .map(getSystemMessageText).join("\n");
  for (const text of [firstGoalSystem, systemText(requests[0])]) {
    for (const rule of ["Repository sandbox rule.", "Nested repository sandbox rule.",
      "Home sandbox rule.", "Nested home sandbox rule."]) {
      assert.equal(text.split(rule).length - 1, 1, `provider receives ${rule} exactly once`);
    }
    assert.ok(text.includes(`${guestRepository}/.agents/sandbox/AGENTS.md`));
    assert.ok(text.includes("/src/dotfiles/config/agents/nested.md"));
  }
  assert.ok(systemText(requests[1]).includes("Updated repository sandbox rule."));
  assert.ok(systemText(requests[1]).includes("Updated nested home sandbox rule."));
  assert.ok(!systemText(requests[1]).includes("Nested repository sandbox rule."));
  assert.ok(!systemText(requests[2]).includes("sandbox rule."), "removed roots clear historical instruction sections");
  for (const messages of requests) {
    const system = messages.filter((message) => message.role === "system")
      .map(getSystemMessageText).join("\n");
    assert.ok(system.includes(`${guestRepository}/.agents/skills/ready-workqueue/SKILL.md`), system);
    assert.ok(system.includes(`<cwd>\n${guestCwd}\n</cwd>`), system);
    assert.ok(system.includes(expectedSandbox), "provider receives the rendered template with the launch repository");
    assert.ok(system.includes("Ordinary host user instruction."), "sandbox guidance preserves normal host instructions");
    assert.ok(system.includes('/src/dotfiles/config/pi-agent/AGENTS.md'), "the host context advertises its readable source");
    assert.ok(!system.includes(incorrectSandbox), "nested cwd is not the writable root");
    assert.ok(!system.includes("{{repository}}"), "provider never receives the placeholder");
    assert.ok(!system.includes(cwd), "host repository paths never reach the provider");
    assert.ok(!system.includes(home), "host home paths never reach the provider");
    assert.ok(!system.includes("Working directory switched from"), "handoff preserves the historical system prompt");
    const userText = messages.filter((message) => message.role === "user")
      .map((message) => typeof message.content === "string" ? message.content
        : message.content.filter((block) => block.type === "text").map((block) => block.text).join("\n"))
      .join("\n");
    assert.equal(userText.split("Working directory switched from").length - 1, 1);
    assert.ok(userText.includes(`from /src/previous-project to ${guestCwd}.`));
    assert.ok(!userText.includes("/host/previous-project"), "previous directory uses the guest view too");
    assert.match(userText, /Continue the user's objective/);
    assert.match(userText, /authorizes work in the destination within that objective/);
    assert.match(userText, /Before making changes, read .*repository instructions/);
    assert.match(userText, /inspect working-copy state and change ownership/);
    assert.match(userText, /Older paths remain historical context/);
  }
  const storedSystem = sessionManager.buildSessionContext().messages
    .filter((message) => message.role === "system").map(getSystemMessageText).join("\n");
  assert.ok(storedSystem.includes(join(skillDir, "SKILL.md")), "stored catalog retains host paths");
  assert.ok(!storedSystem.includes("Working directory switched from"));
  assert.equal(sessionManager.getBranch().filter((entry) =>
    entry.type === "custom_message" && entry.customType === "sandbox-handoff").length, 1,
    "the handoff is recorded once, including after resume");
  assert.ok(!sessionManager.buildSessionContext().messages
    .some((message) => message.role === "system" && ("sandbox_context" in (message.sections ?? {})
      || "sandbox_instructions" in (message.sections ?? {}))),
    "sandbox facts and instructions are request-local");
});

test("sandbox instructions stay sandbox-only and each optional root loads independently", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async (t) => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(sdkEntry);
  const directory = mkdtempSync(join(tmpdir(), "optional-sandbox-instructions-"));
  const savedEnvironment = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  });
  const repository = join(directory, "project");
  const home = join(directory, "home");
  const repositoryFile = join(repository, ".agents/sandbox/AGENTS.md");
  const homeFile = join(home, ".agents/sandbox/AGENTS.md");
  mkdirSync(join(repository, ".agents/sandbox"), { recursive: true });
  mkdirSync(join(home, ".agents/sandbox"), { recursive: true });
  Object.assign(process.env, {
    HOME: home,
    CODEX_SANDBOX_GUEST_REPO: "/src/project",
    CODEX_SANDBOX_GUEST_CWD: "/src/project/nested",
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({ [repository]: "/src/project", [home]: "/home/codex" }),
  });
  delete process.env.CODEX_SANDBOX_PREVIOUS_CWD;
  for (const [sandbox, withHome, withRepository] of [
    [false, true, true], [true, true, true], [true, false, true],
    [true, true, false], [true, false, false],
  ]) {
    if (sandbox) process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
    else delete process.env.CODEX_SANDBOX_TOOL_CONTAINER;
    if (withHome) writeFileSync(homeFile, "Optional home rule.");
    else rmSync(homeFile, { force: true });
    if (withRepository) writeFileSync(repositoryFile, "Optional repository rule.");
    else rmSync(repositoryFile, { force: true });
    const loaded = await discoverAndLoadExtensions([
      join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
    ], repository, directory);
    assert.deepEqual(loaded.errors, []);
    const runner = new ExtensionRunner(
      loaded.extensions, loaded.runtime, repository, SessionManager.inMemory(repository), {},
    );
    const errors = [];
    runner.onError((error) => errors.push(error));
    const messages = [{ role: "system", content: "Base instructions", timestamp: 0 }];
    const projected = await runner.emitContext(messages);
    assert.deepEqual(errors, []);
    const instructions = projected[0].sections?.sandbox_instructions ?? "";
    assert.equal(instructions.includes("Optional home rule."), sandbox && withHome);
    assert.equal(instructions.includes("Optional repository rule."), sandbox && withRepository);
    assert.deepEqual(messages, [{ role: "system", content: "Base instructions", timestamp: 0 }]);
    if (!sandbox) assert.deepEqual(projected, messages);
    if (sandbox && withHome) {
      writeFileSync(homeFile, "@missing.md");
      await runner.emitContext(messages);
      assert.equal(errors.length, 1, "missing nested guidance reports an include error rather than silently skipping it");
      assert.match(errors[0].error, /instruction include does not exist/);
    }
  }
});

test("editable sandbox prose follows the launch repository and replaces stale section updates", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async () => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(sdkEntry);
  const directory = mkdtempSync(join(tmpdir(), "editable-sandbox-context-"));
  const savedEnvironment = { ...process.env };
  try {
    const extensions = join(directory, "config/pi-agent/pi-extensions");
    const agents = join(directory, "config/agents");
    mkdirSync(extensions, { recursive: true });
    mkdirSync(agents, { recursive: true });
    for (const name of ["guest-tools.ts", "guest-tools-core.ts", "pi-instruction-includes.ts"]) {
      const source = join(root, "config/pi-agent/pi-extensions", name);
      const copy = join(extensions, name);
      copyFileSync(source, copy);
      assert.deepEqual(readFileSync(copy), readFileSync(source));
    }
    Object.assign(process.env, {
      CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
      CODEX_SANDBOX_GUEST_CWD: "/src/current/nested",
      CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
    });
    delete process.env.CODEX_SANDBOX_PREVIOUS_CWD;
    const template = join(agents, "sandbox-context.md");
    const cases = [
      { repository: "/src/current", prose: "Selected: {{repository}}.", expected: "Selected: /src/current." },
      { repository: "/src/$&-other", prose: "New wording: {{repository}}; again {{repository}}.",
        expected: "New wording: /src/$&-other; again /src/$&-other." },
    ];
    for (const { repository, prose, expected } of cases) {
      process.env.CODEX_SANDBOX_GUEST_REPO = repository;
      process.env.CODEX_SANDBOX_GUEST_CWD = `${repository}/nested`;
      writeFileSync(template, prose);
      const loaded = await discoverAndLoadExtensions([join(extensions, "guest-tools.ts")], directory, directory);
      assert.deepEqual(loaded.errors, []);
      const runner = new ExtensionRunner(
        loaded.extensions, loaded.runtime, directory, SessionManager.inMemory(directory), {},
      );
      const errors = [];
      runner.onError((error) => errors.push(error));
      const messages = [
        { role: "system", content: "Original instructions", timestamp: 0 },
        { role: "system", content: "", sections: { sandbox_context: "Stale repository: /src/old" }, timestamp: 1 },
      ];
      const original = structuredClone(messages);
      const projected = await runner.emitContext(messages);
      assert.deepEqual(errors, []);
      assert.equal(projected[0].content, "Original instructions");
      assert.equal(projected[0].sections?.sandbox_context, expected);
      assert.equal(projected[1].sections.sandbox_context, expected);
      assert.deepEqual(messages, original);
      assert.deepEqual(await runner.emitContext(projected), projected);
    }
    delete process.env.CODEX_SANDBOX_GUEST_REPO;
    const missing = await discoverAndLoadExtensions([join(extensions, "guest-tools.ts")], directory, directory);
    assert.deepEqual(missing.errors, [], "an older launcher must not disable guest tools on reload");
    const runner = new ExtensionRunner(
      missing.extensions, missing.runtime, directory, SessionManager.inMemory(directory), {},
    );
    assert.ok(runner.getToolDefinition("bash"), "an older launcher keeps guest tools attached");
    const cleared = await runner.emitContext([
      { role: "system", content: "Original instructions", sections: { sandbox_context: "Stale repository: /src/old" }, timestamp: 0 },
    ]);
    assert.equal(cleared[0].sections.sandbox_context, null, "missing launch repository clears stale facts without guessing from cwd");
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  }
});

test("handoff notice survives real Codex request conversion with later directory updates", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async (t) => {
  const { convertToLlm, discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(sdkEntry);
  const require = createRequire(sdkEntry);
  const aiDir = require.resolve.paths("@earendil-works/pi-ai")
    .map((path) => join(path, "@earendil-works/pi-ai"))
    .find((path) => existsSync(join(path, "package.json")));
  assert.ok(aiDir);
  const manifest = JSON.parse(readFileSync(join(aiDir, "package.json"), "utf8"));
  const apiPath = manifest.exports["./api/*"].import.replace("*", "openai-codex-responses");
  const { stream } = await import(pathToFileURL(resolve(aiDir, apiPath)).href);
  const directory = mkdtempSync(join(tmpdir(), "codex-handoff-context-"));
  const savedEnvironment = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  });
  Object.assign(process.env, {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_GUEST_CWD: "/src/destination/nested",
    CODEX_SANDBOX_GUEST_REPO: "/src/destination",
    CODEX_SANDBOX_PREVIOUS_CWD: "/host/origin",
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({ "/host/origin": "/src/origin" }),
  });
  const loaded = await discoverAndLoadExtensions([
    join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
  ], directory, directory);
  assert.deepEqual(loaded.errors, []);
  const manager = SessionManager.inMemory(directory);
  const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, directory, manager, {});
  loaded.runtime.sendMessage = (message) => manager.appendCustomMessageEntry(
    message.customType, message.content, message.display, message.details);
  const transcript = [
    { role: "system", content: "Existing conversation.", timestamp: 1,
      sections: { cwd: "<cwd>\n/src/origin\n</cwd>" } },
    { role: "user", content: "Continue the task.", timestamp: 2 },
    { role: "system", content: "", timestamp: 3,
      sections: { cwd: "<cwd>\n/src/destination/nested\n</cwd>", project_context: "Destination instructions." } },
    { role: "user", content: "Did you see the notice?", timestamp: 4 },
  ];
  const original = structuredClone(transcript);
  for (const message of transcript) manager.appendMessage(message);
  const prefix = structuredClone(manager.getBranch());
  await runner.emit({ type: "session_start", reason: "startup" });
  await runner.emit({ type: "session_start", reason: "reload" });
  assert.deepEqual(manager.getBranch().slice(0, prefix.length), prefix, "startup and reload preserve the saved prefix");
  assert.equal(manager.getBranch().length, prefix.length + 1, "reload does not duplicate the recorded note");
  const messages = await runner.emitContext(convertToLlm(manager.buildSessionContext().messages));
  const claims = Buffer.from(JSON.stringify({ "https://api.openai.com/auth": { chatgpt_account_id: "offline-fixture" } })).toString("base64");
  for (const supportsMidConvoSystemMessages of [true, false]) {
    let payload;
    let networkCalls = 0;
    const model = {
      id: "offline-codex", name: "Offline Codex", api: "openai-codex-responses", provider: "openai-codex",
      baseUrl: "https://codex.invalid", reasoning: false, input: ["text"], contextWindow: 200000, maxTokens: 1000,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      compat: { supportsMidConvoSystemMessages },
    };
    // Stop at the public payload hook: exercise the real serializer, but never
    // send fixture credentials or conversation text to a service.
    const result = await stream(model, { messages }, {
      apiKey: `unused.${claims}.unused`, transport: "sse",
      onPayload: (body) => { payload = structuredClone(body); throw new Error("offline payload captured"); },
      fetch: async () => { networkCalls++; throw new Error("network is forbidden"); },
    }).result();
    assert.equal(result.errorMessage, "offline payload captured");
    assert.equal(networkCalls, 0);
    assert.ok(!payload.instructions.includes("Working directory switched from"), "handoff leaves Codex instructions unchanged");
    const userMessages = payload.input.filter((message) => message.role === "user");
    const userText = userMessages.map((message) => JSON.stringify(message.content)).join("\n");
    assert.equal(userText.split("Working directory switched from").length - 1, 1);
    assert.ok(JSON.stringify(userMessages.at(-1).content).includes("Working directory switched from"),
      "Codex receives the handoff at the end, not in its historical prompt");
    const rendered = [payload.instructions, ...payload.input.map((message) => JSON.stringify(message.content))].join("\n");
    assert.equal(rendered.split("Working directory switched from").length - 1, 1);
    assert.match(rendered, /from \/src\/origin to \/src\/destination\/nested\./);
    assert.match(rendered, /authorizes work in the destination within that objective/);
    assert.match(rendered, /repository instructions and inspect working-copy state and change ownership/);
    assert.match(rendered, /Destination instructions/);
    assert.ok(!rendered.includes("/host/origin"));
  }
  assert.deepEqual(transcript, original);
});

test("recorded handoffs preserve history and do not repeat on reload or ordinary session switches", {
  skip: !sdkEntry && "requires the host Pi installation",
}, async () => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(sdkEntry);
  const directory = mkdtempSync(join(tmpdir(), "recorded-handoff-"));
  const savedEnvironment = { ...process.env };
  try {
    Object.assign(process.env, {
      CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
      CODEX_SANDBOX_GUEST_CWD: "/src/current",
      CODEX_SANDBOX_GUEST_REPO: "/src/current",
      CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({
        "/host/origin": "/src/origin", "/host/current": "/src/current",
      }),
    });
    const cases = [
      { previous: undefined, reason: "startup", expected: 0 },
      { previous: "/src/current", reason: "startup", expected: 0 },
      { previous: "/host/current", reason: "startup", expected: 0 },
      { previous: "/host/origin", reason: "startup", expected: 1 },
      { previous: "/src/origin", reason: "reload", expected: 1 },
      { previous: "/src/origin", reason: "startup", pending: true, expected: 0 },
      { previous: "/src/origin", reason: "new", expected: 0 },
      { previous: "/src/origin", reason: "resume", expected: 0 },
      { previous: "/src/origin", reason: "fork", expected: 0 },
      { previous: "/src/origin", reason: "startup", existing: "current", expected: 0 },
      { previous: "/src/origin", reason: "startup", existing: "source", expected: 1 },
    ];
    for (const example of cases) {
      if (example.previous === undefined) delete process.env.CODEX_SANDBOX_PREVIOUS_CWD;
      else process.env.CODEX_SANDBOX_PREVIOUS_CWD = example.previous;
      const manager = SessionManager.inMemory(example.pending ? join(directory, "old-cwd") : directory);
      manager.appendMessage({ role: "user", content: "Existing work remains here.", timestamp: 1 });
      if (example.existing) manager.appendCustomMessageEntry("sandbox-handoff", "Older handoff", false, {
        sessionId: example.existing === "current" ? manager.getSessionId() : "prior-session-id",
      });
      const prefix = structuredClone(manager.getBranch());
      const loaded = await discoverAndLoadExtensions([
        join(root, "config/pi-agent/pi-extensions/guest-tools.ts"),
      ], directory, directory);
      assert.deepEqual(loaded.errors, []);
      const messages = [];
      loaded.runtime.sendMessage = (message, options) => {
        messages.push({ message, options });
        manager.appendCustomMessageEntry(message.customType, message.content, message.display, message.details);
      };
      const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, directory, manager, {});
      const errors = [];
      runner.onError((error) => errors.push(error));
      await runner.emit({ type: "session_start", reason: example.reason });
      if (example.reason === "startup" || example.reason === "reload") {
        await runner.emit({ type: "session_start", reason: "reload" });
      }
      assert.deepEqual(errors, []);
      assert.equal(messages.length, example.expected, JSON.stringify(example));
      assert.deepEqual(manager.getBranch().slice(0, prefix.length), prefix);
      if (example.expected) {
        assert.deepEqual(messages[0].options, { triggerTurn: false }, "a directory switch does not start new work");
        assert.match(messages[0].message.content, /from \/src\/origin to \/src\/current\./);
        assert.ok(!messages[0].message.content.includes("/host/"));
      }
    }
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  }
});
