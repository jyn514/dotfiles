import { test, expect, mock } from "bun:test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { createConnection } from "node:net";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Use the installed SDK's public exports, including its real edit matching,
// normalization, file-mutation queue and write implementation (not test doubles).
const packageDirs = process.env.PI_PACKAGE_DIR ? [process.env.PI_PACKAGE_DIR] : [
  join(homedir(), ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"),
  "/opt/agent-pi/src/packages/coding-agent",
];
const installed = packageDirs.find(path => existsSync(join(path, "package.json")));
if (!installed) throw new Error("Installed Pi SDK not found; set PI_PACKAGE_DIR");
const packageDir = realpathSync(installed);
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const publicEntry = manifest.exports?.["."]?.import;
if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof publicEntry !== "string") {
  throw new Error("Installed SDK has no supported public import export");
}
const sdkURL = pathToFileURL(resolve(packageDir, publicEntry)).href;
const sdk = await import(sdkURL);
mock.module("@earendil-works/pi-coding-agent", () => sdk);
const { default: guestTools } = await import("../../../config/pi-agent/pi-extensions/guest-tools.ts");
const { default: commitBoundary } = await import("../../../config/pi-agent/pi-extensions/commit-boundary.ts");
const root = resolve(import.meta.dir, "../../..");
const head = Array.from({ length: 12 }, (_, n) => `head ${n}\n`).join("");
const tail = Array.from({ length: 12 }, (_, n) => `tail ${n}\n`).join("");
const section = "Instructions\nKeep exact words.\nPreserve this section.\n\n";
const base = head + section + tail + "footer\n";
const dirtyBase = head + section + tail + "footer  \n";
const reorganized = section + head + tail + "footer  \n";
const extracted = "See the extracted skill.\n\n" + head + tail + "footer  \n";

async function eventually(predicate: () => boolean, detail: () => string = () => "") {
  for (let attempt = 0; attempt < 250; attempt++) {
    if (predicate()) return;
    await Bun.sleep(20);
  }
  throw new Error(`commit-boundary fixture did not become ready: ${detail()}`);
}

