import { test, expect } from "bun:test";
import { copyFileSync, cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { AgentManager, getAgentDefinition } from "../core.ts";
import { jsonl, sourceRpc, until } from "./source-runtime.ts";
import { providerCallsFile } from "./held-tool-extension.ts";

// Reuses the installed-layout QA fixture, with the corrected on-demand routes.
// The faux provider establishes delivery and native reads, not model compliance,
// staffing judgment, or whether these instructions improve collaboration.
const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const root = resolve(import.meta.dir, "../../..");
const read = (path: string) => readFileSync(path, "utf8");
const roles = ["executive", "strategist", "builder", "qa", "designer", "parent", "luna", "archivist"];
const copy = (source: string, destination: string) => {
  copyFileSync(source, destination);
  expect(read(destination)).toBe(read(source));
};

sourceTest("roots keep direct-task context; every child has a shared read route without executive leakage", async () => {
  const agentDir = getAgentDir();
  const templates = join(agentDir, "pi-codex-subagents/agents");
  const sharedDir = join(process.env.HOME!, ".agents");
  mkdirSync(templates, { recursive: true });
  mkdirSync(sharedDir, { recursive: true });
  copy(join(root, "config/pi-agent/AGENTS.md"), join(agentDir, "AGENTS.md"));
  copy(join(root, "config/pi-agent/ROOT.md"), join(agentDir, "ROOT.md"));
  copy(join(root, "config/agents/shared-agents.md"), join(sharedDir, "shared.md"));
  cpSync(join(root, "skills"), join(sharedDir, "skills"), { recursive: true });
  for (const role of roles) {
    copy(join(root, `config/pi-agent/pi-codex-subagents/agents/${role}.md`), join(templates, `${role}.md`));
  }
  const includes = join(root, "config/pi-agent/pi-extensions/pi-instruction-includes.ts");
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({
    packages: [join(root, "tools/pi-codex-subagents")], extensions: [includes],
  }));
  const roleFile = join(agentDir, "pi-codex-subagents/SYSTEM.md");
  const userRole = "USER_OWNED_ROLE_CONTEXT\n@role-extra.md\n";
  writeFileSync(roleFile, userRole);
  writeFileSync(join(agentDir, "pi-codex-subagents/role-extra.md"), "USER_NESTED_ROLE_INCLUDE\n");
  const cwd = join(process.env.PI_TEST_OWNED_ROOT!, "consumer");
  mkdirSync(cwd);
  writeFileSync(join(cwd, "AGENTS.md"), "USER_PROJECT_CONTEXT\n");
  const commonPath = join(sharedDir, "skills/delegation/SKILL.md");
  const executivePath = join(sharedDir, "skills/delegation/references/executive.md");
  const common = read(commonPath).trim();
  const executiveSource = read(join(templates, "executive.md")).trim();
  const executiveBody = getAgentDefinition("executive")!.prompt!;
  const agentsRoute = read(join(agentDir, "AGENTS.md")).trim();
  const rootRoute = read(join(agentDir, "ROOT.md")).trim();
  const shared = read(join(sharedDir, "shared.md")).trim();
  // The routes name files that really exist in this private installed layout.
  expect(agentsRoute).toContain("~/.agents/skills/delegation/SKILL.md");
  expect(rootRoute).toContain("~/.agents/skills/delegation/SKILL.md");
  expect(common).toContain("(references/executive.md)");
  expect(read(executivePath)).toContain("# Executive procedure");
  const roleRoute = common.match(/\[executive role body\]\(([^)]+)\)/)?.[1];
  expect(roleRoute?.startsWith("~/")).toBe(true);
  const executiveRolePath = resolve(process.env.HOME!, roleRoute!.slice(2));
  expect(executiveRolePath).toBe(join(templates, "executive.md"));
  expect(read(executiveRolePath).trim()).toBe(executiveSource);
  const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
  const parentSessionId = "coordination-delivery";
  const rootFile = join(cwd, "root.jsonl");
  const peer = sourceRpc(cwd, rootFile, false, [], {
    PI_TEST_CAPTURE_CONTEXT: "1", PI_SUBAGENT_ID: "",
  });
  const checkSharedRoute = (prompt: string) => {
    expect(prompt).toContain(agentsRoute);
    expect(prompt).toContain(shared);
    expect(prompt).toContain("USER_PROJECT_CONTEXT");
    expect(prompt).toContain("<name>delegation</name>");
    expect(prompt).toContain(commonPath);
    expect(prompt).not.toContain(common);
    expect(prompt).not.toContain(executiveBody);
    expect(prompt).not.toContain(read(executivePath).trim());
  };
  try {
    await peer.request({ type: "prompt", message: "Inspect the assigned outcome." });
    await until(() => peer.records.filter(record => record.type === "agent_settled").length === 1,
      "configured root captures direct-task context");
    const firstRoot = jsonl(providerCallsFile(rootFile))[0];
    checkSharedRoute(firstRoot.systemPrompt);
    expect(firstRoot.systemPrompt).toContain(rootRoute);
    expect(firstRoot.systemPrompt).not.toContain(executiveSource);
    expect(firstRoot.systemPrompt).not.toContain("USER_OWNED_ROLE_CONTEXT");

    // Authority-only changes must not turn a read route into an automatic include.
    const commonMarker = "COMMON_AUTHORITY_VARIATION";
    const procedureMarker = "EXECUTIVE_PROCEDURE_VARIATION";
    const roleMarker = "EXECUTIVE_ROLE_VARIATION";
    writeFileSync(commonPath, `${common}\n\n${commonMarker}\n`);
    writeFileSync(executivePath, `${read(executivePath)}\n${procedureMarker}\n`);
    writeFileSync(executiveRolePath, `${executiveSource}\n\n${roleMarker}\n`);
    await peer.request({ type: "prompt", message: "Inspect the assigned outcome." });
    await until(() => peer.records.filter(record => record.type === "agent_settled").length === 2,
      "root keeps guidance on demand after authorities change");
    const nextRoot = jsonl(providerCallsFile(rootFile))[1];
    checkSharedRoute(nextRoot.systemPrompt);
    expect(nextRoot.systemPrompt).not.toContain(commonMarker);
    expect(nextRoot.systemPrompt).not.toContain(procedureMarker);
    expect(nextRoot.systemPrompt).not.toContain(roleMarker);

    // Explicit native reads exercise the positive route, without pretending the
    // deterministic provider independently chose to load these documents.
    // Common + procedure covers a bounded-helper caller. Taking dedicated
    // executive responsibility additionally follows the skill-owned role route.
    for (const [index, path, marker] of [
      [0, commonPath, commonMarker], [1, executivePath, procedureMarker],
      [2, executiveRolePath, roleMarker],
    ] as const) {
      await peer.request({ type: "prompt", message: `invoke-tool:${JSON.stringify({ name: "read", args: { path } })}` });
      await until(() => peer.records.filter(record => record.type === "agent_settled").length === index + 3,
        `native read reaches ${path}`);
      const last = jsonl(providerCallsFile(rootFile)).at(-1);
      const results = last.messages.filter((message: any) => message.role === "toolResult" && message.toolName === "read");
      const text = results.flatMap((message: any) => message.content)
        .filter((part: any) => part.type === "text").map((part: any) => part.text).join("\n");
      expect(text).toContain(read(path).trim());
      expect(text).toContain(marker);
      if (index < 2) expect(text).not.toContain(roleMarker);
      else expect(text).toContain(executiveBody);
      expect(last.systemPrompt).not.toContain(marker);
    }

    for (const selection of [...roles, undefined]) {
      const task = selection ?? "omitted";
      await manager.spawnAgent({ task_name: task, agent_type: selection, message: "Inspect the assigned outcome.", cwd,
        projectTrusted: false, parentSessionId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "medium" });
      await until(() => manager.getAgentInfo(task, parentSessionId).status === "completed", `${task} child completes`);
      const info = manager.getAgentInfo(task, parentSessionId);
      const calls = jsonl(providerCallsFile(info.sessionFile));
      expect(calls).toHaveLength(1);
      const call = calls[0];
      checkSharedRoute(call.systemPrompt);
      expect(call.systemPrompt).toContain("USER_OWNED_ROLE_CONTEXT");
      expect(call.systemPrompt).toContain("USER_NESTED_ROLE_INCLUDE");
      expect(call.systemPrompt).not.toContain(rootRoute);
      expect(call.systemPrompt).not.toContain(commonMarker);
      expect(call.systemPrompt).not.toContain(procedureMarker);
      expect(call.systemPrompt).not.toContain(roleMarker);
      const definition = selection ? getAgentDefinition(selection)! : undefined;
      expect(call.text).toBe([definition?.prompt, "Inspect the assigned outcome."].filter(Boolean).join("\n\n"));
      expect(call.text.includes(roleMarker)).toBe(selection === "executive");
      expect(call.text).not.toContain(procedureMarker);
      expect(call.tools).toContain("spawn_agent");
      expect(read(roleFile)).toBe(userRole);
      expect(read(join(cwd, "AGENTS.md"))).toBe("USER_PROJECT_CONTEXT\n");
      expect(info.thinking).toBe(definition?.thinking ?? "medium");
      expect(info.model).toBe(definition?.provider && definition.model ? `${definition.provider}:${definition.model}` : "faux:faux-1");
    }
  } finally {
    await peer.close();
    await manager.shutdown();
  }
}, 60000);
