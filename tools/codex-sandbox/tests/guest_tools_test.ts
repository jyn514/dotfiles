import { test, expect, mock, spyOn } from "bun:test";
import * as childProcess from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  rewritePiResourcePaths, sessionToolInputToHost, sessionToolMetadataToGuest, sessionToolTextToGuest,
} from "../../../config/pi-agent/pi-extensions/guest-tools-core.ts";

test("host Pi resource paths are rewritten to guest paths", () => {
  const host = "/Users/jyn/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent";
  const guest = "/opt/agent-pi/src/packages/coding-agent";
  const prompt = [
    `Main documentation: ${host}/README.md`,
    `Additional docs: ${host}/docs`,
    `Examples: ${host}/examples`,
  ].join("\n");

  const rewritten = rewritePiResourcePaths(prompt, {
    [`${host}/README.md`]: `${guest}/README.md`,
    [`${host}/docs`]: `${guest}/docs`,
    [`${host}/examples`]: `${guest}/examples`,
  });

  expect(rewritten).not.toContain(host);
  expect(rewritten).toContain(`${guest}/README.md`);
  expect(rewritten).toContain(`${guest}/docs`);
  expect(rewritten).toContain(`${guest}/examples`);
});

test("host project paths are rewritten without touching sibling paths", () => {
  const host = "/Users/jyn/src/personal/lapwing/stint";
  const guest = "/src/personal/lapwing/stint";
  const prompt = [
    `Skill location: ${host}/.agents/skills/spec-review/SKILL.md`,
    `Sibling location: ${host}-old/.agents/skills/spec-review/SKILL.md`,
  ].join("\n");

  const rewritten = rewritePiResourcePaths(prompt, { [host]: guest });

  expect(rewritten).toContain(`${guest}/.agents/skills/spec-review/SKILL.md`);
  expect(rewritten).toContain(`${host}-old/.agents/skills/spec-review/SKILL.md`);
});

const sessionPaths = {
  "/host/sessions": "/guest/sessions",
  "/host/subagents": "/guest/subagents",
  "/host/project": "/src/project",
};

test("session calls translate guest selectors without rewriting queries, cursors, or unrelated tools", () => {
  for (const [tool, field, guest, host] of [
    ["read_session", "sessionFile", "/guest/subagents/parent/child.jsonl", "/host/subagents/parent/child.jsonl"],
    ["search_sessions", "cwd", "/src/project/subdir", "/host/project/subdir"],
    ["read_session", "sessionFile", "relative/session.jsonl", "relative/session.jsonl"],
    ["read_session", "sessionFile", "/guest/subagents-old/child.jsonl", "/guest/subagents-old/child.jsonl"],
    ["read_session", "sessionFile", "/host/sessions/file.jsonl", "/host/sessions/file.jsonl"],
    ["read_session", "sessionFile", "/unmapped/session.jsonl", "/unmapped/session.jsonl"],
    ["search_sessions", "cwd", "project", "project"],
    ["read", "path", "/guest/sessions/file.jsonl", "/guest/sessions/file.jsonl"],
  ]) {
    const input = { [field]: guest, query: "/guest/subagents/needle", after: "opaque-cursor" };
    sessionToolInputToHost(tool, input, sessionPaths);
    expect(input).toEqual({ [field]: host, query: "/guest/subagents/needle", after: "opaque-cursor" });
  }
  const nested = { sessionFile: "/guest/subagents/nested/file.jsonl" };
  sessionToolInputToHost("read_session", nested, { ...sessionPaths, "/special/store": "/guest/subagents/nested" });
  expect(nested.sessionFile).toBe("/special/store/file.jsonl");
  const overlapping = { sessionFile: "/src/project/child.jsonl" };
  sessionToolInputToHost("read_session", overlapping, {
    "/home/user/src": "/src", "/home/user/src/project": "/src/project",
  });
  expect(overlapping.sessionFile).toBe("/home/user/src/project/child.jsonl");
});