async function fixture(mode: "guest" | "native", checkerBarrier = false) {
  const directory = mkdtempSync(join(realpathSync(tmpdir()), "pi-commit-boundary-"));
  const repo = join(directory, "repo");
  const bin = join(directory, "bin");
  mkdirSync(repo); mkdirSync(bin);
  // Only select the public bb dispatcher; retain dev/test-environment's real
  // local jj and private HOME. No proxy endpoint or host repository is used.
  symlinkSync(checkerBarrier
    ? join(import.meta.dir, "fixtures/commit-boundary-bb.py")
    : join(root, "libexec/agent-wrappers/bb"), join(bin, "bb"));
  const updates: Record<string, string | undefined> = {
    PATH: `${bin}:${process.env.PATH}`,
    BB_SOURCE_ROOT: root,
    BB_REAL: process.env.DOTFILES_TEST_BB_REAL || Bun.which("bb") || undefined,
    CODEX_SANDBOX_TOOL_CONTAINER: mode === "guest" ? "local-regression-fixture" : undefined,
    // Cancellation/race tests use the existing exec-based connector directly:
    // SIGTERM closes its actual socket and reaches the worker AbortController.
    CODEX_SANDBOX_TOOL_CONNECT: join(import.meta.dir, checkerBarrier
      ? "fixtures/local-tool-connect.py" : "fixtures/commit-boundary-connect.py"),
    CODEX_SANDBOX_GUEST_CWD: repo,
    CODEX_SANDBOX_GUEST_REPO: repo,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
    CODEX_SANDBOX_TOOL_SOCKET: join(directory, "worker.sock"),
    CODEX_SANDBOX_PI_TOOL_MODULE: sdkURL,
    COMMIT_BOUNDARY_TEST_CONTROL: directory,
    COMMIT_BOUNDARY_TEST_BB_DISPATCHER: join(root, "libexec/agent-wrappers/bb"),
  };
  const previous = Object.fromEntries(Object.keys(updates).map(key => [key, process.env[key]]));
  for (const [key, value] of Object.entries(updates)) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
  let worker: ChildProcess | undefined;
  let workerErrors = "";
  const file = (name: string) => join(repo, name);
  const read = (name: string) => readFileSync(file(name), "utf8");
  const jj = (...args: string[]) => {
    const result = spawnSync("jj", args, { cwd: repo, env: process.env, encoding: "utf8", timeout: 30000 });
    if (result.status !== 0) throw new Error(`jj ${args.join(" ")}: ${result.error || result.stderr}`);
    return result.stdout;
  };
  const tools = new Map<string, any>();
  const hooks = new Map<string, any[]>();
  let session = "boundary-session-a";
  const ctx = { cwd: repo, model: { provider: "fixture", id: "boundary-model" }, sessionManager: {
    getSessionId: () => session, getSessionFile: () => undefined,
  } };
  const hook = async (name: string, event: any = {}) => {
    for (const handler of hooks.get(name) || []) await handler(event, ctx);
  };
  const requests = () => existsSync(join(directory, "requests.jsonl"))
    ? readFileSync(join(directory, "requests.jsonl"), "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
  const replies = () => existsSync(join(directory, "replies.jsonl"))
    ? readFileSync(join(directory, "replies.jsonl"), "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
  const close = async () => {
    // Release any delayed terminal reply even on assertion failure.
    writeFileSync(join(directory, "release"), "");
    writeFileSync(join(directory, "checker-release"), "");
    if (worker && worker.exitCode === null && worker.signalCode === null) {
      const exited = once(worker, "exit");
      worker.kill("SIGTERM");
      await exited;
    }
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    rmSync(directory, { recursive: true, force: true });
  };
  try {
    jj("git", "init", "--colocate");
    jj("config", "set", "--repo", "user.name", "Commit boundary regression");
    jj("config", "set", "--repo", "user.email", "boundary@example.invalid");
    writeFileSync(file(".gitignore"), "/target/jj-split/\n");
    writeFileSync(file("note.txt"), base);
    writeFileSync(file("unrelated.txt"), "formatting\n");
    writeFileSync(file("unchanged.txt"), "original\n");
    jj("commit", "-m", "owned regression baseline");
    // Pre-existing formatting is dirty both in the target and a separate file;
    // the structured reorganization must preserve it, not claim ownership.
    writeFileSync(file("note.txt"), dirtyBase);
    writeFileSync(file("unrelated.txt"), "formatting  \n");
    if (mode === "guest") {
      worker = spawn("node", [join(root, "tools/codex-sandbox/image/tool-worker.mjs")], {
        cwd: repo, env: process.env, stdio: ["ignore", "ignore", "pipe"],
      });
      worker.stderr!.on("data", data => { workerErrors += data.toString(); });
      await eventually(() => existsSync(updates.CODEX_SANDBOX_TOOL_SOCKET!), () => workerErrors);
    }
    const recordPath = file("target/jj-split/commit-boundary.json");
    const record = () => {
      if (!existsSync(recordPath)) return null;
      const contents = readFileSync(recordPath, "utf8");
      return contents.trim() ? JSON.parse(contents) : null;
    };
    const install = () => {
      // Reconstruct all extension state; the guest protocol worker stays alive.
      // Only the common on-workspace record can carry the boundary forward.
      tools.clear(); hooks.clear();
      const pi = {
        registerTool: (tool: any) => tools.set(tool.name, tool),
        on: (name: string, handler: any) => hooks.set(name, [...(hooks.get(name) || []), handler]),
      };
      (mode === "guest" ? guestTools : commitBoundary)(pi as any);
    };
    install();
    let calls = 0;
    const execute = (name: "edit" | "write", params: any, signal?: AbortSignal) => tools.get(name).execute(
      `boundary-${++calls}`, params, signal, undefined, ctx,
    );
    return { directory, repo, file, read, jj, tools, hook, execute, requests, replies, close, record, recordPath,
      reconstruct: async () => {
        await hook("session_shutdown");
        session += "-fresh";
        install();
        await hook("session_start", { reason: "startup" });
      },
      // A second editing session can settle through the production internal
      // endpoint while this session's file check is still awaiting its result.
      capture: () => new Promise<void>((resolve, reject) => {
        const socket = createConnection(updates.CODEX_SANDBOX_TOOL_SOCKET!);
        let data = "";
        socket.on("error", reject);
        socket.on("connect", () => socket.write(JSON.stringify({
          tool: "commit_boundary_checkpoint", params: {}, model: null, session: null,
        }) + "\n"));
        socket.on("data", chunk => {
          data += chunk;
          if (!data.includes("\n")) return;
          const frame = JSON.parse(data.split("\n")[0]);
          socket.end();
          if (frame.kind === "result") resolve(); else reject(new Error(frame.message));
        });
      }),
      session: (id: string) => { session = id; },
      control: (value: any) => writeFileSync(join(directory, "control.json"), JSON.stringify(value)),
      reorganize: () => execute("edit", { path: "note.txt", edits: [{ oldText: dirtyBase, newText: reorganized }] }),
      extract: () => execute("write", { path: "note.txt", content: extracted }),
    };
  } catch (error) { await close(); throw error; }
}

async function warning(action: Promise<any>, path: string) {
  const result = await action;
  expect(result.isError).toBe(true);
  const message = result.content.map((item: any) => item.text || "").join("\n");
  expect(message).toBe(`Could not write file: ${path}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`);
  return message;
}

for (const mode of ["guest", "native"] as const) {
  test(`${mode}: real splitter warns before extraction; identical retry writes and preserves unrelated dirty hunk`, async () => {
    const f = await fixture(mode);
    try {
      expect((await f.reorganize()).isError).not.toBe(true);
      expect(f.read("note.txt")).toBe(reorganized);
      // Neither tool iterations nor a read-only settlement create an extra
      // boundary; the registered settled lifecycle captures the actual repo.
      await f.hook("agent_settled", { aborted: false });
      await f.hook("agent_settled", { aborted: false });
      const before = statSync(f.file("note.txt"), { bigint: true });
      await warning(f.extract(), f.file("note.txt"));
      expect(f.read("note.txt")).toBe(reorganized);
      const after = statSync(f.file("note.txt"), { bigint: true });
      expect([after.ino, after.size, after.mtimeNs, after.ctimeNs]).toEqual(
        [before.ino, before.size, before.mtimeNs, before.ctimeNs]);
      // A warning-only response must not capture again or revive the boundary.
      await f.hook("agent_settled", { aborted: false });
      expect((await f.extract()).isError).not.toBe(true);
      expect(f.read("note.txt")).toBe(extracted);
      expect(f.read("unrelated.txt")).toBe("formatting  \n");
      expect(f.jj("diff", "--git", "--", "unrelated.txt")).toContain("+formatting  ");
      if (mode === "guest") {
        const requests = f.requests();
        expect(requests.filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);
        const writes = requests.filter(r => r.tool === "write");
        expect(writes).toHaveLength(2);
        expect(requests.every(r => r.checkpoint === undefined)).toBe(true);
        expect(writes[0].params).toEqual({ path: "note.txt", content: extracted });
        expect(writes[1].params).toEqual(writes[0].params);
        const rejected = f.replies().find(r => r.kind === "result" && r.result?.isError);
        expect(rejected.result.content.map((item: any) => item.text || "").join("\n")).toBe(
          `Could not write file: ${f.file("note.txt")}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`);
        expect(f.replies().every(r => r.boundary === undefined)).toBe(true);
      }
    } finally { await f.close(); }
  }, 60000);
}

test("guest: edit refusal has the exact advisory; genuine missing-file diagnostics survive unchanged", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    const params = { path: "note.txt", edits: [{ oldText: reorganized, newText: extracted }] };
    const before = statSync(f.file("note.txt"), { bigint: true });
    const expected = `Could not edit file: ${f.file("note.txt")}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`;
    const refused = await f.execute("edit", params);
    expect(refused.isError).toBe(true);
    expect(refused.content.map((item: any) => item.text || "").join("\n")).toBe(expected);
    const terminal = f.replies().at(-1);
    expect(terminal.kind).toBe("result");
    expect(terminal.result).toEqual(refused);
    expect(f.read("note.txt")).toBe(reorganized);
    const after = statSync(f.file("note.txt"), { bigint: true });
    expect([after.ino, after.size, after.mtimeNs, after.ctimeNs]).toEqual(
      [before.ino, before.size, before.mtimeNs, before.ctimeNs]);
    expect(captured).toMatch(/^[0-9a-f]{40,64}$/);
    expect(f.record()).toBeNull();
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBeNull();
    expect((await f.execute("edit", params)).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);

    const missing = { path: "missing.txt", edits: [{ oldText: "absent", newText: "still absent" }] };
    const nativeError = await sdk.createEditTool(f.repo).execute("native-missing-control", missing)
      .then(() => { throw new Error("Native missing-file control unexpectedly succeeded"); }, (error: Error) => error.message);
    expect(nativeError).toContain("ENOENT");
    await expect(f.execute("edit", missing)).rejects.toThrow(nativeError);
    expect(f.replies().at(-1).message).toBe(nativeError);
    expect(existsSync(f.file("missing.txt"))).toBe(false);
  } finally { await f.close(); }
}, 60000);

