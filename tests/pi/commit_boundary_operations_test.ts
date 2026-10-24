// Use the installed factories: the locked SDK predates native multi-edit/queue.
// Also runnable with Node 24 --test (no Bun module mocks in that route).
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify, stripVTControlCharacters } from "node:util";
import { chmod, lstat, mkdir, mkdtemp, open, readFile, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import { captureCheckpoint, createBoundaryTool as createProductionBoundaryTool, readCheckpoint, storeCheckpoint, forgetCheckpoint } from "../../config/pi-agent/pi-extensions/commit-boundary/operations.mjs";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const factories = await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
const accepted = { status: "preserved" };
function createBoundaryTool(factories, name, cwd, { checkpoint = null, ...options } = {}) {
  return createProductionBoundaryTool(factories, name, cwd, {
    load: async () => checkpoint, ...options,
  });
}
const unavailable = { status: "unusable", reason: "lost boundary" };
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "pi-boundary-operations-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const checkpoint = { root, revision: "c".repeat(40) };
  await storeCheckpoint(root, checkpoint.revision);
  await writeFile(join(root, "file"), "original\n");
  return { root, checkpoint, path: join(root, "file") };
}
function edit(call, signal?) {
  return call.tool.execute("call", { path: "file", edits: [{ oldText: "original", newText: "proposal" }] }, signal);
}
function write(call, content = "proposal\n", signal?) {
  return call.tool.execute("call", { path: "file", content }, signal);
}

test("owned edit refusal has exact one-paragraph diagnostic, never writes, retires; retry uses native edit", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  let checks = 0;
  const call = createBoundaryTool(factories, "edit", root, { checkpoint, check: async (request) => {
    checks++;
    assert.equal(request.path, "file");
    assert.equal(Buffer.from(request.actual.content, "base64").toString(), "original\n");
    assert.equal(Buffer.from(request.proposed, "base64").toString(), "proposal\n");
    return { status: "would-lose", reason: "removed selected occurrence" };
  } });
  assert.deepEqual(await edit(call), {
    content: [{ type: "text", text: `Could not edit file: ${path}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.` }],
    details: {},
    isError: true,
  });
  assert.equal(await readFile(path, "utf8"), "original\n");
  assert.equal(await readCheckpoint(root), null);
  const retry = createBoundaryTool(factories, "edit", root, { check: async () => { throw new Error("must not check"); } });
  await edit(retry);
  assert.equal(await readFile(path, "utf8"), "proposal\n");
  assert.equal(retry.metadata(), undefined);
  assert.equal(checks, 1);
});

test("owned write refusal has exact one-paragraph diagnostic without checker reason or errno", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const call = createBoundaryTool(factories, "write", root, { checkpoint,
    check: async () => ({ status: "would-lose", reason: "raw canonical checker reason" }),
  });
  assert.deepEqual(await write(call), {
    content: [{ type: "text", text: `Could not write file: ${path}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.` }],
    details: {},
    isError: true,
  });
  assert.equal(await readFile(path, "utf8"), "original\n");
  assert.equal(await readCheckpoint(root), null);
  assert.equal(call.metadata(), undefined);
});

test("actual missing edit keeps the installed factory's genuine ENOENT diagnostic", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  await unlink(path);
  const args = { path: "file", edits: [{ oldText: "original", newText: "proposal" }] };
  const native = factories.createEditTool(root);
  const call = createBoundaryTool(factories, "edit", root, { checkpoint,
    check: async () => { throw new Error("missing file must not reach checker"); },
  });
  await assert.rejects(native.execute("native", args), {
    message: "Could not edit file: file. Error code: ENOENT.",
  });
  await assert.rejects(call.tool.execute("guarded", args), {
    message: "Could not edit file: file. Error code: ENOENT.",
  });
  await assert.rejects(lstat(path), { code: "ENOENT" });
  assert.equal(await readCheckpoint(root), checkpoint.revision);
  assert.equal(call.metadata(), undefined);
});

test("native errors after an owned refusal are not replaced by the advisory", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const ioError = Object.assign(new Error("real native I/O error"), { code: "EIO" });
  const decorated = { ...factories, createEditTool(cwd, options) {
    const native = factories.createEditTool(cwd, options);
    return { ...native, async execute(...args) {
      try { return await native.execute(...args); }
      catch { throw ioError; }
    } };
  } };
  const call = createBoundaryTool(decorated, "edit", root, { checkpoint,
    check: async () => ({ status: "would-lose", reason: "selected occurrence removed" }),
  });
  await assert.rejects(edit(call), error => error === ioError);
  assert.equal(await readFile(path, "utf8"), "original\n");
  assert.equal(await readCheckpoint(root), null);
});

test("cancellation while the native tool unwinds beats the owned refusal", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const abort = new AbortController();
  const decorated = { ...factories, createEditTool(cwd, options) {
    const native = factories.createEditTool(cwd, options);
    return { ...native, async execute(...args) {
      try { return await native.execute(...args); }
      catch (error) { abort.abort(); throw error; }
    } };
  } };
  const call = createBoundaryTool(decorated, "edit", root, { checkpoint,
    check: async () => ({ status: "would-lose", reason: "selected occurrence removed" }),
  });
  await assert.rejects(edit(call, abort.signal), { message: "Operation aborted" });
  assert.equal(await readFile(path, "utf8"), "original\n");
  assert.equal(await readCheckpoint(root), null);
});

