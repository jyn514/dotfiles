// Run with dev/test-environment node --test tests/pi/native_edit_suggestions.mjs.
// The locked SDK supplies unsuggested execution. Checked fixtures preserve the
// pre-extraction fork diagnostics; the selected SDK runs loader/session checks.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { createEditToolDefinition } from "@earendil-works/pi-coding-agent";
import { createEditSuggestionsTool } from "../../config/pi-agent/pi-extensions/edit-suggestions.ts";
import { createEditSuggestionsTool as createSuggestedEdit } from "../../config/pi-agent/pi-extensions/edit-suggestions-core.ts";

const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
// Captured from the pre-extraction fork, independently of this extension.
const expectedDiagnostics = JSON.parse(await readFile(new URL("./fixtures/edit-suggestions-diagnostics.json", import.meta.url), "utf8"));
const packageDir = process.env.PI_PACKAGE_DIR;
assert.ok(packageDir, "test-environment must select the supported Pi SDK");
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const forkEntry = resolve(packageDir, manifest.exports["."].import);
const fork = await import(pathToFileURL(forkEntry).href);

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "edit-suggestions-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

async function failure(tool, input, signal) {
  try { await tool.execute("diagnostic", input, signal); }
  catch (error) { return error; }
  assert.fail("edit unexpectedly succeeded");
}

function memoryOperations(content) {
  const state = { content, reads: 0, writes: 0, paths: [] };
  const operations = {
    async access(path) { state.paths.push(path); },
    async readFile(path) { state.paths.push(path); state.reads++; return Buffer.from(state.content); },
    async writeFile(path, value) { state.paths.push(path); state.writes++; state.content = value; },
  };
  return { state, operations };
}

const diagnostics = [
  ["closest match", "start\nconst value = 'actual';\nend\n", "const value = 'actuaL';"],
  ["missing expected preview", "unrelated\n", "totally absent\nwith internal whitespace"],
  ["bounded expected preview", "unrelated\n", "z".repeat(201)],
  ["exact duplicate lines", "same\nother\nsame\n", "same"],
  ["bounded duplicate lines", "same\n".repeat(8), "same"],
  ["normalized duplicate lines", "\uFEFFsame\r\nother\r\nsame  \r\n", "same\r\n"],
  ["Unicode duplicate lines", "const x = 'same';\nconst x = ‘same’;\n", "const x = 'same';"],
  ["ambiguous closest matches", "const x = 'one';\nconst x = 'one';\n", "const x = 'onE';"],
  ["multiline closest diff", "header\nfunction a() {\n  return 123;\n}\nfooter\n", "function a() {\n  return 124;\n}"],
  ["long diff bounded", Array.from({ length: 18 }, (_, i) => `const value${i} = 'actual';`).join("\n"), Array.from({ length: 18 }, (_, i) => `const value${i} = 'actuaL';`).join("\n")],
  ["wide diff bounded", `const value = '${"a".repeat(250)}actual';`, `const value = '${"a".repeat(250)}expect';`],
  ["too large content", "z".repeat(1_000_001), "const value = 42;"],
  ["too large search", "unrelated", "z".repeat(4001)],
  // Moved with the diagnostic policy from Pi's core tools tests.
  ["centered truncation", Array.from({ length: 20 }, (_, i) => `setting ${i + 1} = true;`).join("\n") + "\n",
    Array.from({ length: 20 }, (_, i) => `setting ${i + 1} = ${i === 14 ? "false" : "true"};`).join("\n")],
  ["distant mismatches", Array.from({ length: 20 }, (_, i) => `setting ${i + 1} = true;`).join("\n") + "\n",
    Array.from({ length: 20 }, (_, i) => `setting ${i + 1} = ${i === 3 || i === 16 ? "false" : "true"};`).join("\n")],
  ["first-line mismatch", Array.from({ length: 8 }, (_, i) => `setting ${i + 1} = true;`).join("\n") + "\n",
    Array.from({ length: 8 }, (_, i) => `setting ${i + 1} = ${i === 0 ? "false" : "true"};`).join("\n")],
  ["last-line mismatch", Array.from({ length: 8 }, (_, i) => `setting ${i + 1} = true;`).join("\n") + "\n",
    Array.from({ length: 8 }, (_, i) => `setting ${i + 1} = ${i === 7 ? "false" : "true"};`).join("\n")],
  ["CRLF closest line", "header\r\nalpha\r\nshared block\r\nomega\r\nfooter\r\n", "alpha\nshared  block\nomega"],
  ["same-line typo", "const host = 'localhost';\nconst timeout = 30_000;\nstart();\n", "const timeout = 3_000;"],
  ["low-confidence closest", "alpha\nunrelated content\nomega\n", "alpha\nshared block\nomega"],
  ["exact whitespace duplicate", "a   b   c", "   "],
];