test("native: independent JJ working copies never share captures or retirement", async () => {
  const a = await fixture("native");
  let b: Awaited<ReturnType<typeof fixture>> | undefined;
  try {
    await a.reorganize();
    await a.hook("agent_settled", { aborted: false });
    const capturedA = a.record();
    b = await fixture("native");
    expect(a.jj("workspace", "root").trim()).not.toBe(b.jj("workspace", "root").trim());
    expect(b.record()).toBeNull();
    // A's protected selection must not cause a first-edit warning in B.
    expect((await b.extract()).isError).not.toBe(true);
    await b.hook("agent_settled", { aborted: false });
    const capturedB = b.record();
    expect(capturedB).toMatch(/^[0-9a-f]{40,64}$/);
    expect(a.record()).toBe(capturedA);
    await warning(a.extract(), a.file("note.txt"));
    expect(a.record()).toBeNull();
    expect(b.record()).toBe(capturedB);
    // Capturing A's retry must not replace B's independently protected work.
    await a.extract();
    await a.hook("agent_settled", { aborted: false });
    expect(a.record()).toMatch(/^[0-9a-f]{40,64}$/);
    expect(b.record()).toBe(capturedB);
    expect(b.read("note.txt")).toBe(extracted);
  } finally {
    // The nested fixtures restore process environment in reverse order.
    if (b) await b.close();
    await a.close();
  }
}, 60000);

