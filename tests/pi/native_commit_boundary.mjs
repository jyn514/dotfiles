// Use the installed loader/session, not Bun's process-wide SDK module mocks.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const sdk = await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
let ai;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  try {
    const directory = join(modulesDir, "@earendil-works/pi-ai");
    const metadata = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
    ai = await import(pathToFileURL(resolve(directory, metadata.exports["."].import)).href);
    break;
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}
assert.ok(ai, "installed pi-ai public export is required");
const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

function jj(cwd, ...args) {
  const result = spawnSync("jj", args, { cwd, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

for (const mode of ["native", "guest"]) {
test(`fresh ${mode} sessions share boundaries and return exact edit/write advisories without hiding real ENOENT`, async (t) => {
  const root = await mkdtemp(join(tmpdir(), "native-commit-boundary-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "repo");
  const agentDir = join(root, "agent");
  const bin = join(root, "bin");
  await Promise.all([cwd, agentDir, bin].map(path => mkdir(path)));
  // test-environment selects native bb; exercise the repository's actual
  // agent-split wrapper explicitly rather than inventing a Babashka task.
  await symlink(join(repository, "tools/agent-split/bb"), join(bin, "bb"));
  const updates = {
    PATH: `${bin}:${process.env.PATH}`,
    CODEX_SANDBOX_TOOL_CONTAINER: mode === "guest" ? "local-regression-fixture" : undefined,
    CODEX_SANDBOX_TOOL_CONNECT: join(repository, "tools/codex-sandbox/tests/fixtures/local-tool-connect.py"),
    CODEX_SANDBOX_GUEST_CWD: cwd, CODEX_SANDBOX_GUEST_REPO: cwd,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}", CODEX_SANDBOX_PREVIOUS_CWD: undefined,
    CODEX_SANDBOX_TOOL_SOCKET: join(root, "worker.sock"), CODEX_SANDBOX_PI_TOOL_MODULE: sdkEntry,
  };
  const prior = Object.fromEntries(Object.keys(updates).map(key => [key, process.env[key]]));
  for (const [key, value] of Object.entries(updates)) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
  t.after(() => {
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  if (mode === "guest") {
    const worker = spawn("node", [join(repository, "tools/codex-sandbox/image/tool-worker.mjs")], {
      cwd, env: process.env, stdio: ["ignore", "ignore", "pipe"],
    });
    let errors = "";
    worker.stderr.on("data", data => { errors += data; });
    t.after(async () => {
      if (worker.exitCode === null && worker.signalCode === null) {
        const exited = once(worker, "exit"); worker.kill("SIGTERM"); await exited;
      }
    });
    for (let attempt = 0; attempt < 250 && !existsSync(updates.CODEX_SANDBOX_TOOL_SOCKET); attempt++) {
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    assert.ok(existsSync(updates.CODEX_SANDBOX_TOOL_SOCKET), errors);
  }
  jj(cwd, "git", "init");
  jj(cwd, "config", "set", "--repo", "user.name", "Boundary Test");
  jj(cwd, "config", "set", "--repo", "user.email", "boundary@example.invalid");
  await writeFile(join(cwd, ".gitignore"), "/target/jj-split/\n");
  await writeFile(join(cwd, "rules.md"), "alpha\nrule one\nrule two\nomega\n");
  await writeFile(join(cwd, "unrelated.txt"), "original\n");
  jj(cwd, "commit", "-m", "Base rules");
  await writeFile(join(cwd, "unrelated.txt"), "unrelated formatting\n");
  const reorganized = "alpha\nomega\n\n## Policy\nrule one\nrule two\n";
  const continued = "alpha\nomega\n\n## Policy\nsee skill one\n";
  const extracted = "alpha\nomega\n\n## Policy\nsee skill two\n";
  const edited = "alpha\nomega\n\n## Policy\nsee skill three\n";
  const editParams = { path: "rules.md", edits: [{ oldText: extracted, newText: edited }] };
  const missingParams = { path: "missing.md", edits: [{ oldText: "absent", newText: "still absent" }] };
  const faux = ai.fauxProvider({ provider: "native-commit-boundary", api: "anthropic-messages" });
  const calls = [];
  const response = (message) => (context) => { calls.push(structuredClone(context)); return message; };
  faux.setResponses([
    response(ai.fauxAssistantMessage(ai.fauxToolCall("write", { path: "rules.md", content: reorganized }), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Reorganized.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("write", { path: "rules.md", content: continued }), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Automatic continuation finished.")),
    response(ai.fauxAssistantMessage("Read-only turn finished.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("write", { path: "rules.md", content: extracted }), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Boundary warning received.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("write", { path: "rules.md", content: extracted }), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Retry finished.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("edit", missingParams), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Missing file reported.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("edit", editParams), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Edit boundary warning received.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("edit", editParams), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Edit retry finished.")),
  ]);
  let beforeSettle = 0, settled = 0;
  const recordPath = join(cwd, "target/jj-split/commit-boundary.json");
  const record = async () => {
    try { const value = await readFile(recordPath, "utf8"); return value.trim() ? JSON.parse(value) : null; }
    catch (error) { if (error.code === "ENOENT") return null; throw error; }
  };
  await mkdir(join(cwd, "target/jj-split"), { recursive: true });
  await writeFile(join(cwd, "target/jj-split/cache-fixture"), "ignored cache\n");
  const settingsManager = sdk.SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await sdk.ModelRuntime.create({
    credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const sessions = new Set();
  t.after(() => { for (const session of sessions) session.dispose(); });
  const freshSession = async () => {
    const loader = new sdk.DefaultResourceLoader({
      cwd, agentDir, settingsManager, noExtensions: true, noSkills: true,
      noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: [join(repository, `config/pi-agent/pi-extensions/${mode === "guest" ? "guest-tools" : "commit-boundary"}.ts`)],
      systemPrompt: "Execute the requested offline regression tools.",
      extensionFactories: [(pi) => {
        pi.registerProvider(faux.provider);
        pi.on("agent_before_settle", () => beforeSettle++ === 0 ? {
          entries: [{ type: "custom_message", customType: "boundary-test",
            content: "Complete the automatic continuation before settling.", display: false }],
          continue: true,
        } : undefined);
        pi.on("agent_settled", () => { settled++; });
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const { session, extensionsResult } = await sdk.createAgentSession({
      cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager: sdk.SessionManager.inMemory(cwd), model: faux.getModel(),
      tools: ["write", "edit"],
    });
    assert.deepEqual(extensionsResult.errors, []);
    await session.bindExtensions({ onError: error => assert.fail(JSON.stringify(error)) });
    sessions.add(session);
    return session;
  };
  let session = await freshSession();
  await session.prompt("Reorganize the rules and complete the automatic continuation.");
  assert.equal(settled, 1, "automatic continuation must not publish an earlier boundary");
  assert.equal(await readFile(join(cwd, "rules.md"), "utf8"), continued);
  const initialResults = session.messages.filter(message => message.role === "toolResult");
  assert.equal(initialResults.length, 2);
  assert.ok(initialResults.every(message => !message.isError), "no checkpoint may interrupt the same response's continuation");
  const captured = await record();
  assert.match(captured, /^[0-9a-f]{40,64}$/);
  assert.equal(captured, jj(cwd, "log", "-r", "@", "--no-graph", "-T", "commit_id").trim());
  assert.doesNotMatch(jj(cwd, "file", "list", "-r", captured), /target\/jj-split/);
  session.dispose();
  sessions.delete(session);
  session = await freshSession();
  await session.prompt("Do not write any files this turn.");
  assert.equal(await record(), captured, "read-only fresh session must preserve shared C");
  session.dispose();
  sessions.delete(session);
  session = await freshSession();
  await session.prompt("Make the later extraction.");
  const warningResult = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(warningResult.isError, true);
  assert.equal(warningResult.content.map(block => block.text ?? "").join("\n"), `Could not write file: ${join(cwd, "rules.md")}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`);
  assert.equal(await readFile(join(cwd, "rules.md"), "utf8"), continued);
  assert.equal(await record(), null, "warning-only turn must forget shared C");
  session.dispose();
  sessions.delete(session);
  session = await freshSession();
  await session.prompt("Retry the same extraction.");
  const retryResult = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(retryResult.isError, false);
  assert.equal(await readFile(join(cwd, "rules.md"), "utf8"), extracted);
  assert.equal(await readFile(join(cwd, "unrelated.txt"), "utf8"), "unrelated formatting\n");
  assert.match(await record(), /^[0-9a-f]{40,64}$/);
  assert.notEqual(await record(), captured, "later successful write replaces C");
  assert.doesNotMatch(jj(cwd, "file", "list", "-r", await record()), /target\/jj-split/);
  assert.equal(calls.length, 9, "all provider calls stay in the offline faux provider");

  const protectedEdit = await record();
  let nativeMissingDiagnostic;
  await assert.rejects(sdk.createEditTool(cwd).execute("native-missing-control", missingParams), error => {
    nativeMissingDiagnostic = error.message;
    return nativeMissingDiagnostic.includes("ENOENT");
  });
  await session.prompt("Attempt the edit to the genuinely missing file.");
  const missingResult = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(missingResult.isError, true);
  assert.equal(missingResult.content.map(block => block.text ?? "").join("\n"), nativeMissingDiagnostic);
  assert.equal(existsSync(join(cwd, "missing.md")), false);
  assert.equal(await record(), protectedEdit);

  await session.prompt("Make the later structured edit.");
  const editWarning = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(editWarning.isError, true);
  assert.equal(editWarning.content.map(block => block.text ?? "").join("\n"), `Could not edit file: ${join(cwd, "rules.md")}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`);
  assert.equal(await readFile(join(cwd, "rules.md"), "utf8"), extracted);
  assert.equal(await record(), null);
  await session.prompt("Retry the identical structured edit.");
  const editRetry = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(editRetry.isError, false);
  assert.equal(await readFile(join(cwd, "rules.md"), "utf8"), edited);
  assert.match(await record(), /^[0-9a-f]{40,64}$/);
  assert.equal(calls.length, 15);
});
}