for (const [name, content, oldText] of diagnostics) {
  test(`execution diagnostic matches pre-extraction fixture: ${name}`, async t => {
    const cwd = await fixture(t);
    const input = { path: "sample.txt", edits: [{ oldText, newText: "replacement" }] };
    const candidateFile = memoryOperations(content);
    // The locked SDK predates the core empty-normalized-search/count fix.
    const candidate = name === "exact whitespace duplicate"
      ? createSuggestedEdit(fork, cwd, { operations: candidateFile.operations })
      : createEditSuggestionsTool(cwd, { operations: candidateFile.operations });
    const actual = await failure(candidate, input);
    assert.equal(actual.message, expectedDiagnostics[name]);
    if (["closest match", "multiline closest diff", "long diff bounded", "wide diff bounded"].includes(name)) {
      assert.match(actual.message, /Closest match starts at line/);
      const lines = actual.message.split("\n").slice(1);
      assert.ok(lines.length <= 12);
      assert.ok(lines.every(line => line.length <= 203));
    }
    if (name.includes("duplicate")) assert.match(actual.message, /starting at lines/);
    if (name === "ambiguous closest matches") assert.match(actual.message, /Expected/);
    assert.equal(candidateFile.state.content, content, "approximate diagnostics never mutate");
    assert.equal(candidateFile.state.writes, 0);
    assert.equal(candidateFile.state.reads, 1, "diagnostics use the authoritative read, not a reread");
  });
}

test("failed later edit reports its original index and atomically preserves all bytes", async t => {
  const cwd = await fixture(t);
  const content = "first\nconst value = 'actual';\n";
  const input = { path: "sample.txt", edits: [
    { oldText: "first", newText: "changed" },
    { oldText: "const value = 'actuaL';", newText: "replacement" },
  ] };
  const candidateFile = memoryOperations(content);
  const actual = await failure(createEditSuggestionsTool(cwd, { operations: candidateFile.operations }), input);
  assert.equal(actual.message, "Could not find edits[1].oldText in sample.txt. Closest match starts at line 2:\n- const value = 'actuaL';\n+ const value = 'actual';");
  assert.match(actual.message, /edits\[1\]\.oldText/);
  assert.equal(candidateFile.state.content, content);
  assert.equal(candidateFile.state.writes, 0);
});

for (const [name, content, edits] of [
  ["exact BOM CRLF", "\uFEFFfirst\r\nsecond\r\nthird\r\n", [{ oldText: "second", newText: "new\nline" }]],
  ["normalized match", "before  \nconst x = ‘one’;\nafter  \n", [{ oldText: "const x = 'one';", newText: "const x = 'two';" }]],
  ["disjoint batch", "first\nsecond\nthird\n", [{ oldText: "first", newText: "one" }, { oldText: "third", newText: "three" }]],
]) {
  test(`successful execution is delegated unchanged: ${name}`, async t => {
    const cwd = await fixture(t);
    const candidateFile = memoryOperations(content);
    const baselineFile = memoryOperations(content);
    const input = { path: "@sample.txt", edits };
    const result = await createEditSuggestionsTool(cwd, { operations: candidateFile.operations }).execute("success", input);
    const baseline = await createEditToolDefinition(cwd, { operations: baselineFile.operations }).execute("success", input);
    assert.deepEqual(result, baseline, "preserve details/diff/patch/navigation fields");
    assert.deepEqual(candidateFile.state, baselineFile.state, "preserve reads, writes, paths and final bytes");
    assert.equal(candidateFile.state.reads, 1);
    assert.equal(candidateFile.state.writes, 1);
  });
}

for (const [name, content, edits] of [
  ["empty", "abc", [{ oldText: "", newText: "changed" }]],
  ["overlap", "abcdef", [{ oldText: "abcd", newText: "one" }, { oldText: "cdef", newText: "two" }]],
  ["no change", "abc", [{ oldText: "abc", newText: "abc" }]],
]) {
  test(`unrelated failure remains unchanged: ${name}`, async t => {
    const cwd = await fixture(t);
    const candidateFile = memoryOperations(content);
    const baselineFile = memoryOperations(content);
    const input = { path: "sample.txt", edits };
    const actual = await failure(createEditSuggestionsTool(cwd, { operations: candidateFile.operations }), input);
    const expected = await failure(createEditToolDefinition(cwd, { operations: baselineFile.operations }), input);
    assert.equal(actual.message, expected.message);
    assert.deepEqual(candidateFile.state, baselineFile.state);
    assert.equal(candidateFile.state.writes, 0);
  });
}