test("guest: fresh extension sessions share the workspace record; read-only preserves it and warning-only forgets it", async () => {
  const f = await fixture("guest");
  try {
    mkdirSync(f.file("target/jj-split"), { recursive: true });
    writeFileSync(f.file("target/jj-split/cache-fixture"), "ignored cache\n");
    await f.hook("session_start", { reason: "startup" });
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    expect(captured).toMatch(/^[0-9a-f]{40,64}$/);
    expect(captured).toBe(f.jj("log", "-r", "@", "--no-graph", "-T", "commit_id").trim());
    expect(f.jj("file", "list", "-r", captured)).not.toContain("target/jj-split");

    await f.reconstruct();
    expect(f.record()).toBe(captured);
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBe(captured);
    expect(f.requests().filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);

    await f.reconstruct();
    const before = statSync(f.file("note.txt"), { bigint: true });
    await warning(f.extract(), f.file("note.txt")); // First write in this fresh extension session.
    expect(f.read("note.txt")).toBe(reorganized);
    const after = statSync(f.file("note.txt"), { bigint: true });
    expect([after.ino, after.size, after.mtimeNs, after.ctimeNs]).toEqual(
      [before.ino, before.size, before.mtimeNs, before.ctimeNs]);
    expect(f.record()).toBeNull();
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBeNull();
    expect(f.requests().filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);

    await f.reconstruct();
    expect((await f.extract()).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toMatch(/^[0-9a-f]{40,64}$/);
    expect(f.record()).not.toBe(captured);
    expect(f.jj("file", "list", "-r", f.record())).not.toContain("target/jj-split");
    expect(f.requests().filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(2);
    expect(f.requests().every(r => r.checkpoint === undefined)).toBe(true);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally { await f.close(); }
}, 60000);

test("guest: aborted editing response neither captures its writes nor forgets another response's shared revision", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    await f.reconstruct();
    await f.execute("write", { path: "unchanged.txt", content: "write before response abort\n" });
    await f.hook("agent_settled", { aborted: true });
    expect(f.record()).toBe(captured);
    expect(f.requests().filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);
    await f.reconstruct();
    await warning(f.extract(), f.file("note.txt"));
    expect(f.read("note.txt")).toBe(reorganized);
    expect(f.record()).toBeNull();
  } finally { await f.close(); }
}, 60000);

test("guest: successive accepted edits, unchanged path and ordinary creation retain the same checkpoint", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    await expect(f.execute("edit", { path: "note.txt", edits: [{ oldText: "not in this file", newText: "unused" }] }))
      .rejects.toThrow();
    await f.hook("agent_settled", { aborted: false });
    await f.execute("edit", { path: "note.txt", edits: [{ oldText: "head 6\n", newText: "independent head\n" }] });
    await f.execute("write", { path: "unchanged.txt", content: "changed independently\n" });
    await f.execute("write", { path: "created.txt", content: "ordinary UTF-8 creation: λ\n" });
    await f.execute("edit", { path: "note.txt", edits: [{ oldText: "tail 6\n", newText: "independent tail\n" }] });
    expect(f.read("created.txt")).toBe("ordinary UTF-8 creation: λ\n");
    expect(f.record()).toBe(captured);
    expect(f.requests().every(r => r.checkpoint === undefined)).toBe(true);
    expect(f.replies().every(r => r.boundary === undefined)).toBe(true);
    expect(f.requests().filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally { await f.close(); }
}, 60000);

test("guest: late warning reply cannot forget a newer shared revision", async () => {
  const f = await fixture("guest");
  let pending: Promise<any> | undefined;
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    f.control({ path: "note.txt", hold: true });
    // Attach rejection handling immediately while the old terminal reply waits.
    pending = warning(f.extract(), f.file("note.txt"));
    await eventually(() => existsSync(join(f.directory, "held")));
    expect(f.read("note.txt")).toBe(reorganized);
    f.session("boundary-session-b");
    await f.hook("session_start", { reason: "switch" });
    await f.execute("write", { path: "unchanged.txt", content: "replacement session\n" });
    await f.hook("agent_settled", { aborted: false });
    const replacement = f.record();
    expect(replacement).toMatch(/^[0-9a-f]{40,64}$/);
    writeFileSync(join(f.directory, "release"), "");
    await pending;
    expect(f.record()).toBe(replacement);
    f.control({});
    await warning(f.extract(), f.file("note.txt"));
    expect(f.read("note.txt")).toBe(reorganized);
    expect(f.record()).toBeNull();
  } finally {
    writeFileSync(join(f.directory, "release"), "");
    if (pending) await pending.catch(() => {});
    await f.close();
  }
}, 60000);

