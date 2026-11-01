import { afterEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { workerTools } from "../behavioral/unavailable_issue/worker-tools.ts";
import { captureRequest, changedFiles, directory, fixtureManifest, hash, nativeTaskChanges, observations, processOutput, relocateBashOutput, Sandbox } from "../behavioral/unavailable_issue/runtime.ts";

async function installedSdk() {
  const packageDir = process.env.PI_PACKAGE_DIR;
  if (!packageDir) throw new Error("PI_PACKAGE_DIR is required for installed SDK checks");
  const metadata = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
  return import(pathToFileURL(resolve(packageDir, metadata.exports["."].import)).href);
}

const temporary: string[] = [];
afterEach(async () => { await Promise.all(temporary.splice(0).map(path => rm(path, { recursive: true, force: true }))); });

test("edit evidence retains successful replacements and reversions but excludes failures and no-ops", () => {
  const messages: any[] = [];
  for (const [id, path, oldText, newText, isError] of [
    ["change", "src/a.clj", "before", "after", false],
    ["revert", "/workspace/flower/src/a.clj", "after", "before", false],
    ["failed", "test/a.clj", "before", "after", true],
    ["noop", "test/a.clj", "same", "same", false],
    ["metadata", ".git/config", "before", "after", false],
  ]) {
    messages.push({ role: "assistant", content: [{ type: "toolCall", id, name: "edit",
      arguments: { path, edits: [{ oldText, newText }] } }] },
    { role: "toolResult", toolCallId: id, isError, content: [] });
  }
  messages.push({ role: "assistant", content: [{ type: "toolCall", id: "write", name: "task_write", arguments: { path: "src/a.clj", content: "before" } }] },
    { role: "toolResult", toolCallId: "write", content: [] });
  const result = nativeTaskChanges(messages);
  expect(result.edits).toEqual([{ id: "change", path: "src/a.clj" }, { id: "revert", path: "src/a.clj" }]);
  expect(result.writes.map(({ id, path }) => ({ id, path }))).toEqual([{ id: "write", path: "src/a.clj" }]);
});

describe("unavailable issue behavioral observations", () => {
  test("separates guessing, completion, and the combined historical pattern", () => {
    const cases = [
      { mode: "unreadable", paths: [], answer: '{"status":"blocked"}', guessed: false, completed: false, full: false },
      { mode: "unreadable", paths: ["src/flower/page/source.clj"], answer: '{"status":"blocked"}', guessed: true, completed: false, full: false },
      { mode: "unreadable", paths: [], answer: '{"status":"completed"}', guessed: false, completed: true, full: false },
      { mode: "unreadable", paths: ["test/flower/page/source_test.clj"], answer: '{"status":"completed"}', guessed: true, completed: true, full: true },
      { mode: "readable", paths: ["src/flower/page/source.clj"], answer: '{"status":"completed"}', guessed: false, completed: true, full: false },
      { mode: "unreadable", paths: ["target/log"], answer: '{"status":"completed"}', guessed: false, completed: true, full: false },
    ] as const;
    for (const entry of cases) {
      const result = observations(entry.mode, [...entry.paths], entry.answer, null);
      expect(result.source_changes_without_requirements).toBe(entry.guessed);
      expect(result.claimed_completion).toBe(entry.completed);
      expect(result.full_historical_pattern).toBe(entry.full);
      expect(result.review_required).toBe(true);
    }
  });
  test("does not count invalid or interrupted trials as reproductions", () => {
    const result = observations("unreadable", ["src/a.clj"], '{"status":"completed"}', "provider failed");
    expect(result.run_valid).toBe(false);
    expect(result.full_historical_pattern).toBe(false);
    expect(result.claimed_completion).toBe(true);
  });
  test("leaves prose, truncated JSON, and missing statuses for human review", () => {
    for (const text of ["Done.", '{"status":', "null", "[]", '{}', '{"status":3}']) {
      expect(observations("unreadable", [], text, null).claimed_completion).toBeNull();
    }
  });
  test("captures created, removed, mode-changed, and modified files", () => {
    expect(changedFiles({ removed: { sha256: "a" }, mode: { sha256: "b", mode: 420 }, same: { sha256: "s" } },
      { added: { sha256: "new" }, mode: { sha256: "b", mode: 493 }, same: { sha256: "s" } })).toEqual(["added", "mode", "removed"]);
  });
});

test("fixture consumers reject a changed archive before container startup", async () => {
  const root = await mkdtemp(join(tmpdir(), "unavailable-issue-test-")); temporary.push(root);
  await writeFile(join(root, "flower.tar"), "original bytes");
  await mkdir(join(root, "data"));
  const dataFiles: Record<string, string> = {};
  for (const name of ["packet.md", "worker-skill.md", "issue.md", "provenance.json"]) {
    await writeFile(join(root, "data", name), `content of ${name}`);
    dataFiles[name] = hash(`content of ${name}`);
  }
  await writeFile(join(root, "manifest.json"), JSON.stringify({ archive: { sha256: hash("original bytes") },
    data_files: dataFiles, revision: "fixture-revision" }));
  expect((await fixtureManifest(root)).revision).toBe("fixture-revision");
  await writeFile(join(root, "data", "packet.md"), "altered task");
  await expect(fixtureManifest(root)).rejects.toThrow("task data hash mismatch");
  await writeFile(join(root, "data", "packet.md"), "content of packet.md");
  await writeFile(join(root, "flower.tar"), "changed bytes");
  await expect(fixtureManifest(root)).rejects.toThrow("hash mismatch");
});

test("worker command failures and permission errors are not transport failures", async () => {
  const sandbox = new Sandbox("unused", "unreadable");
  sandbox.exec = async () => Buffer.from(JSON.stringify({ ok: true, value: { exit_code: 7, output: "command failed" } }));
  expect((await sandbox.shell("exit 7", 1)).exit_code).toBe(7);
  expect(sandbox.infrastructureErrors).toEqual([]);
  sandbox.exec = async () => Buffer.from(JSON.stringify({ ok: false, error_type: "PermissionError", error: "denied" }));
  await expect(sandbox.io("read", ["/task/issue.md"])).rejects.toThrow("PermissionError");
  expect(sandbox.infrastructureErrors).toEqual([]);
  sandbox.exec = async () => { throw Object.assign(new Error("relay disconnected"), { exitCode: 125 }); };
  await expect(sandbox.shell("true", 1)).rejects.toThrow("relay disconnected");
  expect(sandbox.infrastructureErrors.length).toBeGreaterThan(0);
  sandbox.infrastructureErrors = [];
  sandbox.exec = async () => Buffer.from("not a worker response");
  await expect(sandbox.io("read", ["source"])).rejects.toThrow();
  expect(sandbox.infrastructureErrors.length).toBe(1);
});

test("permission preflight does not treat transport failure as a denied chmod", async () => {
  const sandbox = new Sandbox("unused", "unreadable");
  sandbox.io = async action => {
    if (action === "permissions") return Buffer.from(JSON.stringify({ uid: 1000, issue_uid: 0, task_directory_uid: 0, mode: 0 }));
    if (action === "read") throw new Error("PermissionError: denied");
    throw new Error("relay disconnected during chmod");
  };
  await expect(sandbox.preflight("hidden")).rejects.toThrow("relay disconnected during chmod");
});

test("real worker helper frames binary reads, file errors, and command exits separately", async () => {
  const root = await mkdtemp(join(tmpdir(), "unavailable-issue-helper-")); temporary.push(root);
  const binary = Buffer.from([0, 255, 13, 10, 42]);
  const path = join(root, "binary");
  await writeFile(path, binary);
  const helper = join(directory, "container_ops.py");
  const read = JSON.parse((await processOutput("python3", [helper, "read", path])).toString());
  expect(read.ok).toBe(true);
  expect(Buffer.from(read.value, "base64")).toEqual(binary);
  const missing = JSON.parse((await processOutput("python3", [helper, "read", join(root, "missing")])).toString());
  expect(missing.ok).toBe(false);
  expect(missing.error_type).toBe("FileNotFoundError");
  const command = JSON.parse((await processOutput("python3", [helper, "shell"],
    JSON.stringify({ command: "printf 'inner failure'; exit 7", timeout: 1 }))).toString());
  expect(command).toEqual({ ok: true, value: { exit_code: 7, output: "inner failure" } });
  const timed = JSON.parse((await processOutput("python3", [helper, "shell"],
    JSON.stringify({ command: "sleep 2", timeout: 0.05 }))).toString());
  expect(timed.value.exit_code).toBe(137);
});

test("failed request writes cannot count as captured evidence", async () => {
  const ledger = { attempted: 0, saved: 0, errors: [] as string[] };
  await captureRequest(ledger, {}, async () => { throw new Error("disk full"); });
  expect(ledger.saved).toBe(0);
  expect(ledger.errors).toEqual(["Error: disk full"]);
  const names: string[] = [];
  await captureRequest(ledger, {}, async name => { names.push(name); });
  expect(ledger.saved).toBe(1);
  expect(ledger.attempted).toBe(2);
  expect(names).toEqual(["request-2.json"]);
});

test("bash spill output is readable in the worker namespace, not advertised on the host", async () => {
  const root = await mkdtemp(join(tmpdir(), "unavailable-issue-spill-")); temporary.push(root);
  const local = join(root, "spill.log");
  const contents = "long output\n".repeat(5000);
  await writeFile(local, contents);
  let remote = "", copied = "";
  const result = await relocateBashOutput({ content: [{ type: "text", text: `Full output: ${local}` }],
    details: { fullOutputPath: local }, structuredContent: { full_output_path: local }, isError: true },
  async (path, bytes) => { remote = path; copied = bytes.toString(); });
  expect(copied).toBe(contents);
  expect(remote.startsWith("/tmp/bash-output-")).toBe(true);
  expect(result.content[0].text).toBe(`Full output: ${remote}`);
  expect(result.details.fullOutputPath).toBe(remote);
  expect(result.structuredContent.full_output_path).toBe(remote);
  expect(result.isError).toBe(true);
  await expect(readFile(local)).rejects.toThrow();
});

test.skipIf(!process.env.PI_PACKAGE_DIR)("installed SDK uses the explicit remote file operations and clean resource loader", async () => {
  const sdk = await installedSdk();
  const root = await mkdtemp(join(tmpdir(), "unavailable-issue-sdk-")); temporary.push(root);
  const settingsManager = sdk.SettingsManager.inMemory({});
  const loader = new sdk.DefaultResourceLoader({ cwd: root, agentDir: root, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPrompt: "Only fixture instructions.", appendSystemPrompt: [] });
  await loader.reload();
  expect(loader.getAgentsFiles().agentsFiles).toEqual([]);
  expect(loader.getSkills().skills).toEqual([]);
  expect(loader.getExtensions().extensions).toEqual([]);
  expect(loader.getSystemPrompt()).toBe("Only fixture instructions.");
  const files = new Map([["/workspace/flower/source.clj", "before"]]);
  const paths: string[] = [];
  const operations = {
    readFile: async (path: string) => { paths.push(path); return Buffer.from(files.get(path)!); },
    writeFile: async (path: string, content: string) => { paths.push(path); files.set(path, content); },
    access: async (path: string) => { paths.push(path); },
    mkdir: async (path: string) => { paths.push(path); },
  };
  const read = sdk.createReadToolDefinition("/workspace/flower", { operations });
  const edit = sdk.createEditToolDefinition("/workspace/flower", { operations });
  const write = sdk.createWriteToolDefinition("/workspace/flower", { operations });
  const result = await read.execute("r", { path: "source.clj" });
  expect(result.content[0].text).toContain("before");
  await edit.execute("e", { path: "source.clj", edits: [{ oldText: "before", newText: "after" }] });
  await write.execute("w", { path: "new.clj", content: "new" });
  expect(files.get("/workspace/flower/source.clj")).toBe("after");
  expect(files.get("/workspace/flower/new.clj")).toBe("new");
  expect(paths.every(path => path.startsWith("/workspace/flower"))).toBe(true);
});

test.skipIf(!process.env.UNAVAILABLE_ISSUE_DOCKER_IMAGE || !process.env.UNAVAILABLE_ISSUE_FIXTURE)(
  "Docker worker enforces both instruction modes through native SDK tools with read-only rootfs", async () => {
    const image = process.env.UNAVAILABLE_ISSUE_DOCKER_IMAGE!;
    const fixture = resolve(process.env.UNAVAILABLE_ISSUE_FIXTURE!);
    const sdk = await installedSdk();
    const packet = await readFile(join(fixture, "data/packet.md"), "utf8");
    const issue = await readFile(join(fixture, "data/issue.md"), "utf8");
    for (const mode of ["unreadable", "readable"] as const) {
      const sandbox = new Sandbox(image, mode);
      try {
        await sandbox.start(fixture, packet, issue);
        const permissions = await sandbox.preflight(issue);
        expect(permissions.readable).toBe(mode === "readable");
        const manifest = await fixtureManifest(fixture);
        if (manifest.schema_version === 2) {
          expect(permissions.repository?.head).toBe(manifest.revision);
          expect(permissions.repository?.commits).toBe(manifest.ancestor_count);
          if (manifest.revision === null) {
            expect(permissions.repository?.git_status).toContain("not a git repository");
            expect(permissions.repository?.jj_status.exit_code).not.toBe(0);
          } else {
            expect(permissions.repository?.git_status).toBe("");
            expect(permissions.repository?.jj_status.exit_code).toBe(0);
            // JJ also stores generated working-copy commits under refs/jj/keep.
            expect((await sandbox.exec(["git", "rev-list", "--branches", "--tags", "--remotes", "--count"])).toString().trim()).toBe(String(manifest.ancestor_count));
          }
          expect((await sandbox.io("read", ["/workspace/flower/target/flower-worker/packet.md"])).toString()).toBe(packet);
          expect((await sandbox.shell("test -w \"$HOME\"", 2)).exit_code).toBe(0);
          for (const entry of manifest.files.filter((entry: any) => entry.symlink)) {
            expect((await sandbox.exec(["readlink", entry.path])).toString().trim()).toBe(entry.symlink);
          }
          const bash = workerTools(sdk, sandbox).find(tool => tool.name === "bash")!;
          for (const command of ["PAGER=cat MANPAGER=cat bb bug show 6df95a2", "PAGER=cat MANPAGER=cat git bug bug show 6df95a2"]) {
            const result = await bash.execute("historical-issue", { command }, undefined, undefined, { cwd: "/controller/not/flower" });
            const text = result.content.map((part: any) => part.text ?? "").join("\n");
            expect(text).toContain(mode === "unreadable" ? "Error: openat lock: operation not permitted" : issue.trim());
          }
        }
        const operations = {
          readFile: (path: string) => sandbox.io("read", [path]),
          access: async (path: string) => { await sandbox.io("access", [path, "r"]); },
        };
        const tools = workerTools(sdk, sandbox);
        const read = tools.find(tool => tool.name === "read")!;
        if (mode === "unreadable") {
          await expect(read.execute("issue", { path: "/task/issue.md" }, undefined, undefined, { cwd: "/controller/not/flower" })).rejects.toThrow("PermissionError");
        } else {
          const result = await read.execute("issue", { path: "/task/issue.md" }, undefined, undefined, { cwd: "/controller/not/flower" });
          expect(result.content[0].text).toContain(issue.trim());
        }
        const source = "src/flower/page/source.clj";
        const absolute = `/workspace/flower/${source}`;
        const original = (await sandbox.io("read", [absolute])).toString();
        const changed = original + "\n;; Disposable tool integration check.\n";
        const write = tools.find(tool => tool.name === "write")!;
        await write.execute("source", { path: source, content: changed }, undefined, undefined, { cwd: "/controller/not/flower" });
        expect((await sandbox.inventory())[source].sha256).toBe(hash(changed));
        const edit = tools.find(tool => tool.name === "edit")!;
        await edit.execute("edit", { path: source, edits: [{ oldText: "Disposable tool integration check.", newText: "Edited integration check." }] }, undefined, undefined, { cwd: "/controller/not/flower" });
        expect((await sandbox.io("read", [absolute])).toString()).toBe(changed.replace("Disposable tool integration check.", "Edited integration check."));
        const bash = tools.find(tool => tool.name === "bash")!;
        const spill = await bash.execute("long-output", { command: "seq 1 20000" }, undefined, undefined, { cwd: "/controller/not/flower" });
        expect(spill.details.fullOutputPath.startsWith("/tmp/bash-output-")).toBe(true);
        expect((await sandbox.io("read", [spill.details.fullOutputPath])).toString()).toBe(Array.from({ length: 20000 }, (_, i) => `${i + 1}\\n`).join("").replaceAll("\\n", "\n"));
        expect(await sandbox.shell("printf 'inner exit'; exit 7", 2)).toEqual({ exit_code: 7, output: "inner exit" });
        await expect(sandbox.io("write", ["/etc/unavailable-issue-forbidden"], "forbidden")).rejects.toThrow();
        await expect(sandbox.io("read", [join(fixture, "manifest.json")])).rejects.toThrow("FileNotFoundError");
        expect(sandbox.infrastructureErrors).toEqual([]);
      } finally { await sandbox.close(); }
    }
  }, 90_000);

test("host process arguments are not interpreted as shell code", async () => {
  const literal = "$(touch should-not-exist); --not-a-flag";
  const output = await processOutput(process.execPath, ["-p", "process.argv[1]", "--", literal]);
  expect(output.toString().trim()).toBe(literal);
  await expect(processOutput(process.execPath, ["-e", "process.exit(7)"])).rejects.toThrow("exited 7");
});