test("native edit preserves BOM, CRLF, executable mode and computed proposal", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  await writeFile(path, "\ufefforiginal\r\nsecond\r\n");
  await chmod(path, 0o751);
  const call = createBoundaryTool(factories, "edit", root, { checkpoint, check: async (request) => {
    assert.equal(request.actual.executable, true);
    assert.equal(Buffer.from(request.actual.content, "base64").toString(), "\ufefforiginal\r\nsecond\r\n");
    assert.equal(Buffer.from(request.proposed, "base64").toString(), "\ufeffproposal\r\nsecond\r\n");
    return accepted;
  } });
  await edit(call);
  assert.equal(await readFile(path, "utf8"), "\ufeffproposal\r\nsecond\r\n");
  assert.equal((await lstat(path)).mode & 0o777, 0o751);
  assert.equal(await readCheckpoint(root), checkpoint.revision);
});

for (const status of ["preserved", "unusable", "would-lose", "failure"]) {
  test(`${status}: changed bytes or identity prevent stale write`, async (t) => {
    const { root, checkpoint, path } = await fixture(t);
    const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => {
      // Same bytes, different inode: content-only verification would miss this.
      await unlink(path);
      await writeFile(path, "original\n");
      if (status === "failure") throw new Error("checker exploded");
      return status === "preserved" ? accepted : status === "would-lose"
        ? { status: "would-lose", reason: "rejected proposal" } : unavailable;
    } });
    await assert.rejects(write(call), /Target changed/);
    assert.equal(await readFile(path, "utf8"), "original\n");
    assert.equal(await readCheckpoint(root), null);
    if (status === "failure") assert.match(call.metadata().error, /checker exploded/);
  });
}

test("edit retains native read baseline instead of a newer checker baseline; no C also verifies", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  for (const current of [checkpoint, null]) {
    await writeFile(path, "original\n");
    const decorated = { ...factories, createEditTool(cwd, options) {
      const read = options.operations.readFile;
      return factories.createEditTool(cwd, { ...options, operations: { ...options.operations,
        readFile: async (target) => {
          const bytes = await read(target);
          await writeFile(target, "external\n");
          return bytes;
        },
      } });
    } };
    let observed;
    const call = createBoundaryTool(decorated, "edit", root, { checkpoint: current, check: async (request) => {
      observed = Buffer.from(request.actual.content, "base64").toString();
      return accepted;
    } });
    await assert.rejects(edit(call), /Target changed/);
    if (current) assert.equal(observed, "original\n");
    assert.equal(await readFile(path, "utf8"), "external\n");
  }
});

for (const status of ["preserved", "unusable", "would-lose", "failure"]) {
  test(`cancellation beats ${status} and verification errors`, async (t) => {
    const { root, checkpoint, path } = await fixture(t);
    const abort = new AbortController();
    const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async (_request, context) => {
      assert.equal(context.signal, abort.signal);
      await unlink(path);
      await mkdir(path); // reading a directory fails verification
      abort.abort();
      if (status === "failure") throw new Error("checker failed");
      return { status, reason: "test" };
    } });
    await assert.rejects(write(call, "proposal", abort.signal), /Operation aborted/);
    assert.equal((await lstat(path)).isDirectory(), true);
    assert.equal(await readCheckpoint(root), null);
  });
}

test("verification errors preserve their original code without a cancellation", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => {
    await unlink(path);
    await mkdir(path);
    return unavailable;
  } });
  await assert.rejects(write(call), { code: "EISDIR" });
  assert.equal(await readCheckpoint(root), null);
});

test("no-checkpoint finalizer checks cancellation after capture and verification", async (t) => {
  const { root, path } = await fixture(t);
  const abort = new AbortController();
  const decorated = { ...factories, createWriteTool(cwd, options) {
    return factories.createWriteTool(cwd, { ...options, operations: { ...options.operations,
      writeFile: async (...args) => { abort.abort(); return options.operations.writeFile(...args); },
    } });
  } };
  const call = createBoundaryTool(decorated, "write", root);
  await assert.rejects(write(call, "proposal", abort.signal), /Operation aborted/);
  assert.equal(await readFile(path, "utf8"), "original\n");
});

test("native file mutation queue serializes independent per-call adapters", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  let enter, release;
  const entered = new Promise((resolve) => { enter = resolve; });
  const waiting = new Promise((resolve) => { release = resolve; });
  const first = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => {
    enter();
    await waiting;
    return accepted;
  } });
  const firstResult = write(first, "first\n");
  await entered;
  const second = createBoundaryTool(factories, "edit", root, { checkpoint, check: async (request) => {
    assert.equal(Buffer.from(request.actual.content, "base64").toString(), "first\n");
    return accepted;
  } });
  const secondResult = second.tool.execute("second", { path: "file", edits: [{ oldText: "first", newText: "second" }] });
  release();
  await Promise.all([firstResult, secondResult]);
  assert.equal(await readFile(path, "utf8"), "second\n");
  assert.equal(await readCheckpoint(root), checkpoint.revision);
  assert.equal(second.metadata(), undefined);
});

