import { expect, test } from "bun:test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { providerCallsFile } from "./held-tool-extension.ts";
import { jsonl, until } from "./source-runtime.ts";

const source = process.env.PI_TEST_COMMIT_BOUNDARY_SOURCE;
const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG || !source);
for (const mode of ["native", "guest"] as const) {
  sourceTest(`actual ${mode} boundary protects worker A after exit from fresh worker B, warns once and permits resumed retry`, async () => {
    const { AgentManager, SUBAGENT_DIR } = await import("../core.ts");
    const root = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, `domain-${mode}-`));
    const cwd = join(root, "repo");
    const bin = join(root, "bin");
    mkdirSync(cwd); mkdirSync(bin);
    const template = `boundary-${mode}-${crypto.randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${template}.md`);
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    const extensions = join(source!, "config/pi-agent/pi-extensions");
    writeFileSync(templateFile, `---\nname: ${template}\ntools: write,edit\nextensions: ${join(extensions, "commit-boundary.ts")}${mode === "guest" ? `, ${join(extensions, "guest-tools.ts")}` : ""}\n---\n`);
    // Keep the production dispatchers on PATH; test-environment supplies their
    // real local binaries after these aliases, without sandbox proxy authority.
    symlinkSync(join(source!, "libexec/agent-wrappers/bb"), join(bin, "bb"));
    symlinkSync(join(source!, "libexec/agent-wrappers/jj"), join(bin, "jj"));
    const updates: Record<string, string | undefined> = {
      PATH: `${bin}:${process.env.PATH}`,
      BB_SOURCE_ROOT: source,
      BB_REAL: process.env.DOTFILES_TEST_BB_REAL || Bun.which("bb") || undefined,
      CODEX_SANDBOX_TOOL_CONTAINER: mode === "guest" ? "local-regression-fixture" : undefined,
      CODEX_SANDBOX_TOOL_CONNECT: join(source!, "tools/codex-sandbox/tests/fixtures/local-tool-connect.py"),
      CODEX_SANDBOX_GUEST_CWD: cwd,
      CODEX_SANDBOX_GUEST_REPO: cwd,
      CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
      CODEX_SANDBOX_TOOL_SOCKET: join(root, "worker.sock"),
      CODEX_SANDBOX_PI_TOOL_MODULE: pathToFileURL(join(process.env.PI_TEST_CORE_ROOT!, "packages/coding-agent/src/index.ts")).href,
    };
    const previous = Object.fromEntries(Object.keys(updates).map(key => [key, process.env[key]]));
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    const jj = (...args: string[]) => {
      const result = spawnSync("jj", args, { cwd, env: process.env, encoding: "utf8", timeout: 30000 });
      if (result.status !== 0) throw new Error(`Owned JJ fixture failed: jj ${args.join(" ")}: ${result.error || result.stderr}. Run via dotfiles dev/test-environment for native tools.`);
      return result.stdout.trim();
    };
    let worker: ChildProcess | undefined;
    let workerError = "";
    let manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    let parentSessionId = crypto.randomUUID();
    const task = (content: string) => `invoke-tool:${JSON.stringify({ name: "write", args: { path: "rules.md", content } })}`;
    const settled = async (name: string) => {
      const info = () => manager.getAgentInfo(name, parentSessionId);
      await until(() => info().status === "completed" && !info().childProcess, `${name} settles and owned Pi child exits`, 20000);
      return structuredClone(info());
    };
    const spawnAgent = (name: string, message: string) => manager.spawnAgent({ task_name: name, message, cwd, parentSessionId, agent_type: template,
      inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
    const recordFile = join(cwd, "target/jj-split/commit-boundary.json");
    const recordContents = () => existsSync(recordFile) ? readFileSync(recordFile, "utf8").trim() : "";
    try {
      // Native tools come from the documented dotfiles test environment; all
      // repository commands run exclusively inside this owned disposable repo.
      jj("git", "init", "--colocate");
      jj("config", "set", "--repo", "user.name", "Checkpoint regression");
      jj("config", "set", "--repo", "user.email", "checkpoint@example.invalid");
      writeFileSync(join(cwd, ".gitignore"), "/target/jj-split/\n");
      writeFileSync(join(cwd, "rules.md"), "alpha\nrule one\nrule two\nomega\n");
      writeFileSync(join(cwd, "unrelated.txt"), "original\n");
      jj("commit", "-m", "owned boundary fixture baseline");
      writeFileSync(join(cwd, "unrelated.txt"), "unrelated formatting\n");
      if (mode === "guest") {
        worker = spawn(process.env.PI_TEST_BUN!, ["--no-install", `--tsconfig-override=${process.env.PI_TEST_CORE_TSCONFIG}`,
          join(source!, "tools/codex-sandbox/image/tool-worker.mjs")], { cwd, env: process.env, stdio: ["ignore", "ignore", "pipe"] });
        worker.stderr!.on("data", data => { workerError += data.toString(); });
        await until(() => existsSync(updates.CODEX_SANDBOX_TOOL_SOCKET!), `source-backed real guest worker socket: ${workerError}`);
      }
      await manager.ready();
      const reorganized = "alpha\nomega\n\n## Policy\nrule one\nrule two\n";
      const extracted = "alpha\nomega\n\n## Policy\nsee skill two\n";
      // Ordinary two-worker workflow, with no helper restore or seeded record:
      // A finishes before a fresh B starts editing.
      await spawnAgent("set-rules", task(reorganized));
      const first = await settled("set-rules");
      const firstPid = jsonl(providerCallsFile(first.sessionFile))[0].pid;
      const firstSessionId = jsonl(first.sessionFile).find(entry => entry.type === "session").id;
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(reorganized);
      expect(jsonl(first.sessionFile).find(entry => entry.message?.toolName === "write").message.isError).not.toBe(true);
      expect(existsSync(recordFile)).toBe(true);
      const record = readFileSync(recordFile, "utf8");
      expect(JSON.parse(record)).toBe(jj("log", "-r", "@", "--no-graph", "-T", "commit_id"));

      await manager.sendMessage(parentSessionId, "set-rules", "No write in this turn.");
      await settled("set-rules");
      expect(readFileSync(recordFile, "utf8")).toBe(record);

      // The record belongs to the working copy, not the manager or parent.
      await manager.shutdown();
      manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
      parentSessionId = crypto.randomUUID();
      await manager.ready();
      expect(readFileSync(recordFile, "utf8")).toBe(record);
      await spawnAgent("update-rules", task(extracted));
      const warned = await settled("update-rules");
      const warningPid = jsonl(providerCallsFile(warned.sessionFile))[0].pid;
      expect(warned.id).not.toBe(first.id);
      expect(warned.sessionFile).not.toBe(first.sessionFile);
      expect(warningPid).not.toBe(firstPid);
      expect(jsonl(warned.sessionFile).find(entry => entry.type === "session").id).not.toBe(firstSessionId);
      const warning = jsonl(warned.sessionFile).filter(entry => entry.message?.toolName === "write").at(-1).message;
      expect(warning.isError).toBe(true);
      const warningText = warning.content.map((block: any) => block.text || "").join("\n");
      expect(warningText).toBe(`Could not write file: ${join(cwd, "rules.md")}. This edit would make the earlier changes to this file no longer separately selectable by \`agent-split\`. No file was changed. Commit first if that separation matters, or retry to proceed.`);
      expect(warningText).not.toMatch(/[\r\n]/);
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(reorganized);
      expect(recordContents()).toBe("");

      // A read-only turn after retirement must not resurrect the record.
      await manager.sendMessage(parentSessionId, "update-rules", "No write in this turn.");
      await settled("update-rules");
      expect(recordContents()).toBe("");
      const beforeRetryCalls = jsonl(providerCallsFile(warned.sessionFile)).length;
      await manager.sendMessage(parentSessionId, "update-rules", task(extracted));
      const retried = await settled("update-rules");
      expect(retried.id).toBe(warned.id);
      expect(retried.sessionFile).toBe(warned.sessionFile);
      const retryPid = jsonl(providerCallsFile(warned.sessionFile))[beforeRetryCalls].pid;
      expect(retryPid).not.toBe(warningPid);
      const writes = jsonl(warned.sessionFile).filter(entry => entry.message?.toolName === "write");
      expect(writes).toHaveLength(2);
      expect(writes.at(-1).message.isError).not.toBe(true);
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(extracted);
      expect(readFileSync(join(cwd, "unrelated.txt"), "utf8")).toBe("unrelated formatting\n");
    } finally {
      await manager.shutdown();
      if (worker && worker.exitCode === null && worker.signalCode === null) {
        const exited = once(worker, "exit"); worker.kill("SIGTERM"); await exited;
      }
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
      rmSync(templateFile, { force: true }); rmSync(root, { recursive: true, force: true });
    }
  }, 60000);
}