test("guest: lost terminal reply preserves transport error, never replays, and cannot forget a newer revision", async () => {
  const f = await fixture("guest");
  let pending: Promise<any> | undefined;
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    f.control({ path: "unchanged.txt", hold: true, drop: true });
    pending = f.execute("write", { path: "unchanged.txt", content: "completed but reply lost\n" })
      .then(result => ({ result }), error => ({ error }));
    await eventually(() => existsSync(join(f.directory, "held")));
    expect(f.read("unchanged.txt")).toBe("completed but reply lost\n");
    // Another editing response captures before the first caller discovers its
    // lost terminal reply. That transport error must not clear this newer C.
    await f.capture();
    const replacement = f.record();
    expect(replacement).not.toBe(captured);
    writeFileSync(join(f.directory, "release"), "");
    const outcome = await pending;
    expect(outcome.result).toBeUndefined();
    expect(String(outcome.error)).toContain("deliberately lost terminal reply");
    expect(f.record()).toBe(replacement);
    f.control({});
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBe(replacement);
    const requests = f.requests();
    expect(requests.filter(r => r.params.path === "unchanged.txt")).toHaveLength(1);
    expect(requests.filter(r => r.tool === "commit_boundary_checkpoint")).toHaveLength(1);
    expect(requests.every(r => r.checkpoint === undefined)).toBe(true);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally {
    writeFileSync(join(f.directory, "release"), "");
    if (pending) await pending.catch(() => {});
    await f.close();
  }
}, 60000);