test("no-checkpoint cancellation during native read never writes", async (t) => {
  const { root, path } = await fixture(t);
  const abort = new AbortController();
  const decorated = { ...factories, createEditTool(cwd, options) {
    const read = options.operations.readFile;
    return factories.createEditTool(cwd, { ...options, operations: { ...options.operations,
      readFile: async (target) => { const bytes = await read(target); abort.abort(); return bytes; },
    } });
  } };
  const call = createBoundaryTool(decorated, "edit", root);
  await assert.rejects(edit(call, abort.signal), /Operation aborted/);
  assert.equal(await readFile(path, "utf8"), "original\n");
});

test("expected absence permits creation but refuses a racing creator", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  await unlink(path);
  let race = true;
  const checker = async (request) => {
    assert.equal(request.actual, null);
    if (race) await writeFile(path, "external");
    return accepted;
  };
  const first = createBoundaryTool(factories, "write", root, { checkpoint, check: checker });
  await assert.rejects(write(first), /Target changed/);
  assert.equal(await readFile(path, "utf8"), "external");
  await unlink(path);
  race = false;
  await write(createBoundaryTool(factories, "write", root, { checkpoint, check: checker }));
  assert.equal(await readFile(path, "utf8"), "proposal\n");
});

test("unsupported binary and symlink skip checker without changing native permissions", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  for (const bytes of [Buffer.from([0, 1]), Buffer.from([0xff, 0xfe])]) {
    await storeCheckpoint(root, checkpoint.revision);
    await writeFile(path, bytes);
    const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => {
      throw new Error("unsupported actual must never reach checker");
    } });
    await write(call);
    assert.equal(await readCheckpoint(root), null);
    assert.equal(call.metadata(), undefined);
  }
  await storeCheckpoint(root, checkpoint.revision);
  await writeFile(join(root, "referent"), "original\n");
  await unlink(path);
  await symlink("referent", path);
  const call = createBoundaryTool(factories, "edit", root, { checkpoint, check: async () => {
    throw new Error("symlink actual must never reach checker");
  } });
  await edit(call);
  assert.equal((await lstat(path)).isSymbolicLink(), true);
  assert.equal(await readFile(join(root, "referent"), "utf8"), "proposal\n");
  assert.equal(await readCheckpoint(root), null);
  assert.equal(call.metadata(), undefined);
});

test("checker failure allows ordinary write, retains actual error, and forgets matching revision", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => { throw new Error("offline checker"); } });
  await write(call);
  assert.equal(await readFile(path, "utf8"), "proposal\n");
  assert.match(call.metadata().error, /offline checker/);
  assert.equal(await readCheckpoint(root), null);
});

test("failed/partially completed underlying write retires without hiding native error", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  // A child-only file-size limit reliably fails a real fsWriteFile even as
  // root. It may leave a partial file; never replay this uncertain write.
  const script = `
    import assert from 'node:assert/strict';
    import * as factories from ${JSON.stringify(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href)};
    import { createBoundaryTool, readCheckpoint } from ${JSON.stringify(new URL("../../config/pi-agent/pi-extensions/commit-boundary/operations.mjs", import.meta.url).href)};
    process.on('SIGXFSZ', () => {});
    const checkpoint = ${JSON.stringify(checkpoint)};
    const call = createBoundaryTool(factories, 'write', ${JSON.stringify(root)}, {
      load: async () => checkpoint, check: async () => ({status:'preserved'})
    });
    await assert.rejects(call.tool.execute('call', {path:'file',content:'x'.repeat(4096)}), {code:'EFBIG'});
    assert.equal(await readCheckpoint(checkpoint.root), null);
  `;
  await promisify(execFile)("python3", ["-c", "import os,resource,signal,sys; resource.setrlimit(resource.RLIMIT_FSIZE,(1024,1024)); signal.signal(signal.SIGXFSZ,signal.SIG_IGN); os.execv(sys.argv[1],sys.argv[1:])", process.execPath, "--input-type=module", "-e", script]);
  assert.ok((await readFile(path)).length <= 1024);
});

test("subprocess checker uses exact JSON stdin, cwd/env and cancellation", async (t) => {
  const { root, checkpoint } = await fixture(t);
  const bin = join(root, "bin");
  await mkdir(bin);
  const executable = join(bin, "bb");
  await writeFile(executable, `#!${process.execPath}\nconst assert=require('node:assert/strict');\nassert.deepEqual(process.argv.slice(2), ['agent-split','--check-file']); let input=''; process.stdin.on('data', x => input+=x); process.stdin.on('end', () => { const request=JSON.parse(input); assert.deepEqual(Object.keys(request).sort(),['actual','path','proposed','revision']); assert.equal(request.revision, '${checkpoint.revision}'); if (process.env.WAIT) setInterval(()=>{}, 1000); else console.log(JSON.stringify({status:'preserved'})); });\n`);
  await chmod(executable, 0o755);
  const env = { ...process.env, PATH: bin };
  await write(createBoundaryTool(factories, "write", root, { checkpoint, env }));
  const abort = new AbortController();
  const call = createBoundaryTool(factories, "write", root, { checkpoint, env: { ...env, WAIT: "yes" } });
  const pending = write(call, "cancelled", abort.signal);
  setTimeout(() => abort.abort(), 100);
  await assert.rejects(pending, /Operation aborted/);
  assert.equal(await readCheckpoint(root), null);
  assert.equal(await readFile(join(root, "file"), "utf8"), "proposal\n");
});

