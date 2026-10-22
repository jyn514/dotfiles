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
  sourceTest(`actual ${mode} boundary survives manager hibernation, warns once, retires and permits retry in another PID`, async () => {
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
    symlinkSync(join(source!, "libexec/agent-wrappers/bb"), join(bin, "bb"));
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
    const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    const parentSessionId = crypto.randomUUID();
    const task = (content: string) => `invoke-tool:${JSON.stringify({ name: "write", args: { path: "rules.md", content } })}`;
    const info = () => manager.getAgentInfo("boundary", parentSessionId);
    const settled = async () => {
      await until(() => info().status === "completed" && !info().childProcess, "actual boundary settles and owned Pi child exits", 20000);
      return structuredClone(info());
    };
    try {
      // Native tools come from the documented dotfiles test environment; all
      // repository commands run exclusively inside this owned disposable repo.
      jj("git", "init", "--colocate");
      jj("config", "set", "--repo", "user.name", "Checkpoint regression");
      jj("config", "set", "--repo", "user.email", "checkpoint@example.invalid");
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
      await manager.spawnAgent({ task_name: "boundary", message: task(reorganized), cwd, parentSessionId, agent_type: template,
        inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      const first = await settled();
      const firstPid = jsonl(providerCallsFile(first.sessionFile))[0].pid;
      const sessionId = jsonl(first.sessionFile).find(entry => entry.type === "session").id;
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(reorganized);
      expect(jsonl(first.sessionFile).find(entry => entry.message?.toolName === "write").message.isError).not.toBe(true);
      const checkpointCommit = jj("log", "-r", "@", "--no-graph", "-T", "commit_id");
      // A no-write settlement must export the existing controller checkpoint.
      await manager.sendMessage(parentSessionId, "boundary", "No write in this turn.");
      await settled();
      const beforeWarningCalls = jsonl(providerCallsFile(first.sessionFile)).length;
      await manager.sendMessage(parentSessionId, "boundary", task(extracted));
      const warned = await settled();
      expect(warned.id).toBe(first.id);
      expect(warned.sessionFile).toBe(first.sessionFile);
      const warningPid = jsonl(providerCallsFile(first.sessionFile))[beforeWarningCalls].pid;
      expect(warningPid).not.toBe(firstPid);
      expect(jsonl(first.sessionFile).find(entry => entry.type === "session").id).toBe(sessionId);
      const warning = jsonl(first.sessionFile).filter(entry => entry.message?.toolName === "write").at(-1).message;
      expect(warning.isError).toBe(true);
      expect(warning.content.map((block: any) => block.text || "").join("\n")).toMatch(/checkpointed changes.*no longer separately selectable/);
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(reorganized);
      const beforeRetryCalls = jsonl(providerCallsFile(first.sessionFile)).length;
      await manager.sendMessage(parentSessionId, "boundary", task(extracted));
      await settled();
      const retryPid = jsonl(providerCallsFile(first.sessionFile))[beforeRetryCalls].pid;
      expect(retryPid).not.toBe(warningPid);
      const retry = jsonl(first.sessionFile).filter(entry => entry.message?.toolName === "write").at(-1).message;
      expect(retry.isError).not.toBe(true);
      expect(readFileSync(join(cwd, "rules.md"), "utf8")).toBe(extracted);
      expect(readFileSync(join(cwd, "unrelated.txt"), "utf8")).toBe("unrelated formatting\n");
      for (const file of [first.sessionFile, first.infoFile, first.logFile]) {
        expect(readFileSync(file, "utf8")).not.toContain(checkpointCommit);
      }
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
