import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
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
  const agentDir = join(directory, "agent");
  const skillDir = join(cwd, ".agents/skills/ready-workqueue");
  mkdirSync(skillDir, { recursive: true });
  mkdirSync(agentDir);
  writeFileSync(join(skillDir, "SKILL.md"),
    "---\nname: ready-workqueue\ndescription: offline queue fixture\n---\nRead the queue.");
  const guestRepository = "/src/renamed-project";
  const guestCwd = `${guestRepository}/nested`;
  Object.assign(process.env, {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_GUEST_CWD: guestCwd,
    CODEX_SANDBOX_GUEST_REPO: guestRepository,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({ [cwd]: guestCwd }),
    CODEX_SANDBOX_PREVIOUS_CWD: "/src/previous-project",
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
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
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
  const goal = { customType: "pi-codex-goal", content: "/skill:ready-workqueue", display: false };
  await session.sendCustomMessage(goal, { triggerTurn: true });
  assert.equal(beforeStarts, 0, "goal-first request skips before_agent_start");
  await session.prompt("ordinary prompt");
  assert.equal(beforeStarts, 1);
  session.dispose();
  const { session: resumed } = await createAgentSession(options);
  t.after(() => resumed.dispose());
  await resumed.sendCustomMessage(goal, { triggerTurn: true });
  assert.equal(beforeStarts, 1, "resumed goal also skips before_agent_start");
  assert.equal(requests.length, 3);
  const template = readFileSync(join(root, "config/agents/sandbox-context.md"), "utf8");
  const expectedSandbox = template.split("{{repository}}").join(guestRepository).trim();
  const incorrectSandbox = template.split("{{repository}}").join(guestCwd).trim();
  assert.ok(firstGoalSystem.includes(expectedSandbox), "the initial goal request also receives the sandbox context");
  for (const messages of requests) {
    const system = messages.filter((message) => message.role === "system")
      .map(getSystemMessageText).join("\n");
    assert.ok(system.includes(`${guestCwd}/.agents/skills/ready-workqueue/SKILL.md`), system);
    assert.ok(system.includes(`<cwd>\n${guestCwd}\n</cwd>`), system);
    assert.ok(system.includes(expectedSandbox), "provider receives the rendered template with the launch repository");
    assert.ok(!system.includes(incorrectSandbox), "nested cwd is not the writable root");
    assert.ok(!system.includes("{{repository}}"), "provider never receives the placeholder");
    assert.ok(!system.includes(cwd), "host repository paths never reach the provider");
    assert.equal(system.split("This conversation moved from").length - 1, 1);
  }
  const storedSystem = sessionManager.buildSessionContext().messages
    .filter((message) => message.role === "system").map(getSystemMessageText).join("\n");
  assert.ok(storedSystem.includes(join(skillDir, "SKILL.md")), "stored catalog retains host paths");
  assert.ok(!storedSystem.includes("This conversation moved from"));
  assert.ok(!sessionManager.buildSessionContext().messages
    .some((message) => message.role === "system" && "sandbox_context" in (message.sections ?? {})),
    "sandbox facts are request-local");
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
    for (const name of ["guest-tools.ts", "guest-tools-core.ts"]) {
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