test("capture uses ordinary JJ snapshot/ID, verifies ignore before storage, and propagates command failures", async (t) => {
  const { root, checkpoint } = await fixture(t);
  await rm(join(root, "target"), { recursive: true });
  const bin = join(root, "bin");
  await mkdir(bin);
  const executable = join(bin, "jj");
  const git = join(bin, "git");
  const calls = join(root, "calls");
  const env = { ...process.env, PATH: bin };
  await writeFile(git, `#!${process.execPath}\nrequire('node:fs').appendFileSync(${JSON.stringify(calls)},'ignore\\n'); process.exit(process.env.UNIGNORED || (process.env.RECORD_UNIGNORED && process.argv.at(-1).endsWith('commit-boundary.json')) ? 1 : 0);\n`);
  await chmod(git, 0o755);
  const reply = async (revision = checkpoint.revision, extra = {}) => {
    await writeFile(executable, `#!${process.execPath}\nconst fs=require('node:fs'); const args=process.argv.slice(2); fs.appendFileSync(${JSON.stringify(calls)},args.join(' ')+'\\n'); if (args[0]==='workspace') console.log(${JSON.stringify(root)}); else { if (process.env.WAIT) setInterval(()=>{},1000); else if (process.env.CRASH) {process.stderr.write('JJ failed');process.exit(7);} else process.stdout.write(${JSON.stringify(revision)}); }\n`);
    await chmod(executable, 0o755);
    return captureCheckpoint(root, { env: { ...env, ...extra } });
  };
  await assert.rejects(reply(checkpoint.revision, { UNIGNORED: "yes" }), /git exited 1/);
  await assert.rejects(lstat(join(root, "target")), { code: "ENOENT" });
  assert.deepEqual((await readFile(calls, "utf8")).trim().split("\n"), ["workspace --ignore-working-copy root", "ignore"]);
  await writeFile(calls, "");
  await assert.rejects(reply(checkpoint.revision, { RECORD_UNIGNORED: "yes" }), /git exited 1/);
  await assert.rejects(lstat(join(root, "target")), { code: "ENOENT" });
  assert.deepEqual((await readFile(calls, "utf8")).trim().split("\n"), ["workspace --ignore-working-copy root", "ignore", "ignore"]);
  await writeFile(calls, "");
  assert.deepEqual(await reply(), { revision: checkpoint.revision });
  assert.equal(await readFile(join(root, "target/jj-split/commit-boundary.json"), "utf8"), JSON.stringify(checkpoint.revision));
  assert.deepEqual((await readFile(calls, "utf8")).trim().split("\n"), ["workspace --ignore-working-copy root", "ignore", "ignore", "log -r @ --no-graph -T commit_id"]);
  for (const id of ["immutable-C", "a".repeat(39), "b".repeat(65), "A".repeat(40)]) {
    await assert.rejects(reply(id), /Invalid Jujutsu immutable revision/);
    assert.equal(await readCheckpoint(root), checkpoint.revision);
  }
  await assert.rejects(reply(checkpoint.revision, { CRASH: "yes" }), /jj exited 7: JJ failed/);
  const abort = new AbortController();
  const pending = captureCheckpoint(root, { env: { ...env, WAIT: "yes" }, signal: abort.signal });
  setTimeout(() => abort.abort(), 50);
  await assert.rejects(pending, /Operation aborted/);
  assert.equal(await readCheckpoint(root), checkpoint.revision);
});

// Zombies have terminated and cannot write, but an orphan may remain awaiting
// the container's init reaper. Do not mistake that for a surviving checker.
async function processRunning(pid) {
  if (process.platform === "linux") {
    try {
      const stat = await readFile(`/proc/${pid}/stat`, "utf8");
      return !/[)] Z /.test(stat);
    } catch (error) { if (error.code === "ENOENT") return false; throw error; }
  }
  try { process.kill(pid, 0); return true; }
  catch (error) { if (error.code === "ESRCH") return false; throw error; }
}