test("search results project only metadata and retain historical snippets", () => {
  const result = { hits: [
    { sessionFile: "/host/subagents/parent/child.jsonl", sessionCwd: "/host/project", snippet: "read /host/project/file" },
    { sessionFile: "--project--/main.jsonl", sessionCwd: "/unmapped/project", snippet: "unchanged" },
  ], count: 2 };
  const original = structuredClone(result);
  const projected = JSON.parse(sessionToolTextToGuest("search_sessions", JSON.stringify(result), {}, sessionPaths));
  expect(projected.hits[0]).toEqual({
    sessionFile: "/guest/subagents/parent/child.jsonl", sessionCwd: "/src/project", snippet: "read /host/project/file",
  });
  expect(projected.hits[1]).toEqual(result.hits[1]);
  expect(result).toEqual(original);
});

test("read results project headers and version metadata without changing transcript text or receipts", () => {
  const transcript = "# Session id — cwd: /host/project — started: today\n\n## user\n"
    + "# Session quoted — cwd: /host/project — started: yesterday\nread /host/project/file\n"
    + '# Navigation {"nextCursor":"opaque-host-receipt"}';
  const details = { sessionFile: "/host/subagents/parent/child.jsonl", nextCursor: "opaque-host-receipt",
    messages: [{ text: "/host/project/file" }] };
  const projected = sessionToolTextToGuest("read_session", transcript, details, sessionPaths);
  expect(projected.split("\n")[0]).toBe("# Session id — cwd: /src/project — started: today");
  expect(projected.slice(projected.indexOf("\n"))).toBe(transcript.slice(transcript.indexOf("\n")));
  expect(sessionToolMetadataToGuest(details, sessionPaths)).toEqual({ ...details, sessionFile: "/guest/subagents/parent/child.jsonl" });
  expect(details.sessionFile).toBe("/host/subagents/parent/child.jsonl");
  const versions = [{ index: 1, sessionFile: "/host/sessions/a.jsonl", sessionCwd: "/host/project", timestamp: "today" }];
  const text = '# Versions\n1. today — cwd: /host/project\n   sessionFile: "/host/sessions/a.jsonl"\n'
    + '   sessionFile: "/host/sessions/a.jsonl"\n'; // Preview resembling a metadata line.
  expect(sessionToolTextToGuest("read_session", text, { versions }, sessionPaths)).toBe(
    '# Versions\n1. today — cwd: /src/project\n   sessionFile: "/guest/sessions/a.jsonl"\n'
    + '   sessionFile: "/host/sessions/a.jsonl"\n');
  expect(sessionToolMetadataToGuest({ versions }, sessionPaths)).toEqual({ versions: [
    { ...versions[0], sessionFile: "/guest/sessions/a.jsonl", sessionCwd: "/src/project" },
  ] });
  expect(sessionToolTextToGuest("read_session", "read_session failed: ENOENT /host/sessions/missing.jsonl", {}, sessionPaths))
    .toBe("read_session failed: ENOENT /guest/sessions/missing.jsonl");
});

// Resolve the installed SDK's public export, as in session_side_test.ts;
// Bun does not resolve NODE_PATH and no checkout node_modules is needed.
const packageDirs = process.env.PI_PACKAGE_DIR ? [process.env.PI_PACKAGE_DIR] : [
  join(homedir(), ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"),
  "/opt/agent-pi/src/packages/coding-agent",
];
const installedDir = packageDirs.find(dir => existsSync(join(dir, "package.json")));
if (!installedDir) throw new Error("Installed Pi SDK not found; set PI_PACKAGE_DIR");
const packageDir = realpathSync(installedDir);
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const publicEntry = manifest.exports?.["."]?.import;
if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof publicEntry !== "string") {
  throw new Error(`Pi package has no supported public import export: ${packageDir}`);
}
const sdk = await import(pathToFileURL(resolve(packageDir, publicEntry)).href);
mock.module("@earendil-works/pi-coding-agent", () => sdk);
const { default: guestTools, createGuestAttachment, waitForGuestToolReady } = await import("../../../config/pi-agent/pi-extensions/guest-tools.ts");