test("guest: unavailable immutable revision permits normal write and forgets the shared record", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    writeFileSync(f.recordPath, JSON.stringify("f".repeat(40)));
    const result = await f.execute("write", { path: "unchanged.txt", content: "after unavailable revision\n" });
    expect(result.isError).not.toBe(true);
    expect(f.record()).toBeNull();
    await f.extract();
    expect(f.read("note.txt")).toBe(extracted);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally { await f.close(); }
}, 60000);

function checkerCalls(directory: string) {
  return readFileSync(join(directory, "checker-calls.jsonl"), "utf8").trim().split("\n")
    .map(line => JSON.parse(line));
}

function processExists(pid: number) {
  try { process.kill(pid, 0); return true; }
  catch (error: any) {
    if (error.code === "ESRCH") return false;
    throw error;
  }
}

test("guest: old real checker result cannot forget a newer editing session's atomic replacement", async () => {
  const f = await fixture("guest", true);
  let pending: Promise<any> | undefined;
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const captured = f.record();
    const originalRecord = statSync(f.recordPath, { bigint: true });
    pending = warning(f.extract(), f.file("note.txt"));
    await eventually(() => existsSync(join(f.directory, "checker-held.json")));
    const checked = JSON.parse(readFileSync(join(f.directory, "checker-request.json"), "utf8"));
    expect(checked.revision).toBe(captured);
    expect(f.record()).toBe(captured);
    // A concurrent editing session finishes a different file, then uses the
    // same production guest capture/store path, not a fabricated record value.
    writeFileSync(f.file("unchanged.txt"), "other editing session finished\n");
    await f.capture();
    const replacement = f.record();
    expect(replacement).toMatch(/^[0-9a-f]{40,64}$/);
    expect(replacement).not.toBe(captured);
    expect(statSync(f.recordPath, { bigint: true }).ino).not.toBe(originalRecord.ino);
    writeFileSync(join(f.directory, "checker-release"), "");
    await pending;
    expect(f.read("note.txt")).toBe(reorganized);
    expect(f.record()).toBe(replacement);
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBe(replacement);
    expect(checkerCalls(f.directory).map(call => call.args)).toEqual([["agent-split", "--check-file"]]);
  } finally {
    writeFileSync(join(f.directory, "checker-release"), "");
    if (pending) await pending.catch(() => {});
    await f.close();
  }
}, 60000);