test("access, read, post-write failure, and cancellation are not converted to suggestions", async t => {
  const cwd = await fixture(t);
  const input = { path: "sample.txt", edits: [{ oldText: "abc", newText: "def" }] };
  for (const operation of ["access", "readFile", "writeFile"]) {
    const marker = new Error(`failed ${operation}`);
    const candidateFile = memoryOperations("abc");
    const baselineFile = memoryOperations("abc");
    for (const file of [candidateFile, baselineFile]) {
      const original = file.operations[operation];
      file.operations[operation] = async (...args) => {
        if (operation === "writeFile") await original(...args);
        throw marker;
      };
    }
    const actual = await failure(createEditSuggestionsTool(cwd, { operations: candidateFile.operations }), input);
    const expected = await failure(createEditToolDefinition(cwd, { operations: baselineFile.operations }), input);
    assert.equal(actual.message, expected.message);
    if (operation !== "access") assert.equal(actual, marker);
    assert.deepEqual(candidateFile.state, baselineFile.state);
  }
  const file = memoryOperations("abc");
  const abort = new AbortController();
  abort.abort();
  const error = await failure(createEditSuggestionsTool(cwd, { operations: file.operations }), input, abort.signal);
  assert.match(error.message, /aborted/);
  assert.equal(file.state.reads, 0);
  assert.equal(file.state.writes, 0);
});

test("real loader registers complete prompt metadata and inherited renderer slots", async t => {
  const cwd = await fixture(t);
  const path = join(repository, "config/pi-agent/pi-extensions/edit-suggestions.ts");
  // The installed supported SDK supplies ctx.cwd; the older locked SDK does not.
  const loaded = await fork.discoverAndLoadExtensions([path], cwd, join(cwd, "agent"));
  assert.deepEqual(loaded.errors, []);
  const tool = loaded.extensions[0].tools.get("edit").definition;
  const baseline = fork.createEditToolDefinition(cwd);
  for (const field of ["name", "label", "description", "promptSnippet", "promptGuidelines", "parameters", "constrainedSampling", "renderShell"]) {
    assert.deepEqual(tool[field], baseline[field], field);
  }
  assert.equal(tool.renderCall, undefined);
  assert.equal(tool.renderResult, undefined);
  // Loader metadata is public before binding; execution needs Pi runtime APIs.
  const legacy = { path: "sample.txt", oldText: "actual", newText: "changed" };
  assert.deepEqual(tool.prepareArguments(structuredClone(legacy)), baseline.prepareArguments(structuredClone(legacy)));
  await mkdir(join(cwd, "nested"));
  const target = join(cwd, "nested", "sample.txt");
  await writeFile(target, "\uFEFFconst value = 'actual';\r\n");
  const input = { path: "@sample.txt", edits: [{ oldText: "const value = 'actuaL';", newText: "replacement" }] };
  const context = { cwd: join(cwd, "nested") };
  const executing = createSuggestedEdit(fork, context.cwd);
  await assert.rejects(executing.execute("missing", input, undefined, undefined, context), /Closest match starts at line 1/);
  assert.equal(await readFile(target, "utf8"), "\uFEFFconst value = 'actual';\r\n");
  const whitespace = { path: "@sample.txt", edits: [{ oldText: "\t  ", newText: "must not insert" }] };
  await assert.rejects(executing.execute("empty-normalized", whitespace, undefined, undefined, context), /No exact or normalized match was found/);
  assert.equal(await readFile(target, "utf8"), "\uFEFFconst value = 'actual';\r\n");
  input.edits[0].oldText = "const value = 'actual';";
  const result = await executing.execute("success", input, undefined, undefined, context);
  assert.match(result.content[0].text, /Successfully replaced/);
  assert.equal(await readFile(target, "utf8"), "\uFEFFreplacement\r\n");
  const index = await readFile(join(repository, "config/pi-agent/pi-extensions/index.ts"), "utf8");
  const settings = await readFile(join(repository, "config/pi-agent/settings.json"), "utf8");
  assert.match(index, /editSuggestions\(pi\)/);
  assert.doesNotMatch(settings, /edit-suggestions/);
});