test("guest routing projects session-tool results at request time and reverses their selectors", async () => {
  const env = {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture", CODEX_SANDBOX_GUEST_CWD: "/src/project",
    CODEX_SANDBOX_GUEST_REPO: "/src/project", CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify(sessionPaths),
  };
  const saved = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  try {
    const hooks = new Map<string, (event: any) => any>();
    guestTools({ registerTool() {}, on(name: string, hook: (event: any) => any) { hooks.set(name, hook); } } as any);
    const input = { sessionFile: "/guest/subagents/parent/child.jsonl" };
    hooks.get("tool_call")!({ toolName: "read_session", input });
    expect(input.sessionFile).toBe("/host/subagents/parent/child.jsonl");
    const messages = [
      { role: "toolResult", toolName: "search_sessions", details: { count: 1 }, content: [{ type: "text", text: JSON.stringify({ hits: [
        { sessionFile: "/host/subagents/parent/child.jsonl", sessionCwd: "/host/project", snippet: "/host/project" },
      ] }) }] },
      { role: "toolResult", toolName: "read_session", details: { sessionFile: input.sessionFile, nextCursor: "opaque" }, content: [
        { type: "text", text: "# Session id — cwd: /host/project — started: today\nuser quoted /host/project" },
      ] },
      { role: "toolResult", toolName: "read", content: [{ type: "text", text: "/host/project" }] },
    ];
    const original = structuredClone(messages);
    const projected = (await hooks.get("context_with_system")!({ messages })).messages;
    expect(JSON.parse(projected[0].content[0].text).hits[0].sessionFile).toBe("/guest/subagents/parent/child.jsonl");
    expect(projected[1].details.sessionFile).toBe("/guest/subagents/parent/child.jsonl");
    expect(projected[1].details.nextCursor).toBe("opaque");
    expect(projected[1].content[0].text).toBe("# Session id — cwd: /src/project — started: today\nuser quoted /host/project");
    expect(projected[2]).toEqual(original[2]);
    expect(messages).toEqual(original);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

// Uses the actual session-tools producer when supplied, just like the native
// reader/title composition test. Never read the user's session stores.
const readerPackage = process.env.PI_SESSION_SEARCH_PACKAGE_DIR;
test.skipIf(!readerPackage)("native session tools round-trip guest paths through installed Pi hooks", async () => {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), "pi-guest-session-tools-")));
  const hostProject = join(dir, "host-project");
  const guestProject = join(dir, "guest-project");
  const stores = ["sessions", "subagents", "codex"];
  for (const name of ["project", ...stores]) {
    mkdirSync(join(dir, `host-${name}`));
    symlinkSync(join(dir, `host-${name}`), join(dir, `guest-${name}`), "dir");
  }
  const paths = Object.fromEntries(["project", ...stores].map(name => [join(dir, `host-${name}`), join(dir, `guest-${name}`)]));
  const env = {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_GUEST_CWD: guestProject,
    CODEX_SANDBOX_GUEST_REPO: guestProject,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify(paths),
    PI_SESSION_SEARCH_ROOT: join(dir, "host-sessions"),
    PI_SESSION_SEARCH_SUBAGENT_ROOT: join(dir, "host-subagents"),
    PI_SESSION_SEARCH_CODEX_ROOT: join(dir, "host-codex"),
  };
  const saved = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  try {
    const loaded = await sdk.discoverAndLoadExtensions([
      resolve(readerPackage!), resolve(import.meta.dir, "../../../config/pi-agent/pi-extensions/guest-tools.ts"),
    ], hostProject, join(dir, "agent"));
    expect(loaded.errors).toEqual([]);
    const reader = loaded.extensions.find((extension: any) => extension.tools.has("read_session"));
    expect(reader).toBeDefined();
    const runner = new sdk.ExtensionRunner(loaded.extensions, loaded.runtime, hostProject, sdk.SessionManager.inMemory(hostProject), undefined);
    const errors: unknown[] = [];
    runner.onError((error: unknown) => errors.push(error));
    const child = sdk.SessionManager.create(hostProject, join(env.PI_SESSION_SEARCH_SUBAGENT_ROOT, "parent-key"));
    child.appendMessage({ role: "user", content: `sandbox lookup needle; historical path ${hostProject}`, timestamp: Date.now() });
    const hostFile = realpathSync(child.getSessionFile()!);
    const guestFile = rewritePiResourcePaths(hostFile, paths);

    async function call(name: string, input: Record<string, unknown>) {
      expect(await runner.emitToolCall({ type: "tool_call", toolName: name, toolCallId: "native", input })).toBeUndefined();
      const raw = await reader.tools.get(name).definition.execute("native", input, undefined, undefined, runner.createToolContext("native", undefined));
      expect(raw.isError).not.toBe(true);
      const event = { ...raw, role: "toolResult", toolName: name, toolCallId: "native", isError: false, timestamp: 1 };
      const original = structuredClone(event);
      const [projected] = await runner.emitContext([event]);
      expect(event).toEqual(original); // Stored results and host title lookup keep host paths.
      expect(errors).toEqual([]);
      return { raw, projected };
    }

    const searchInput = { query: "sandbox lookup needle", cwd: guestProject };
    const found = await call("search_sessions", searchInput);
    const hits = JSON.parse(found.projected.content[0].text).hits;
    expect(hits).toHaveLength(1);
    expect(hits[0].sessionFile).toBe(guestFile);
    expect(hits[0].sessionCwd).toBe(guestProject);
    expect(hits[0].snippet).toContain(hostProject);
    // The advertised path must also work with a filesystem reader in the guest
    // view, not only after reversing it for another host tool.
    const filesystemRead = await sdk.createReadTool(guestProject).execute("guest-read", { path: guestFile });
    expect(filesystemRead.content[0].text).toContain("sandbox lookup needle");
    const readInput = { sessionFile: hits[0].sessionFile, maxMessages: 1 };
    const read = await call("read_session", readInput);
    expect(read.projected.details.sessionFile).toBe(guestFile);
    expect(read.projected.content[0].text).toContain(`— cwd: ${guestProject} — started:`);
    expect(read.projected.content[0].text).toContain(`historical path ${hostProject}`);
    expect(read.projected.details.nextCursor).toBe(read.raw.details.nextCursor);
    child.appendMessage({ role: "user", content: "later child message", timestamp: Date.now() });
    const continued = await call("read_session", { sessionFile: guestFile, after: read.projected.details.nextCursor });
    expect(continued.projected.content[0].text).toContain("later child message");
    expect(continued.projected.content[0].text).not.toContain("sandbox lookup needle");

    for (const name of ["a", "b"]) {
      writeFileSync(join(env.PI_SESSION_SEARCH_CODEX_ROOT, `${name}.jsonl`), [
        { type: "session_meta", payload: { id: "versioned-thread", cwd: hostProject, timestamp: "2026-10-27T10:00:00Z" } },
        { type: "response_item", payload: { type: "message", role: "user", content: [{ type: "input_text", text: `preview ${hostProject}` }] } },
      ].map(row => JSON.stringify(row)).join("\n") + "\n");
    }
    const versions = await call("read_session", { sessionId: "versioned-thread" });
    expect(versions.projected.details.versions).toHaveLength(2);
    for (const version of versions.projected.details.versions) {
      expect(version.sessionFile).toStartWith(join(dir, "guest-codex"));
      expect(version.sessionCwd).toBe(guestProject);
      expect(versions.projected.content[0].text).toContain(`sessionFile: ${JSON.stringify(version.sessionFile)}`);
    }
    expect(versions.projected.content[0].text).toContain(`preview ${hostProject}`);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

async function eventually(predicate: () => boolean) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await Bun.sleep(20);
  }
  throw new Error("connector did not reach expected state");
}