test("guest: host cancellation reaches real checker process and leaves target unchanged without a false checkpoint", async () => {
  const f = await fixture("guest", true);
  let pending: Promise<any> | undefined;
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    const before = statSync(f.file("note.txt"), { bigint: true });
    const controller = new AbortController();
    pending = f.execute("write", { path: "note.txt", content: extracted }, controller.signal)
      .then(result => ({ result }), error => ({ error }));
    await eventually(() => existsSync(join(f.directory, "checker-held.json")));
    const held = JSON.parse(readFileSync(join(f.directory, "checker-held.json"), "utf8"));
    const actualResult = JSON.parse(readFileSync(join(f.directory, "checker-result.json"), "utf8"));
    expect(held.status).toBe(0);
    expect(actualResult.status).toBe("would-lose");
    expect(actualResult.reason.length).toBeGreaterThan(0);
    expect(processExists(held.pid)).toBe(true);
    expect(f.read("note.txt")).toBe(reorganized);
    controller.abort();
    const outcome = await pending;
    expect(outcome.result).toBeUndefined();
    expect(String(outcome.error)).toContain("guest tool cancelled");
    // Host cancellation must traverse the existing connector's socket close,
    // worker AbortController and checker process group, not just reject locally.
    await eventually(() => existsSync(join(f.directory, "checker-cancelled.json")));
    const cancelled = JSON.parse(readFileSync(join(f.directory, "checker-cancelled.json"), "utf8"));
    expect(cancelled.pid).toBe(held.pid);
    expect(cancelled.signal).toBe(15);
    await eventually(() => !processExists(held.pid));
    expect(f.read("note.txt")).toBe(reorganized);
    const after = statSync(f.file("note.txt"), { bigint: true });
    expect([after.ino, after.size, after.mtimeNs, after.ctimeNs]).toEqual(
      [before.ino, before.size, before.mtimeNs, before.ctimeNs]);
    await f.hook("agent_settled", { aborted: false });
    expect(checkerCalls(f.directory).filter(call => call.args.includes("--checkpoint"))).toHaveLength(0);
    // The connector rejects before the worker's finalizer completes. Wait for
    // conditional retirement, not just for the checker process to disappear.
    await eventually(() => f.record() === null);
    // This same worker/file queue must finish cancellation before retrying.
    // A retired checkpoint means no second checker invocation/barrier at all.
    expect((await f.extract()).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);
    expect(checkerCalls(f.directory).filter(call => call.args.includes("--check-file"))).toHaveLength(1);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally {
    writeFileSync(join(f.directory, "checker-release"), "");
    if (pending) await pending;
    await f.close();
  }
}, 60000);

test("guest: external target change during real checker request fails guarded native edit and retires checkpoint", async () => {
  const f = await fixture("guest", true);
  let pending: Promise<any> | undefined;
  try {
    await f.reorganize();
    await f.hook("agent_settled", { aborted: false });
    pending = f.execute("edit", { path: "note.txt", edits: [{ oldText: reorganized, newText: extracted }] })
      .then(result => ({ result }), error => ({ error }));
    await eventually(() => existsSync(join(f.directory, "checker-held.json")));
    const held = JSON.parse(readFileSync(join(f.directory, "checker-held.json"), "utf8"));
    const actualResult = JSON.parse(readFileSync(join(f.directory, "checker-result.json"), "utf8"));
    const actualRequest = JSON.parse(readFileSync(join(f.directory, "checker-request.json"), "utf8"));
    expect(held.status).toBe(0);
    expect(actualResult.status).toBe("would-lose");
    expect(Object.keys(actualRequest).sort()).toEqual(["actual", "path", "proposed", "revision"]);
    expect(actualRequest.revision).toBe(f.record());
    expect(Object.keys(actualRequest.actual).sort()).toEqual(["content", "executable"]);
    expect(actualRequest.actual.executable).toBe(false);
    expect(actualRequest.path).toBe("note.txt");
    expect(Buffer.from(actualRequest.actual.content, "base64").toString("utf8")).toBe(reorganized);
    expect(Buffer.from(actualRequest.proposed, "base64").toString("utf8")).toBe(extracted);
    const external = "External writer owns these newer contents.\n";
    writeFileSync(f.file("note.txt"), external);
    writeFileSync(join(f.directory, "checker-release"), "");
    const outcome = await pending;
    expect(outcome.result).toBeUndefined();
    expect(String(outcome.error)).toContain("Target changed while preparing write");
    expect(String(outcome.error)).not.toContain("No file was changed.");
    expect(f.read("note.txt")).toBe(external);
    await eventually(() => !processExists(held.pid));
    await f.hook("agent_settled", { aborted: false });
    expect(checkerCalls(f.directory).filter(call => call.args.includes("--checkpoint"))).toHaveLength(0);
    expect(f.record()).toBeNull();
    // A genuinely fresh SDK edit reads the external version. It succeeds
    // without another check, proving the failed raced call retired tracking.
    await f.execute("edit", { path: "note.txt", edits: [{ oldText: external, newText: external + "Fresh edit.\n" }] });
    expect(f.read("note.txt")).toBe(external + "Fresh edit.\n");
    expect(checkerCalls(f.directory).filter(call => call.args.includes("--check-file"))).toHaveLength(1);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally {
    writeFileSync(join(f.directory, "checker-release"), "");
    if (pending) await pending;
    await f.close();
  }
}, 60000);