test("offline native session delivers inherited tool results and exact successful bytes to the model", async t => {
  const cwd = await fixture(t);
  const agentDir = join(cwd, "agent");
  await mkdir(agentDir);
  const installedRequire = createRequire(forkEntry);
  let ai;
  for (const modules of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
    try {
      const directory = join(modules, "@earendil-works/pi-ai");
      const metadata = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
      ai = await import(pathToFileURL(resolve(directory, metadata.exports["."].import)).href);
      break;
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  assert.ok(ai?.fauxProvider, "installed SDK must support offline faux-provider sessions");
  const faux = ai.fauxProvider({ provider: "edit-suggestions-regression", api: "anthropic-messages" });
  const seen = [];
  const response = message => context => { seen.push(structuredClone(context)); return message; };
  const missing = { path: "sample.txt", edits: [{ oldText: "const value = 'actuaL';", newText: "changed" }] };
  const success = { path: "sample.txt", edits: [{ oldText: "const value = 'actual';", newText: "changed" }] };
  faux.setResponses([
    response(ai.fauxAssistantMessage(ai.fauxToolCall("edit", missing), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Reported the failure without mutation.")),
    response(ai.fauxAssistantMessage(ai.fauxToolCall("edit", success), { stopReason: "toolUse" })),
    response(ai.fauxAssistantMessage("Applied the exact edit.")),
  ]);
  const settingsManager = fork.SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await fork.ModelRuntime.create({
    credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const loader = new fork.DefaultResourceLoader({
    cwd, agentDir, settingsManager, noExtensions: true, noSkills: true,
    noPromptTemplates: true, noThemes: true, noContextFiles: true,
    // Use the real configured bundle, not a separately loaded candidate.
    additionalExtensionPaths: JSON.parse(await readFile(join(repository, "config/pi-agent/settings.json"), "utf8"))
      .extensions.map(path => resolve(repository, "config/pi-agent", path)),
    extensionFactories: [pi => pi.registerProvider(faux.provider)],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const { session, extensionsResult } = await fork.createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: fork.SessionManager.inMemory(cwd), model: faux.getModel(), tools: ["edit"],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  await session.bindExtensions({ onError: error => assert.fail(JSON.stringify(error)) });
  await writeFile(join(cwd, "sample.txt"), "\uFEFFconst value = 'actual';\r\n");
  await session.prompt("Try the misspelled edit.");
  assert.equal(await readFile(join(cwd, "sample.txt"), "utf8"), "\uFEFFconst value = 'actual';\r\n");
  const errorResult = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(errorResult.isError, true);
  assert.match(errorResult.content[0].text, /Closest match starts at line 1/);
  await session.prompt("Now use the exact old text.");
  const successResult = session.messages.filter(message => message.role === "toolResult").at(-1);
  assert.equal(successResult.isError, false);
  assert.ok(successResult.details.diff);
  assert.ok(successResult.details.patch);
  assert.equal(successResult.details.firstChangedLine, 1);
  assert.equal(await readFile(join(cwd, "sample.txt"), "utf8"), "\uFEFFchanged\r\n");
  const delivered = seen.at(-1).messages.filter(message => message.role === "toolResult");
  assert.equal(delivered.length, 2);
  assert.deepEqual(delivered.map(result => result.isError), [true, false]);
  assert.match(delivered[0].content[0].text, /Closest match/);
  assert.match(delivered[1].content[0].text, /Successfully replaced/);
  const selected = session.getToolDefinition("edit");
  for (const contextLines of [0, 7]) {
    settingsManager.applyOverrides({ editContextLines: contextLines });
    const before = Array.from({ length: 25 }, (_, i) => `row ${i}`).join("\n") + "\n";
    const after = before.replace("row 12", "changed");
    await writeFile(join(cwd, "sample.txt"), before);
    const result = await selected.execute("context", {
      path: "sample.txt", edits: [{ oldText: "row 12", newText: "changed" }],
    }, undefined, undefined, { cwd });
    assert.equal(result.details.diff, fork.generateDiffString(before, after, contextLines).diff);
    assert.equal(await readFile(join(cwd, "sample.txt"), "utf8"), after);
  }
});

test("guest proxy reaches the packaged suggested edit without host-local mutation or previews", async t => {
  const directory = await fixture(t);
  const cwd = join(directory, "guest");
  const host = join(directory, "host");
  await mkdir(cwd);
  await mkdir(host);
  await writeFile(join(host, "sample.txt"), "host decoy must not change");
  const packaged = join(cwd, "packaged");
  await mkdir(packaged);
  // Stage the exact selected runtime files from the real Dockerfile; a new
  // adjacent module must be both declared as an image input and copied here.
  const dockerfile = await readFile(join(repository, "tools/codex-sandbox/image/Dockerfile"), "utf8");
  const runtimeFiles = ["tool-worker.mjs", "commit-boundary-operations.mjs", "edit-suggestions-core.ts"];
  for (const name of runtimeFiles) {
    const destination = `/opt/agent-tools/bin/${name}`;
    const line = dockerfile.split("\n").find(line => line.endsWith(` ${destination}`));
    assert.ok(line, `Dockerfile must deliver ${name}`);
    const fields = line.split(/\s+/);
    assert.equal(fields[0], "COPY");
    const source = resolve(repository, fields[1]);
    const target = join(packaged, name);
    await copyFile(source, target);
    assert.deepEqual(await readFile(target), await readFile(source));
  }
  const socket = join(cwd, "worker.sock");
  const updates = {
    CODEX_SANDBOX_TOOL_CONTAINER: "edit-suggestions-fixture",
    CODEX_SANDBOX_TOOL_CONNECT: join(repository, "tools/codex-sandbox/tests/fixtures/local-tool-connect.py"),
    CODEX_SANDBOX_GUEST_CWD: cwd,
    CODEX_SANDBOX_GUEST_REPO: cwd,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
    CODEX_SANDBOX_TOOL_SOCKET: socket,
    CODEX_SANDBOX_PI_TOOL_MODULE: forkEntry,
  };
  const previous = Object.fromEntries(Object.keys(updates).map(key => [key, process.env[key]]));
  Object.assign(process.env, updates);
  let errors = "";
  const worker = spawn("bun", [join(packaged, "tool-worker.mjs")], {
    cwd, env: process.env, stdio: ["ignore", "ignore", "pipe"],
  });
  worker.stderr.on("data", chunk => { errors += chunk; });
  t.after(async () => {
    if (worker.exitCode === null && worker.signalCode === null) {
      const exited = once(worker, "exit");
      worker.kill("SIGTERM");
      await exited;
    }
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  for (let attempt = 0; attempt < 150 && !existsSync(socket) && worker.exitCode === null; attempt++) await sleep(20);
  assert.ok(existsSync(socket), errors || "packaged worker did not become ready");
  const agentDir = join(cwd, "agent");
  const loaded = await fork.discoverAndLoadExtensions([
    join(repository, "config/pi-agent/pi-extensions/index.ts"),
    join(repository, "config/pi-agent/pi-extensions/guest-tools.ts"),
  ], host, agentDir);
  assert.deepEqual(loaded.errors, []);
  assert.equal(loaded.extensions[0].tools.has("edit"), false, "native override must not replace guest execution");
  const tool = loaded.extensions[1].tools.get("edit").definition;
  const context = { cwd: host, sessionManager: { getSessionId: () => undefined, getSessionFile: () => undefined } };
  const path = join(cwd, "sample.txt");
  const bytes = "\uFEFFheader\r\nconst value = 'actual';\r\nfooter\r\n";
  await writeFile(path, bytes);
  const execute = input => tool.execute("guest-fixture", input, undefined, undefined, context);
  const approximate = { path: "@sample.txt", edits: [{ oldText: "const value = 'actuaL';", newText: "wrong" }] };
  await assert.rejects(execute(approximate), /Closest match starts at line 2/);
  assert.equal(await readFile(path, "utf8"), bytes);
  await assert.rejects(execute({ path: "sample.txt", edits: [
    { oldText: "header", newText: "changed" }, { oldText: "missing", newText: "wrong" },
  ] }), /edits\[1\]\.oldText/);
  assert.equal(await readFile(path, "utf8"), bytes);
  await writeFile(path, "same\nother\nsame\n");
  await assert.rejects(execute({ path: "sample.txt", edits: [{ oldText: "same", newText: "wrong" }] }), /starting at lines 1, 3/);
  assert.equal(await readFile(path, "utf8"), "same\nother\nsame\n");
  await writeFile(path, bytes);
  const input = { path: "sample.txt", edits: [{ oldText: "header", newText: "changed" }] };
  const result = await execute(input);
  assert.equal(await readFile(path, "utf8"), bytes.replace("header", "changed"));
  const baselinePath = join(cwd, "baseline.txt");
  await writeFile(baselinePath, bytes);
  const baseline = await fork.createEditToolDefinition(cwd).execute("baseline", { ...input, path: "baseline.txt" });
  assert.deepEqual(result.details, { ...baseline.details,
    patch: baseline.details.patch.replaceAll("baseline.txt", "sample.txt"),
  });
  await assert.rejects(execute({ path: "absent.txt", edits: [{ oldText: "x", newText: "y" }] }), /ENOENT/);
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(tool.execute("cancel", input, abort.signal, undefined, context), /cancelled/);
  assert.equal(await readFile(path, "utf8"), bytes.replace("header", "changed"));
  assert.equal(await readFile(join(host, "sample.txt"), "utf8"), "host decoy must not change");
});