test("POSIX cancellation terminates a checker descendant after bb closes and holds the native queue through escalation", {
  skip: process.platform === "win32" ? "Windows uses direct child termination" : false,
}, async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  const bin = join(root, "bin");
  await mkdir(bin);
  const executable = join(bin, "bb");
  const pidFile = join(root, "descendant.pid");
  const descendant = `process.on('SIGTERM', () => {}); require('node:fs').writeFileSync(process.env.PID_FILE, String(process.pid)); setInterval(() => {}, 1000);`;
  await writeFile(executable, `#!${process.execPath}\nconst {spawn}=require('node:child_process');\nprocess.on('SIGTERM', () => process.exit(0));\nspawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], {stdio:'ignore',env:process.env});\nsetInterval(() => {}, 1000);\n`);
  await chmod(executable, 0o755);
  let pid;
  t.after(() => { if (pid) { try { process.kill(pid, "SIGKILL"); } catch {} } });
  const abort = new AbortController();
  const call = createBoundaryTool(factories, "write", root, {
    checkpoint, env: { ...process.env, PATH: bin, PID_FILE: pidFile },
  });
  const pending = write(call, "cancelled", abort.signal);
  const rejected = assert.rejects(pending, /Operation aborted/);
  for (let attempt = 0; attempt < 200; attempt++) {
    try { pid = Number(await readFile(pidFile, "utf8")); break; }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    await sleep(10);
  }
  assert.ok(pid, "checker must start its held descendant");
  assert.equal(await processRunning(pid), true);
  let secondFinished = false;
  const second = createBoundaryTool(factories, "write", root);
  const secondPending = write(second, "after cancellation").then(() => { secondFinished = true; });
  const started = Date.now();
  abort.abort();
  await sleep(100);
  assert.equal(secondFinished, false, "bb close alone must not release the queue before group cleanup");
  assert.equal(await readFile(path, "utf8"), "original\n");
  assert.equal(await processRunning(pid), true, "test descendant ignores SIGTERM and requires group escalation");
  await rejected;
  await secondPending;
  assert.ok(Date.now() - started >= 900, "queue must await the escalation grace period");
  assert.equal(await processRunning(pid), false, "cancelled checker's descendant must not survive");
  assert.equal(await readCheckpoint(root), null);
  assert.equal(await readFile(path, "utf8"), "after cancellation");
});


test("record contains only revision; publication always replaces inode, and matching clear leaves empty", async (t) => {
  const { root, checkpoint } = await fixture(t);
  const path = join(root, "target/jj-split/commit-boundary.json");
  const pinned = await open(path, "r");
  try {
    const before = await pinned.stat();
    await storeCheckpoint(root, checkpoint.revision);
    assert.notEqual((await lstat(path)).ino, before.ino);
    assert.equal(await readFile(path, "utf8"), JSON.stringify(checkpoint.revision));
  } finally { await pinned.close(); }
  await forgetCheckpoint(root, checkpoint.revision);
  assert.equal(await readCheckpoint(root), null);
  assert.equal(await readFile(path, "utf8"), "");
  await storeCheckpoint(root, "d".repeat(40));
  await forgetCheckpoint(root, checkpoint.revision);
  assert.equal(await readCheckpoint(root), "d".repeat(40));
});

for (const timing of ["after-open", "after-read", "before-truncate"]) {
  test(`conditional clear preserves a different atomic replacement ${timing}`, async (t) => {
    const { root, checkpoint } = await fixture(t);
    const replacement = "d".repeat(40);
    const pinned = await open(join(root, "target/jj-split/commit-boundary.json"), "r");
    const prototype = Object.getPrototypeOf(pinned);
    // Pause the REAL storage implementation at its FileHandle boundary. There
    // is no production testing hook, lock protocol or alternate clear routine.
    const method = timing === "before-truncate" ? "truncate" : "readFile";
    const original = prototype[method];
    let replaced = false;
    prototype[method] = async function (...args) {
      if (timing !== "after-read") { await storeCheckpoint(root, replacement); replaced = true; }
      const result = await original.apply(this, args);
      if (timing === "after-read") { await storeCheckpoint(root, replacement); replaced = true; }
      return result;
    };
    try { await forgetCheckpoint(root, checkpoint.revision); }
    finally { prototype[method] = original; await pinned.close(); }
    assert.equal(replaced, true);
    assert.equal(await readCheckpoint(root), replacement);
  });
}

test("late check forgets equivalent IDs but cannot forget a different replacement", async (t) => {
  const { root, checkpoint, path } = await fixture(t);
  for (const replacement of [checkpoint.revision, "d".repeat(40)]) {
    await storeCheckpoint(root, checkpoint.revision);
    const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => {
      await storeCheckpoint(root, replacement);
      return { status: "would-lose", reason: "selected hunk no longer available" };
    } });
    assert.deepEqual(await write(call), {
      content: [{ type: "text", text: `Could not write file: ${path}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.` }],
      details: {},
      isError: true,
    });
    assert.equal(await readFile(path, "utf8"), "original\n");
    assert.equal(await readCheckpoint(root), replacement === checkpoint.revision ? null : replacement);
  }
});

test("separate processes publish and conditionally clear without losing a replacement", async (t) => {
  const { root, checkpoint } = await fixture(t);
  const url = new URL("../../config/pi-agent/pi-extensions/commit-boundary/operations.mjs", import.meta.url).href;
  const run = (expression) => promisify(execFile)(process.execPath, ["--input-type=module", "-e",
    `import {storeCheckpoint,forgetCheckpoint} from ${JSON.stringify(url)}; ${expression}`]);
  const replacement = "d".repeat(40);
  for (let i = 0; i < 12; i++) {
    await storeCheckpoint(root, checkpoint.revision);
    await Promise.all([
      run(`await forgetCheckpoint(${JSON.stringify(root)},${JSON.stringify(checkpoint.revision)});`),
      run(`await storeCheckpoint(${JSON.stringify(root)},${JSON.stringify(replacement)});`),
    ]);
    assert.equal(await readCheckpoint(root), replacement);
  }
});