test("guest startup waits for private worker readiness without polling", async () => {
  const dir = mkdtempSync(join(tmpdir(), "pi-guest-ready-"));
  const ready = join(dir, "ready");
  try {
    const waiting = waitForGuestToolReady(ready);
    await Bun.sleep(20);
    writeFileSync(ready, "", { mode: 0o600 });
    await waiting;

    chmodSync(ready, 0o644);
    await expect(waitForGuestToolReady(ready)).rejects.toThrow("invalid readiness");

    rmSync(ready);
    writeFileSync(join(dir, "target"), "", { mode: 0o600 });
    symlinkSync(join(dir, "target"), ready);
    await expect(waitForGuestToolReady(ready)).rejects.toThrow("invalid readiness");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("registered tools and human bash snapshot their own public invocation context", async () => {
  const dir = mkdtempSync(join(tmpdir(), "pi-guest-metadata-"));
  // A holds its transport open while B changes the context and executes.
  const connector = join(import.meta.dir, "../sandbox-tool-connect");
  const env = {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_TOOL_CONNECT: connector,
    CODEX_SANDBOX_TOOL_COMMAND: JSON.stringify(["python3", join(import.meta.dir, "fixtures/guest-tool-metadata.py")]),
    CODEX_SANDBOX_GUEST_CWD: dir,
    CODEX_SANDBOX_GUEST_REPO: dir,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: JSON.stringify({
      "/host/sessions": "/guest/sessions",
      "/host/subagent-runs": "/guest/subagent-runs",
    }),
    CODEX_GUEST_CALL_TEST_DIR: dir,
    PI_CALL_MODEL: "stale-env",
    PI_MODEL_FILE: join(dir, "model.json"),
  };
  writeFileSync(env.PI_MODEL_FILE, '{"modelId":"stale-file"}');
  const previous = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  const tools = new Map<string, any>();
  const hooks = new Map<string, any>();
  try {
    guestTools({ registerTool: (tool: any) => tools.set(tool.name, tool),
      on: (name: string, hook: any) => hooks.set(name, hook) } as any);
    let sessionId = "session-a";
    let sessionFile: string | undefined = "/host/sessions/a.jsonl";
    const ctx = { model: { provider: "provider-a", id: "model-a" }, sessionManager: {
      getSessionId: () => sessionId, getSessionFile: () => sessionFile,
    } };
    const params = { command: "pause", model: "model-selected-parameter" };
    const a = tools.get("bash").execute("a", params, undefined, undefined, ctx);
    await eventually(() => existsSync(join(dir, "started")));
    // Mutate the actual model object, not just the context reference.
    ctx.model.provider = "provider-b";
    ctx.model.id = "model-b";
    // Another environment selection must not split the already-registered
    // tools' transport, prompt paths, and per-invocation session projection.
    process.env.CODEX_SANDBOX_TOOL_CONNECT = join(dir, "not-a-connector");
    process.env.CODEX_SANDBOX_TOOL_CONTAINER = "another-worker";
    process.env.CODEX_SANDBOX_TOOL_COMMAND = JSON.stringify(["/bin/false"]);
    process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = "not-json";
    sessionId = "session-b";
    sessionFile = "/host/sessions/b.jsonl";
    const b = await tools.get("bash").execute("b", { command: "b" }, undefined, undefined, ctx);
    writeFileSync(join(dir, "release"), "");
    const aResult = await a;
    expect(b).toEqual({ tool: "bash", params: { command: "b" },
      model: { provider: "provider-b", modelId: "model-b" },
      session: { id: "session-b", file: "/guest/sessions/b.jsonl" } });
    expect(aResult).toEqual({ tool: "bash", params,
      model: { provider: "provider-a", modelId: "model-a" },
      session: { id: "session-a", file: "/guest/sessions/a.jsonl" } });

    const human = hooks.get("user_bash")({ command: "human" }, ctx);
    ctx.model.id = "later-model";
    sessionId = "later-session";
    sessionFile = undefined;
    expect(await human.operations.exec("human", dir, { onData() {} })).toEqual({
      tool: "user_bash", params: { command: "human" },
      model: { provider: "provider-b", modelId: "model-b" },
      session: { id: "session-b", file: "/guest/sessions/b.jsonl" },
    });
    const ephemeral = await tools.get("bash").execute("ephemeral", {}, undefined, undefined, ctx);
    expect(ephemeral.session).toEqual({ id: "later-session", file: null });
    sessionFile = "/host/subagent-runs/parent/child.jsonl";
    const subagent = await tools.get("bash").execute("subagent", {}, undefined, undefined, ctx);
    expect(subagent.session).toEqual({ id: "later-session", file: "/guest/subagent-runs/parent/child.jsonl" });
    // Keep unexposed locations visible: an omitted path would hide missing mounts.
    sessionFile = "/host/unexposed-subagents/run.jsonl";
    const unexposed = await tools.get("bash").execute("unexposed", {}, undefined, undefined, ctx);
    expect(unexposed.session).toEqual({ id: "later-session", file: sessionFile });
    sessionId = "";
    for (const tool of tools.values()) {
      const result = await tool.execute("unknown", {}, undefined, undefined, { ...ctx, model: undefined });
      expect(result.model).toBeNull();
      expect(result.session).toBeNull();
    }
    const unknown = hooks.get("user_bash")({}, { ...ctx, model: undefined });
    expect((await unknown.operations.exec("unknown", dir, { onData() {} })).model).toBeNull();
    expect(process.env.PI_CALL_MODEL).toBe("stale-env");
    expect(readFileSync(env.PI_MODEL_FILE, "utf8")).toBe('{"modelId":"stale-file"}');

    // Cancellation traverses the production bound connector and reaches only
    // its exec-replaced client. A later independent channel remains usable.
    rmSync(join(dir, "started"));
    rmSync(join(dir, "release"));
    const controller = new AbortController();
    const cancelled = tools.get("bash").execute("cancelled", { command: "pause" }, controller.signal, undefined, ctx);
    await eventually(() => existsSync(join(dir, "started")));
    controller.abort();
    await expect(cancelled).rejects.toThrow("guest tool cancelled");
    expect((await tools.get("bash").execute("after-cancellation", {}, undefined, undefined, ctx)).tool).toBe("bash");

    // A new owner (including /reload) binds the new selection rather than a
    // module-import singleton. Its failed channel cannot fall back to the old.
    process.env.CODEX_SANDBOX_TOOL_CONNECT = connector;
    process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({ "/host/sessions": "/new/sessions" });
    const reloaded = new Map<string, any>();
    guestTools({ registerTool: (tool: any) => reloaded.set(tool.name, tool), on() {} } as any);
    await expect(reloaded.get("bash").execute("new-owner", {}, undefined, undefined, ctx))
      .rejects.toThrow("guest tool transport ended (1)");
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

// Exercise the real pipe, production bound connector, and attachment parser.
// Acknowledge bytes only after Readable.push delivers them: the producer cannot
// write the next fragment early and let the OS coalesce our intended boundary.
async function callWithFragments(chunks: Buffer[], { stderr = false, status = 0,
  onUpdate = (_result: any) => {}, onData = (_data: Buffer) => {} } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "pi-guest-fragments-"));
  const spawn = childProcess.spawn;
  let received = 0;
  let released = 0;
  const boundaries = chunks.map((chunk) => chunk.length);
  for (let i = 1; i < boundaries.length; i++) boundaries[i] += boundaries[i - 1];
  const spy = spyOn(childProcess, "spawn").mockImplementation((...args: Parameters<typeof spawn>) => {
    const child = spawn(...args);
    const stream = stderr ? child.stderr! : child.stdout!;
    const push = stream.push;
    stream.push = function (chunk, encoding) {
      const result = push.call(this, chunk, encoding);
      if (chunk) {
        received += chunk.length;
        while (released < boundaries.length - 1 && received >= boundaries[released]) {
          writeFileSync(join(dir, String(released++)), "");
        }
      }
      return result;
    };
    return child;
  });
  try {
    const attachment = createGuestAttachment({
      CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
      CODEX_SANDBOX_TOOL_CONNECT: join(import.meta.dir, "../sandbox-tool-connect-bound"),
      CODEX_SANDBOX_TOOL_COMMAND: JSON.stringify(["python3", join(import.meta.dir, "fixtures/guest-tool-fragments.py")]),
    })!;
    return await attachment.call("read", { chunks: chunks.map(chunk => chunk.toString("base64")),
      release: dir, stderr, status }, { model: null, session: null }, undefined, onUpdate, onData);
  } finally {
    spy.mockRestore();
    rmSync(dir, { recursive: true, force: true });
  }
}

function guestFrame(frame: unknown): Buffer {
  // Same UTF-8 JSON-line bytes as the existing tool-worker.mjs producer.
  return Buffer.from(`${JSON.stringify(frame)}\n`);
}

for (const character of ["é", "中", "🙂"]) {
  for (let split = 1; split < Buffer.byteLength(character); split++) {
    test(`guest transport preserves update/result UTF-8 ${character} split ${split}`, async () => {
      const text = `first line\n${character}\nlast line`;
      const update = { content: [{ type: "text", text }] };
      const result = { ...update, details: { done: true } };
      const first = guestFrame({ kind: "update", result: update });
      const last = guestFrame({ kind: "result", result });
      const bytes = Buffer.concat([first, last]);
      const a = first.indexOf(Buffer.from(character)) + split;
      const b = first.length + last.indexOf(Buffer.from(character)) + split;
      const updates: unknown[] = [];
      expect(await callWithFragments([bytes.subarray(0, a), bytes.subarray(a, b), bytes.subarray(b)], {
        onUpdate: value => updates.push(value),
      })).toEqual(result);
      expect(updates).toEqual([update]);
    });

    test(`guest transport preserves failure stderr UTF-8 ${character} split ${split}`, async () => {
      const text = `connector failed:\n${character}\nlast line`;
      const bytes = Buffer.from(text);
      const at = bytes.indexOf(Buffer.from(character)) + split;
      await expect(callWithFragments([bytes.subarray(0, at), bytes.subarray(at)], { stderr: true, status: 7 }))
        .rejects.toThrow(text);
    });
  }
}

test("guest transport preserves ASCII frames, data bytes, and multiple records per chunk", async () => {
  const updates: unknown[] = [];
  const data: Buffer[] = [];
  const binary = Buffer.from([0, 255, 128, 10]);
  expect(await callWithFragments([Buffer.concat([
    guestFrame({ kind: "update", result: "progress\nnext line" }),
    guestFrame({ kind: "data", data: binary.toString("base64") }),
    guestFrame({ kind: "result", result: "done" }),
  ])], { onUpdate: value => updates.push(value), onData: value => data.push(value) })).toBe("done");
  expect(updates).toEqual(["progress\nnext line"]);
  expect(data).toEqual([binary]);
});

test("guest transport retains malformed JSON and incomplete-record failures", async () => {
  await expect(callWithFragments([Buffer.from("not JSON\n")])).rejects.toBeInstanceOf(SyntaxError);
  await expect(callWithFragments([Buffer.from('{"kind":"result","result":"no newline"}')]))
    .rejects.toThrow("guest tool transport ended (0)");
  await expect(callWithFragments([Buffer.from([0xe2, 0x82])])).rejects.toThrow("guest tool transport ended (0)");
  await expect(callWithFragments([])).rejects.toThrow("guest tool transport ended (0)");
  await expect(callWithFragments([guestFrame({ kind: "error", message: "worker refused" })]))
    .rejects.toThrow("worker refused");
});

test("guest transport retains replacement decoding for malformed bytes and stderr EOF", async () => {
  expect(await callWithFragments([Buffer.concat([
    Buffer.from('{"kind":"result","result":"'), Buffer.from([0xff]), Buffer.from('"}\n'),
  ])])).toBe("�");
  await expect(callWithFragments([Buffer.concat([Buffer.from("failure: "), Buffer.from([0xe2, 0x82])])], {
    stderr: true, status: 1,
  })).rejects.toThrow("failure: �");
});

test("guest transport retains the stderr tail limit in UTF-16 units, not bytes", async () => {
  const text = "prefix:" + "中".repeat(4096);
  try {
    await callWithFragments([Buffer.from(text)], { stderr: true, status: 1 });
    throw new Error("expected transport failure");
  } catch (error) {
    expect((error as Error).message).toBe(text.slice(-4096));
  }
});
