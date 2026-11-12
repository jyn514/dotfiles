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

async function fixture(mode: "guest" | "native", checkerBarrier = false, separateLaunch = false) {
  const directory = mkdtempSync(join(realpathSync(tmpdir()), "pi-commit-boundary-"));
  const repo = join(directory, "repo");
  const bin = join(directory, "bin");
  mkdirSync(repo); mkdirSync(bin);
  const launchRepo = separateLaunch ? join(directory, "launch-repo") : repo;
  if (separateLaunch) mkdirSync(launchRepo);
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
    CODEX_SANDBOX_GUEST_CWD: launchRepo,
    CODEX_SANDBOX_GUEST_REPO: launchRepo,
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
    if (separateLaunch) jj("git", "init", "--colocate", launchRepo);
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
      worker = spawn("bun", [join(root, "tools/codex-sandbox/image/tool-worker.mjs")], {
        cwd: launchRepo, env: process.env, stdio: ["ignore", "ignore", "pipe"],
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
        getSettings: () => ({}),
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
    return { directory, repo, launchRepo, file, read, jj, tools, hook, execute, requests, replies, close, record, recordPath,
      reconstruct: async () => {
        await hook("session_shutdown");
        session += "-fresh";
        install();
        await hook("session_start", { reason: "startup" });
      },
      // Older host attachments can still send requests to this internal endpoint.
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

test("guest: writes without response captures or commit-boundary warnings", async () => {
  const f = await fixture("guest");
  try {
    expect((await f.reorganize()).isError).not.toBe(true);
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBeNull();
    expect((await f.extract()).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);
    expect(f.requests().filter(request => request.tool === "commit_boundary_checkpoint")).toHaveLength(0);
    expect(f.read("unrelated.txt")).toBe("formatting  \n");
  } finally { await f.close(); }
}, 60000);

test("guest: stale checkpoint cannot interrupt write or edit, including after reload", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    const captured = f.jj("log", "-r", "@", "-T", "commit_id", "--no-graph").trim();
    mkdirSync(f.file("target/jj-split"), { recursive: true });
    writeFileSync(f.recordPath, JSON.stringify(captured));
    expect((await f.extract()).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);
    await f.reconstruct();
    expect((await f.execute("edit", {
      path: "note.txt", edits: [{ oldText: extracted, newText: reorganized }],
    })).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(reorganized);
    await f.hook("agent_settled", { aborted: false });
    expect(f.record()).toBe(captured);
    expect(f.requests().filter(request => request.tool === "commit_boundary_checkpoint")).toHaveLength(0);
    expect(f.replies().every(reply => reply.boundary === undefined)).toBe(true);

    const missing = { path: "missing.txt", edits: [{ oldText: "absent", newText: "still absent" }] };
    const nativeError = await sdk.createEditTool(f.repo).execute("native-missing-control", missing)
      .then(() => { throw new Error("Native missing-file control unexpectedly succeeded"); }, (error: Error) => error.message);
    expect(nativeError).toContain("ENOENT");
    await expect(f.execute("edit", missing)).rejects.toThrow(nativeError);
    expect(existsSync(f.file("missing.txt"))).toBe(false);
  } finally { await f.close(); }
}, 60000);

test("guest: legacy capture request is acknowledged without creating a checkpoint", async () => {
  const f = await fixture("guest");
  try {
    await f.reorganize();
    await f.capture();
    expect(f.record()).toBeNull();
    expect((await f.extract()).isError).not.toBe(true);
    expect(f.read("note.txt")).toBe(extracted);
  } finally { await f.close(); }
}, 60000);

for (const mode of ["native"] as const) {
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
    } finally { await f.close(); }
  }, 60000);
}

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