for (const reason of ["boundary already lost", "revision unavailable"]) {
  test(`unusable (${reason}) permits write and forgets without a diagnostic`, async (t) => {
    const { root, checkpoint, path } = await fixture(t);
    const call = createBoundaryTool(factories, "write", root, { checkpoint,
      check: async () => ({ status: "unusable", reason }) });
    await write(call);
    assert.equal(await readFile(path, "utf8"), "proposal\n");
    assert.equal(await readCheckpoint(root), null);
    assert.equal(call.metadata(), undefined);
  });
}

for (const outcome of [
  { status: "would-lose" }, { status: "would-lose", reason: " " },
  { status: "accepted", retire: false }, { status: "preserved", retire: false },
]) {
  test(`malformed checker reply ${JSON.stringify(outcome)} fails open with actual validation error`, async (t) => {
    const { root, checkpoint, path } = await fixture(t);
    const call = createBoundaryTool(factories, "write", root, { checkpoint, check: async () => outcome });
    await write(call);
    assert.equal(await readFile(path, "utf8"), "proposal\n");
    assert.equal(await readCheckpoint(root), null);
    assert.match(call.metadata().error, /Invalid agent-split file-check reply/);
  });
}

for (const cancel of [false, true]) {
  test(`record retirement runs before target verification (${cancel ? "cancel" : "external mutation"})`, async (t) => {
    const { root, checkpoint, path } = await fixture(t);
    const abort = new AbortController();
    const call = createBoundaryTool(factories, "write", root, { checkpoint,
      check: async () => ({ status: "unusable" }),
      forget: async (workspace, revision) => {
        await writeFile(path, "external\n");
        if (cancel) abort.abort();
        await forgetCheckpoint(workspace, revision);
      },
    });
    await assert.rejects(write(call, "proposal\n", abort.signal), cancel ? /Operation aborted/ : /Target changed/);
    assert.equal(await readFile(path, "utf8"), "external\n");
    assert.equal(await readCheckpoint(root), null);
  });
}

test("an equal-ID publication may survive a clear that already opened the previous inode", async (t) => {
  const { root, checkpoint } = await fixture(t);
  const pinned = await open(join(root, "target/jj-split/commit-boundary.json"), "r");
  const prototype = Object.getPrototypeOf(pinned);
  const original = prototype.readFile;
  prototype.readFile = async function (...args) {
    const result = await original.apply(this, args);
    await storeCheckpoint(root, checkpoint.revision);
    return result;
  };
  try { await forgetCheckpoint(root, checkpoint.revision); }
  finally { prototype.readFile = original; await pinned.close(); }
  // Revision equality permits retirement; it does not require chasing an inode
  // published after clear opened its handle. No generation identity is added.
  assert.equal(await readCheckpoint(root), checkpoint.revision);
});

for (const backend of ["native", "proxy"]) {
  test(`authoritative ${backend} route controls root inspection without leaking mode into capture`, async (t) => {
    const { root, checkpoint } = await fixture(t);
    const bin = join(root, "bin");
    await mkdir(bin);
    const log = join(root, "commands");
    const scripts = {
      python3: `const fs=require('node:fs'); const assert=require('node:assert/strict'); assert.deepEqual(process.argv.slice(2), ['/existing-route.py','--','workspace','root']); fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify({tool:'route',proxy:process.env.SANDBOX_PROXY_DIR})+'\\n'); console.log(JSON.stringify({backend:${JSON.stringify(backend)},workspace:${JSON.stringify(root)},destination:null,command:['workspace','root'],hooks:true}));`,
      jj: `const fs=require('node:fs'); const args=process.argv.slice(2); fs.appendFileSync(${JSON.stringify(log)},JSON.stringify({tool:'jj',args,inspect:process.env.JJ_PROXY_INSPECT ?? null})+'\\n'); console.log(args[0]==='workspace' ? ${JSON.stringify(root)} : '${"d".repeat(40)}');`,
      git: `process.exit(0);`,
    };
    for (const [name, source] of Object.entries(scripts)) {
      await writeFile(join(bin, name), `#!${process.execPath}\n${source}\n`);
      await chmod(join(bin, name), 0o755);
    }
    const env = { ...process.env, PATH: bin, SANDBOX_PROXY_DIR: "/existing-service", JJ_ROUTE_HELPER: "/existing-route.py" };
    delete env.JJ_PROXY_INSPECT;
    const call = createProductionBoundaryTool(factories, "write", root, { env,
      check: async (request, context) => {
        assert.equal(request.revision, checkpoint.revision);
        assert.equal(context.env.JJ_PROXY_INSPECT, undefined);
        return accepted;
      },
    });
    await write(call);
    assert.equal(call.metadata(), undefined);
    assert.deepEqual(await captureCheckpoint(root, { env }), { revision: "d".repeat(40) });
    const commands = (await readFile(log, "utf8")).trim().split("\n").map(JSON.parse);
    assert.deepEqual(commands.filter(c => c.tool === "route"), [
      { tool: "route", proxy: "/existing-service" }, { tool: "route", proxy: "/existing-service" },
    ]);
    const rootQuery = { tool: "jj", args: backend === "proxy"
      ? ["workspace", "root"] : ["workspace", "--ignore-working-copy", "root"],
      inspect: backend === "proxy" ? "1" : null };
    assert.deepEqual(commands.filter(c => c.tool === "jj"), [rootQuery, rootQuery,
      { tool: "jj", args: ["log", "-r", "@", "--no-graph", "-T", "commit_id"], inspect: null }]);
    assert.equal(env.JJ_PROXY_INSPECT, undefined);
  });
}

