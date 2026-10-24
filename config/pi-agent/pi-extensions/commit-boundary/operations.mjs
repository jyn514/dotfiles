import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access, lstat, mkdir, mkdtemp, open, readFile, rename, rm, stat, writeFile as fsWriteFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

const warning = "This edit would make the earlier changes to this file no longer separately selectable by `agent-split`. No file was changed. Commit first if that separation matters, or retry to proceed.";

function aborted(signal) {
  if (signal?.aborted) throw new Error("Operation aborted");
}

// Wait for close and cancellation cleanup before releasing Pi's mutation
// queue. On POSIX the checker owns a process group: descendants must not
// survive merely because bb exited first or closed its inherited pipes.
async function command(executable, args, input, { cwd, signal, env }) {
  aborted(signal);
  return new Promise((resolve, reject) => {
    const processGroup = process.platform !== "win32";
    const child = spawn(executable, args, {
      cwd, env, detached: processGroup, stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout = [], stderr = [];
    let failure, cancellationCleanup;
    const terminate = (signal) => {
      if (processGroup && child.pid) {
        try { process.kill(-child.pid, signal); }
        catch (error) { if (error.code !== "ESRCH") failure ??= error; }
      } else {
        child.kill(signal);
      }
    };
    const cancel = () => {
      if (cancellationCleanup) return;
      terminate("SIGTERM");
      cancellationCleanup = new Promise((resolve) => {
        // Keep this timer alive even if bb closes first: an uncooperative
        // descendant may have detached its stdio, but not its process group.
        setTimeout(async () => {
          terminate("SIGKILL");
          // Signal delivery is asynchronous. Wait for the group to disappear,
          // bounded because terminated orphans can remain as zombies until
          // the platform's init process reaps them.
          if (processGroup && child.pid) {
            const deadline = Date.now() + 1000;
            while (Date.now() < deadline) {
              try { process.kill(-child.pid, 0); }
              catch (error) { if (error.code === "ESRCH") break; failure ??= error; }
              await sleep(10);
            }
          }
          resolve();
        }, 1000);
      });
    };
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", (error) => { failure = error; });
    child.stdin.on("error", (error) => { failure ??= error; });
    child.on("close", async (code) => {
      await cancellationCleanup;
      // An abort can arrive while the close callback yields, even if bb
      // exited normally. Still terminate its group before reporting it.
      if (signal?.aborted) { cancel(); await cancellationCleanup; }
      signal?.removeEventListener("abort", cancel);
      try {
        aborted(signal);
        if (failure) throw failure;
        if (code !== 0) throw new Error(`${executable} exited ${code}: ${Buffer.concat(stderr).toString("utf8").trim()}`);
        resolve(Buffer.concat(stdout).toString("utf8"));
      } catch (error) { reject(error); }
    });
    child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
  });
}

async function invoke(args, input, context) {
  return JSON.parse(await command("bb", ["agent-split", ...args], input, context));
}

const recordPath = root => join(root, "target", "jj-split", "commit-boundary.json");
const validRevision = value => typeof value === "string" && /^[a-f0-9]{40,64}$/.test(value);
function decodeRecord(text) {
  if (text === "") return null;
  const revision = JSON.parse(text);
  if (!validRevision(revision)) throw new Error("Invalid commit-boundary revision record");
  return revision;
}

async function workspaceRoot(cwd, context) {
  try {
    // Match the established splitter/wrapper discovery: ordinary hosts need
    // neither the sandbox route helper nor Python. When sandbox routing exists,
    // ask its authoritative provider rather than infer backend from cwd/env.
    let proxyDirectory = context.env.SANDBOX_PROXY_DIR;
    if (!proxyDirectory) {
      const candidate = context.env.SANDBOX_PROXY_DEFAULT_DIR || "/run/sandbox-proxies";
      try { if ((await stat(join(candidate, "jj", "socket"))).isSocket()) proxyDirectory = candidate; }
      catch (error) { if (!["ENOENT", "ENOTDIR"].includes(error.code)) throw error; }
    }
    let backend = "native", env = context.env;
    if (proxyDirectory) {
      env = { ...env, SANDBOX_PROXY_DIR: proxyDirectory };
      const helper = env.JJ_ROUTE_HELPER || fileURLToPath(new URL("../../../../tools/jj-proxy/route.py", import.meta.url));
      const route = JSON.parse(await command("python3", [helper, "--", "workspace", "root"],
        undefined, { ...context, cwd, env }));
      if (!route || !["native", "proxy"].includes(route.backend)) throw new Error("Invalid Jujutsu read route");
      backend = route.backend;
    }
    // Protected callers must not send the native security-sensitive flag: the
    // trusted inspect executor adds it. Inspection is scoped to this child;
    // settlement's ordinary snapshot must retain mutation authority.
    const args = backend === "proxy" ? ["workspace", "root"] : ["workspace", "--ignore-working-copy", "root"];
    if (backend === "proxy") env = { ...env, JJ_PROXY_INSPECT: "1" };
    const root = (await command("jj", args, undefined, { ...context, cwd, env })).replace(/\r?\n$/, "");
    if (!isAbsolute(root)) throw new Error("Invalid Jujutsu workspace root");
    return root;
  } catch (error) {
    aborted(context.signal);
    if (/There is no jj repo/.test(String(error))) return null;
    throw error;
  }
}

// These functions own the one workspace record. Roots are transient local
// execution paths, never persisted identities or host/guest handoff payloads.
export async function readCheckpoint(root) {
  try { return decodeRecord(await readFile(recordPath(root), "utf8")); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}
export async function storeCheckpoint(root, revision, { signal } = {}) {
  if (!validRevision(revision)) throw new Error("Invalid commit-boundary revision");
  const path = recordPath(root);
  await mkdir(dirname(path), { recursive: true });
  const temporary = await mkdtemp(join(dirname(path), ".commit-boundary-"));
  try {
    const fresh = join(temporary, "revision");
    await fsWriteFile(fresh, JSON.stringify(revision), { flag: "wx", mode: 0o600 });
    // Always publish a new inode. Never overwrite the inode a late clear may
    // have opened, even when the immutable revision happens to be identical.
    aborted(signal);
    await rename(fresh, path);
  } finally { await rm(temporary, { recursive: true, force: true }); }
}
export async function forgetCheckpoint(root, revision) {
  let handle;
  try { handle = await open(recordPath(root), "r+"); }
  catch (error) { if (error.code === "ENOENT") return; throw error; }
  try {
    if (decodeRecord(await handle.readFile("utf8")) === revision) {
      // Compare and clear this SAME inode. A capture racing this truncate
      // replaces the pathname, so a different replacement cannot be erased.
      // Empty is no boundary; equal-ID replacements need no generation token.
      await handle.truncate(0);
    }
  } finally { await handle.close(); }
}

export async function captureCheckpoint(cwd, { signal, env = process.env } = {}) {
  const context = { signal, env };
  const root = await workspaceRoot(cwd, context);
  if (!root) return { revision: null };
  // Check before creating any artifacts or taking the ordinary JJ snapshot.
  try {
    for (const path of ["target/jj-split/.jj-split-ignore-probe", "target/jj-split/commit-boundary.json"]) {
      // The existing artifact probe covers the directory convention; also
      // reject a per-file negation that would expose the actual shared record.
      await command("git", ["check-ignore", "-q", path], undefined, { ...context, cwd: root });
    }
  } catch (error) {
    aborted(signal);
    throw new Error(`Commit-boundary storage requires ignored target/jj-split/: ${error}`);
  }
  const revision = (await command("jj", ["log", "-r", "@", "--no-graph", "-T", "commit_id"],
    undefined, { ...context, cwd })).trim();
  if (!validRevision(revision)) throw new Error("Invalid Jujutsu immutable revision");
  aborted(signal);
  await storeCheckpoint(root, revision, { signal });
  return { revision };
}

const statKeys = ["dev", "ino", "mode", "size", "mtimeNs", "ctimeNs"];
function sameStat(a, b) {
  return a === null || b === null ? a === b : statKeys.every((key) => a[key] === b[key]);
}
async function linkStat(path) {
  try { return await lstat(path, { bigint: true }); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}
function changed(path) { return new Error(`Target changed while preparing write: ${path}. Retry with a fresh read.`); }

// Read bytes and identity from one handle. Both the directory entry and handle
// must remain stable across the read; never bless a newer read as edit's baseline.
async function retain(path, keepHandle = false) {
  const link = await linkStat(path);
  if (link === null) return { link: null, stat: null, bytes: null };
  let handle;
  try { handle = await open(path, "r"); }
  catch (error) {
    if (error.code === "ENOENT" && link.isSymbolicLink()) {
      if (!sameStat(link, await linkStat(path))) throw changed(path);
      return { link, stat: null, bytes: null };
    }
    throw error;
  }
  let retainedHandle = false;
  try {
    const stat = await handle.stat({ bigint: true });
    const bytes = await handle.readFile();
    const after = await handle.stat({ bigint: true });
    const afterLink = await linkStat(path);
    if (!sameStat(stat, after) || !sameStat(link, afterLink)
        || (!link.isSymbolicLink() && !sameStat(link, stat))) throw changed(path);
    retainedHandle = keepHandle;
    return { link, stat, bytes, ...(keepHandle ? { handle } : {}) };
  } finally { if (!retainedHandle) await handle.close(); }
}
function sameState(a, b) {
  return sameStat(a.link, b.link) && sameStat(a.stat, b.stat)
    && (a.bytes === null || b.bytes === null ? a.bytes === b.bytes : a.bytes.equals(b.bytes));
}
function actualState(state) {
  if (state.link === null) return null;
  if (!state.link.isFile() || !state.stat?.isFile() || !state.bytes
      || state.bytes.includes(0) || !Buffer.from(state.bytes.toString("utf8"), "utf8").equals(state.bytes)) {
    return undefined;
  }
  return { content: state.bytes.toString("base64"), executable: (state.stat.mode & 0o111n) !== 0n };
}

/** One instance per call. Native Pi still owns validation, normalization and its queue. */
export function createBoundaryTool(factories, name, cwd, {
  signal: suppliedSignal, env = process.env,
  load = async context => {
    const root = await workspaceRoot(cwd, context);
    return root ? { root, revision: await readCheckpoint(root) } : null;
  },
  forget = forgetCheckpoint,
  check = (request, context) => invoke(["--check-file"], request, context),
} = {}) {
  if (name !== "edit" && name !== "write") throw new Error(`Unsupported boundary tool: ${name}`);
  let retire = false, failure, activeSignal = suppliedSignal, underlyingWrite = false;
  // Only this call's intentional refusal becomes an error result after the
  // native tool unwinds. Filesystem and cancellation errors remain unchanged.
  const refusal = new Error("Commit-boundary refusal");
  let refusedPath;
  let checkpoint;
  const forgetCompared = async () => {
    if (!retire || !checkpoint?.revision) return;
    try { await forget(checkpoint.root, checkpoint.revision); }
    catch (error) { failure ??= String(error); }
  };
  let baseline;
  const markRetired = () => { retire = true; };
  const operations = {
    access: (path) => access(path, constants.R_OK | constants.W_OK),
    mkdir: async (path) => { await mkdir(path, { recursive: true }); },
    readFile: async (path) => {
      try { baseline = await retain(path, true); }
      catch (error) { markRetired(); aborted(activeSignal); throw error; }
      if (baseline.bytes === null) throw new Error(`Could not read file: ${path}`);
      return baseline.bytes;
    },
    writeFile: async (path, content) => {
      let retained = baseline;
      if (name === "write") {
        try { retained = baseline = await retain(path, true); }
        catch (error) { markRetired(); aborted(activeSignal); throw error; }
      }
      let outcome = { status: "preserved" };
      try {
        checkpoint = await load({ cwd, signal: activeSignal, env });
        if (checkpoint?.revision) {
          const repoPath = relative(checkpoint.root, path);
          const actual = actualState(retained);
          if (actual === undefined || repoPath === ".." || repoPath.startsWith(`..${sep}`) || isAbsolute(repoPath)) {
            outcome = { status: "unusable" };
          } else {
            outcome = await check({ revision: checkpoint.revision, path: repoPath.split(sep).join("/"),
              actual, proposed: Buffer.from(content, "utf8").toString("base64") },
            { cwd, signal: activeSignal, env });
            if (!outcome || !["preserved", "would-lose", "unusable"].includes(outcome.status)
                || Object.keys(outcome).some(key => !["status", "reason"].includes(key))
                || (outcome.reason !== undefined && typeof outcome.reason !== "string")
                || (outcome.status === "would-lose" && !outcome.reason?.trim())) {
              throw new Error("Invalid agent-split file-check reply");
            }
          }
        }
      } catch (error) {
        // A failed command is not an advisory checker reply. Report its real
        // error once at the controller, then fail open through the SAME target
        // and cancellation finalizer as every other outcome.
        outcome = { status: "unusable" };
        if (!activeSignal?.aborted) failure = String(error);
      }
      if (outcome.status !== "preserved") markRetired();

      // Forget before final target verification: record I/O must not add an
      // extra awaited race between a successful verification and native write.
      if (retire) await forgetCompared();
      // One finalizer for preserved, would-lose, unusable and no-boundary calls.
      // In particular, retain verification errors until cancellation has won.
      let verificationError;
      try { if (!sameState(retained, await retain(path))) throw changed(path); }
      catch (error) { verificationError = error; }
      if (activeSignal?.aborted || verificationError) {
        markRetired();
        await forgetCompared();
      }
      aborted(activeSignal);
      if (verificationError) throw verificationError;
      if (outcome.status === "would-lose") {
        refusedPath = path;
        throw refusal;
      }
      underlyingWrite = true;
      try { await fsWriteFile(path, content, "utf8"); }
      catch (error) { markRetired(); await forgetCompared(); throw error; }
    },
  };
  const native = name === "edit" ? factories.createEditTool(cwd, { operations }) : factories.createWriteTool(cwd, { operations });
  const tool = { ...native, async execute(id, args, signal, ...rest) {
    // Callers normally supply the same signal; either cancellation must apply.
    activeSignal = suppliedSignal && signal && suppliedSignal !== signal
      ? AbortSignal.any([suppliedSignal, signal]) : (signal ?? suppliedSignal);
    try { return await native.execute(id, args, activeSignal, ...rest); }
    catch (error) {
      if (underlyingWrite || activeSignal?.aborted) { markRetired(); await forgetCompared(); }
      if (error === refusal) {
        aborted(activeSignal);
        return {
          content: [{ type: "text", text: `Could not ${name} file: ${refusedPath}. ${warning}` }],
          details: {},
          isError: true,
        };
      }
      throw error;
    } finally {
      // Pin the original inode through finalization so an unlink/recreate
      // cannot recycle its identity while this call is comparing it.
      if (baseline?.handle) {
        try { await baseline.handle.close(); }
        catch (error) { markRetired(); failure ??= String(error); await forgetCompared(); }
      }
    }
  } };
  return { tool, metadata: () => failure ? { error: failure } : undefined };
}