async function guestEditDefinition(root) {
  const changes = {
    CODEX_SANDBOX_TOOL_CONTAINER: "guest-render-fixture",
    CODEX_SANDBOX_GUEST_CWD: root,
    CODEX_SANDBOX_GUEST_REPO: root,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
  };
  const previous = Object.fromEntries(Object.keys(changes).map(key => [key, process.env[key]]));
  Object.assign(process.env, changes);
  try {
    // Load the edited extension through the installed public loader so its
    // public ToolDefinition and TUI imports come from this same installed SDK.
    const loader = new factories.DefaultResourceLoader({
      cwd: root, agentDir: join(root, "agent"), settingsManager: factories.SettingsManager.inMemory(),
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: [fileURLToPath(new URL("../../config/pi-agent/pi-extensions/guest-tools.ts", import.meta.url))],
    });
    await loader.reload();
    const loaded = loader.getExtensions();
    assert.deepEqual(loaded.errors, []);
    const definition = loaded.extensions.flatMap(extension => [...extension.tools.values()])
      .find(tool => tool.definition.name === "edit")?.definition;
    assert.ok(definition?.renderCall && definition?.renderResult);
    return definition;
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
}
const plainTheme = { fg: (_color, text) => text, bg: (_color, text) => text, bold: text => text };
const renderedLines = component => component.render(1024)
  .map(line => stripVTControlCharacters(line).trimEnd()).filter(Boolean);
function renderContext(args, cwd, invalidate = () => {}) {
  return { args, toolCallId: "render", state: {}, cwd, invalidate, lastComponent: undefined,
    executionStarted: true, argsComplete: true, isPartial: false, expanded: true,
    showImages: false, outputPadY: 0, outputPad: 0, isError: false, durationMs: undefined };
}
const renderOptions = { expanded: true, isPartial: false };

test("guest edit renders only its actual refusal even after a pending native ENOENT preview completes", async (t) => {
  if (process.versions.bun) {
    // Let Pi's Node loader own SDK aliasing rather than Bun's native TS loader.
    // A fresh process also excludes other suites' process-wide module mocks.
    const { stdout } = await promisify(execFile)("node", ["--test", "--test-reporter=tap",
      "--test-name-pattern=^guest edit renders only", fileURLToPath(import.meta.url)]);
    assert.match(stdout, /# pass 1\n/);
    return;
  }
  const { root, checkpoint, path } = await fixture(t);
  const host = join(root, "host-display");
  await mkdir(host);
  await writeFile(path, "original\nsecond\n");
  const args = { path: "file", edits: [
    { oldText: "original", newText: "proposal" }, { oldText: "second", newText: "changed second" },
  ] };
  const call = createBoundaryTool(factories, "edit", root, { checkpoint,
    check: async () => ({ status: "would-lose", reason: "canonical reason not displayed" }),
  });
  const result = await call.tool.execute("render", args);
  const expected = `Could not edit file: ${path}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`;
  assert.deepEqual(result, { content: [{ type: "text", text: expected }], details: {}, isError: true });
  const guest = await guestEditDefinition(root);
  const native = factories.createEditToolDefinition(host);
  let completed;
  const pending = new Promise(resolve => { completed = resolve; });
  const context = renderContext(args, host, completed);
  // A previous local renderer may still have a preview in flight. Use only
  // public renderer contexts/components; never inspect or modify SDK state.
  const oldNativeCall = native.renderCall(args, plainTheme, context);
  const guestCall = guest.renderCall(args, plainTheme, { ...context, lastComponent: oldNativeCall });
  const guestResult = guest.renderResult(result, renderOptions, plainTheme, { ...context, isError: true });
  assert.deepEqual(renderedLines(guestCall), ["edit file"]);
  assert.deepEqual(renderedLines(guestResult), [expected]);
  await pending;
  // The native renderer still truthfully reports its own namespace's absence.
  native.renderCall(args, plainTheme, { ...context, lastComponent: oldNativeCall });
  assert.deepEqual(renderedLines(oldNativeCall), ["edit file", "Could not edit file: file. Error code: ENOENT."]);
  const afterCall = guest.renderCall(args, plainTheme, { ...context, lastComponent: guestCall });
  const afterResult = guest.renderResult(result, renderOptions, plainTheme,
    { ...context, lastComponent: guestResult, isError: true });
  assert.deepEqual([...renderedLines(afterCall), ...renderedLines(afterResult)], ["edit file", expected]);
  assert.equal(await readFile(path, "utf8"), "original\nsecond\n");
});

test("guest edit uses actual success, mismatch and missing-file results without any host preview", async (t) => {
  if (process.versions.bun) {
    const { stdout } = await promisify(execFile)("node", ["--test", "--test-reporter=tap",
      "--test-name-pattern=^guest edit uses actual", fileURLToPath(import.meta.url)]);
    assert.match(stdout, /# pass 1\n/);
    return;
  }
  const { root, path } = await fixture(t);
  const host = join(root, "host-display");
  await mkdir(host);
  // The same relative path names unrelated bytes on the host.
  await writeFile(join(host, "file"), "host-only bytes must never appear\n");
  const guest = await guestEditDefinition(root);
  factories.initTheme("dark", false);
  let invalidations = 0;
  const args = { path: "file", edits: [{ oldText: "original", newText: "proposal" }] };
  const context = renderContext(args, host, () => { invalidations++; });
  const header = guest.renderCall(args, plainTheme, context);
  assert.deepEqual(renderedLines(header), ["edit file"]);
  await sleep(30);
  assert.equal(invalidations, 0, "guest calls must not start an asynchronous local preview");
  const result = await edit(createBoundaryTool(factories, "edit", root));
  const output = guest.renderResult(result, renderOptions, plainTheme, context);
  const authoritative = factories.createEditToolDefinition(root)
    .renderResult(result, renderOptions, plainTheme, renderContext(args, root));
  assert.deepEqual(renderedLines(output), renderedLines(authoritative));
  assert.match(renderedLines(output).join("\n"), /proposal/);
  assert.doesNotMatch(renderedLines(output).join("\n"), /host-only|ENOENT|Could not/);
  assert.equal(await readFile(path, "utf8"), "proposal\n");
  for (const errorArgs of [args, { path: "missing", edits: args.edits }]) {
    const tool = createBoundaryTool(factories, "edit", root);
    let actualError;
    try { await tool.tool.execute("error", errorArgs); }
    catch (error) { actualError = error; }
    assert.ok(actualError);
    if (errorArgs.path === "missing") assert.equal(actualError.message, "Could not edit file: missing. Error code: ENOENT.");
    else assert.doesNotMatch(actualError.message, /ENOENT/);
    const errorResult = { content: [{ type: "text", text: actualError.message }], details: {}, isError: true };
    const errorContext = { ...renderContext(errorArgs, host), isError: true };
    assert.deepEqual(renderedLines(guest.renderCall(errorArgs, plainTheme, errorContext)), [`edit ${errorArgs.path}`]);
    assert.deepEqual(renderedLines(guest.renderResult(errorResult, renderOptions, plainTheme, errorContext)), [actualError.message]);
  }
  const native = factories.createEditToolDefinition(host);
  const nativeArgs = { path: "file", edits: [{ oldText: "host-only bytes must never appear", newText: "native preview still works" }] };
  let previewReady;
  const preview = new Promise(resolve => { previewReady = resolve; });
  const nativeContext = renderContext(nativeArgs, host, previewReady);
  const nativeCall = native.renderCall(nativeArgs, plainTheme, nativeContext);
  await preview;
  native.renderCall(nativeArgs, plainTheme, { ...nativeContext, lastComponent: nativeCall });
  assert.match(renderedLines(nativeCall).join("\n"), /native preview still works/);
});

test("real native guards take zero snapshots; capture takes one only after ignore validation", async (t) => {
  const { root, path } = await fixture(t);
  // The environment wrapper selects real local JJ, with sandbox authority off.
  // Observe immutable IDs and operation count using explicit read-only queries.
  const jj = async (...args) => (await promisify(execFile)("jj", args, { cwd: root })).stdout.trim();
  await jj("git", "init", "--colocate");
  await writeFile(join(root, ".gitignore"), "/target/jj-split/\n");
  const snapshot = await jj("log", "-r", "@", "--no-graph", "-T", "commit_id");
  await storeCheckpoint(root, snapshot);
  const revision = () => jj("log", "--ignore-working-copy", "-r", "@", "--no-graph", "-T", "commit_id");
  const operations = async () => (await jj("op", "log", "--ignore-working-copy", "--no-graph", "-T", 'id ++ "\n"')).split("\n").length;
  const before = await operations();
  await writeFile(path, "unsnapshotted external bytes\n");
  for (const content of ["first proposal\n", "second proposal\n"]) {
    const call = createProductionBoundaryTool(factories, "write", root, {
      check: async request => { assert.equal(request.revision, snapshot); return accepted; },
    });
    await write(call, content);
    assert.equal(call.metadata(), undefined);
    assert.equal(await revision(), snapshot);
    assert.equal(await operations(), before);
  }
  const captured = await captureCheckpoint(root);
  assert.notEqual(captured.revision, snapshot);
  assert.equal(await operations(), before + 1);
  assert.equal(await revision(), captured.revision);
  assert.doesNotMatch(await jj("file", "list", "--ignore-working-copy", "-r", captured.revision), /target\/jj-split/);
  // Previously-created record becomes exposed if the ignore is removed. Root
  // discovery must not snapshot it while trying to validate that prerequisite.
  await writeFile(join(root, ".gitignore"), "");
  await assert.rejects(captureCheckpoint(root), /requires ignored target\/jj-split/);
  assert.equal(await revision(), captured.revision);
  assert.equal(await operations(), before + 1);
  assert.equal(await readCheckpoint(root), captured.revision);
  assert.doesNotMatch(await jj("file", "list", "--ignore-working-copy", "-r", "@"), /target\/jj-split/);
});
