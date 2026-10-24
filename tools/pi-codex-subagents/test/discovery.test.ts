import { expect, test } from "bun:test";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { AgentManager, CHILD_BUILTIN_EXTENSION_NAMES, SUBAGENT_DIR, parseAgentDefinitionText, resolveChildExtensionPaths } from "../core.ts";
import { jsonl, until } from "./source-runtime.ts";
import { providerCallsFile } from "./held-tool-extension.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const builtinPaths = CHILD_BUILTIN_EXTENSION_NAMES.map(name => `builtin:${name}`);
sourceTest("disabledExtensions parses only template state; old templates omit it", () => {
  expect(parseAgentDefinitionText("---\ndisabledExtensions: pi-codex-subagents, ./denied.ts\n---\nTask", "fallback").disabledExtensions)
    .toEqual(["pi-codex-subagents", "./denied.ts"]);
  expect(parseAgentDefinitionText("Task", "fallback").disabledExtensions).toBeUndefined();
});

for (const trusted of [true, false]) {
  sourceTest(`Native child discovery preserves trust=${trusted}, template exclusions and fresh activation on recreation`, async () => {
    const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "discovery-"));
    const agentDir = getAgentDir();
    const settingsFile = join(agentDir, "settings.json");
    const templateName = `discovery-${randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${templateName}.md`);
    const packageRoot = join(cwd, "monorepo");
    const managerPackage = join(packageRoot, "packages", "pi-codex-subagents");
    mkdirSync(managerPackage, { recursive: true });
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    const deny = join(managerPackage, "index.ts");
    copyFileSync(join(import.meta.dir, "denied-extension.ts"), deny);
    expect(readFileSync(deny, "utf8")).toBe(readFileSync(join(import.meta.dir, "denied-extension.ts"), "utf8"));
    writeFileSync(join(managerPackage, "package.json"), JSON.stringify({ name: "@test/pi-codex-subagents", pi: { extensions: ["./index.ts"] } }));
    const discovered = join(packageRoot, "sibling.ts");
    copyFileSync(join(import.meta.dir, "discovery-extension.ts"), discovered);
    expect(readFileSync(discovered, "utf8")).toBe(readFileSync(join(import.meta.dir, "discovery-extension.ts"), "utf8"));
    writeFileSync(join(packageRoot, "package.json"), JSON.stringify({ name: "test-monorepo", pi: { extensions: ["./packages/pi-codex-subagents/index.ts", "./sibling.ts"] } }));
    const project = join(cwd, ".pi");
    mkdirSync(join(project, "extensions"), { recursive: true });
    copyFileSync(join(import.meta.dir, "denied-extension.ts"), join(project, "extensions", "project.ts"));
    for (const base of [agentDir, project]) {
      mkdirSync(join(base, "skills", "native-skill"), { recursive: true });
      mkdirSync(join(base, "prompts"), { recursive: true });
      const prefix = base === agentDir ? "global" : "project";
      writeFileSync(join(base, "skills", "native-skill", "SKILL.md"), `---\nname: ${prefix}-skill\ndescription: Native discovery test\n---\n${prefix} skill contents`);
      writeFileSync(join(base, "prompts", `${prefix}-prompt.md`), `${prefix} template expansion`);
      writeFileSync(join(base, "SYSTEM.md"), "UNWANTED_SYSTEM");
      writeFileSync(join(base, "APPEND_SYSTEM.md"), "UNWANTED_APPEND");
    }
    writeFileSync(join(cwd, "AGENTS.md"), "UNWANTED_CONTEXT");
    writeFileSync(settingsFile, JSON.stringify({ packages: [packageRoot] }));
    writeFileSync(templateFile, `---\nname: ${templateName}\ndisabledExtensions: pi-codex-subagents\nextensions: ${deny}\n---\n`);
    const parentSessionId = randomUUID();
    const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    try {
      // Canonical aliases exclude precisely one entrypoint, including explicit additions.
      const alias = join(cwd, "alias.ts");
      symlinkSync(discovered, alias);
      expect(await resolveChildExtensionPaths({ cwd, projectTrusted: false })).toEqual([deny, discovered, ...builtinPaths]);
      const selection = await resolveChildExtensionPaths({ cwd, projectTrusted: false, extensionPaths: [discovered], disabledExtensions: [alias, "pi-codex-subagents"] });
      expect(selection).toEqual(builtinPaths);
      // The real package basename denies its manager but not the independently loaded helper.
      const actual = resolve(import.meta.dir, "..");
      expect(await resolveChildExtensionPaths({ cwd, projectTrusted: false, extensionPaths: [actual, join(actual, "child-helper.ts")], disabledExtensions: ["pi-codex-subagents", alias] })).toEqual(builtinPaths);
      await manager.spawnAgent({ task_name: "worker", message: 'invoke-tool:{"name":"discovered_probe","args":{}}', agent_type: templateName,
        cwd, projectTrusted: trusted, parentSessionId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedTools: "read", inheritedThinking: "off" });
      await until(() => manager.getAgentInfo("worker", parentSessionId).status === "completed", "discovered tool completion");
      const info = manager.getAgentInfo("worker", parentSessionId);
      expect(info.tools).toBeUndefined();
      expect(info.projectTrusted).toBe(trusted);
      expect(info.disabledExtensions).toEqual(["pi-codex-subagents"]);
      expect(existsSync(join(cwd, "discovered-called"))).toBe(true);
      // Project resource code executes iff the captured parent decision permits it.
      expect(existsSync(join(cwd, "denied-executed"))).toBe(trusted);
      if (trusted) expect(readFileSync(join(cwd, "denied-executed"), "utf8")).toBe("import\nfactory\nhook\n");
      const starts = jsonl(join(cwd, "discovery-starts.jsonl"));
      expect(starts[0].trusted).toBe(trusted);
      const commands = starts[0].commands.map((command: any) => command.name);
      expect(commands).toContain("global-prompt");
      expect(commands).toContain("skill:global-skill");
      expect(commands.includes("project-prompt")).toBe(trusted);
      expect(commands.includes("skill:project-skill")).toBe(trusted);
      const calls = jsonl(providerCallsFile(info.sessionFile));
      expect(calls[0].tools).toContain("discovered_probe");
      expect(calls[0].tools).toContain("link_reply");
      expect(calls[0].tools).not.toContain("spawn_agent");
      expect(calls[0].systemPrompt).toContain("You are a subagent");
      expect(calls[0].systemPrompt).not.toContain("UNWANTED_");
      // Existing workers keep their launch policy even if the template changes.
      writeFileSync(templateFile, `---\nname: ${templateName}\n---\n`);
      await manager.sendMessage(parentSessionId, "worker", "/global-prompt");
      await until(() => jsonl(providerCallsFile(info.sessionFile)).some(call => call.text === "global template expansion"), "normal prompt template expansion");
      await until(() => manager.getAgentInfo("worker", parentSessionId).status === "completed", "recreated worker completion");
      const recreated = jsonl(join(cwd, "discovery-starts.jsonl"));
      expect(recreated).toHaveLength(2);
      expect(recreated[1].pid).not.toBe(recreated[0].pid);
      expect(recreated[1].trusted).toBe(trusted);
      await manager.sendMessage(parentSessionId, "worker", "/skill:global-skill");
      await until(() => jsonl(providerCallsFile(info.sessionFile)).some(call => call.text.includes("global skill contents")), "normal skill expansion");
      await until(() => manager.getAgentInfo("worker", parentSessionId).status === "completed", "skill task completes");
      if (trusted) expect(readFileSync(join(cwd, "denied-executed"), "utf8").split("factory")).toHaveLength(4);
      else expect(existsSync(join(cwd, "denied-executed"))).toBe(false);
      writeFileSync(templateFile, `---\nname: ${templateName}\ntools: read\ndisabledExtensions: pi-codex-subagents\n---\n`);
      await manager.spawnAgent({ task_name: "limited", message: "Explicit tool selection", agent_type: templateName,
        cwd, projectTrusted: trusted, parentSessionId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => manager.getAgentInfo("limited", parentSessionId).status === "completed", "explicit tool task completes");
      const limited = manager.getAgentInfo("limited", parentSessionId);
      expect(jsonl(providerCallsFile(limited.sessionFile))[0].tools.sort()).toEqual(["link_reply", "read"]);
    } finally {
      await manager.shutdown();
      rmSync(templateFile, { force: true });
      rmSync(settingsFile, { force: true });
      for (const name of ["skills", "prompts", "SYSTEM.md", "APPEND_SYSTEM.md"]) rmSync(join(agentDir, name), { recursive: true, force: true });
      rmSync(cwd, { recursive: true, force: true });
    }
  }, 30000);
}

sourceTest("the package-owned built-in names match the approved current CLI contract", () => {
  expect([...CHILD_BUILTIN_EXTENSION_NAMES]).toEqual(["llama.cpp", "codemode", "tool-search", "mcp"]);
});

const builtinCases = [
  { label: "default discovery", settings: [], disabled: [], excluded: [], trusted: false },
  { label: "template exclusion", settings: [], disabled: ["builtin:codemode"], excluded: ["codemode"], trusted: false },
  { label: "native settings exclusion", settings: ["-builtin:tool-search"], disabled: [], excluded: ["tool-search"], trusted: false },
  { label: "trusted project override and template exclusion", settings: ["-builtin:mcp"], project: ["+builtin:mcp"], disabled: ["builtin:codemode"], excluded: ["codemode"], trusted: true },
  { label: "untrusted project cannot override native exclusion", settings: ["-builtin:mcp"], project: ["+builtin:mcp"], disabled: ["builtin:codemode"], excluded: ["mcp", "codemode"], trusted: false },
  { label: "explicit tools restrict built-in tools", settings: [], disabled: [], excluded: [], trusted: false, tools: "read" },
];
for (const scenario of builtinCases) {
  sourceTest(`Built-in transport: ${scenario.label}`, async () => {
    const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "builtins-"));
    const agentDir = getAgentDir();
    mkdirSync(agentDir, { recursive: true });
    mkdirSync(join(cwd, ".pi"));
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    const settingsFile = join(agentDir, "settings.json");
    writeFileSync(settingsFile, JSON.stringify({ extensions: scenario.settings }));
    writeFileSync(join(cwd, ".pi", "settings.json"), JSON.stringify({ extensions: scenario.project ?? [] }));
    const templateName = `builtin-${randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${templateName}.md`);
    writeFileSync(templateFile, `---\nname: ${templateName}\ndisabledExtensions: ${scenario.disabled.join(",")}\n${scenario.tools === undefined ? "" : `tools: ${scenario.tools}\n`}---\n`);
    const parentSessionId = randomUUID();
    const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    const expected = CHILD_BUILTIN_EXTENSION_NAMES.filter(name => !scenario.excluded.includes(name));
    try {
      expect(await resolveChildExtensionPaths({ cwd, projectTrusted: scenario.trusted, disabledExtensions: scenario.disabled }))
        .toEqual(expected.map(name => `builtin:${name}`));
      await manager.spawnAgent({ task_name: "worker", message: "Built-in selection test", agent_type: templateName,
        cwd, projectTrusted: scenario.trusted, parentSessionId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => manager.getAgentInfo("worker", parentSessionId).status === "completed", "built-in worker completes");
      const info = manager.getAgentInfo("worker", parentSessionId);
      const records = jsonl(`${info.sessionFile}.builtin-factories.jsonl`);
      // Exact factory and hook populations detect both an executed exclusion and a lost default.
      for (const phase of ["factory", "hook"]) expect(records.filter(record => record.phase === phase).map(record => record.name).sort()).toEqual([...expected].sort());
      const tools = jsonl(providerCallsFile(info.sessionFile))[0].tools;
      expect(tools).toContain("link_reply");
      if (scenario.tools !== undefined) expect(tools.sort()).toEqual(["link_reply", "read"]);
      else for (const name of CHILD_BUILTIN_EXTENSION_NAMES) {
        expect(tools.includes(`faux_builtin_${name.replaceAll(/[.-]/g, "_")}`)).toBe(expected.includes(name));
      }
    } finally {
      await manager.shutdown();
      rmSync(templateFile, { force: true });
      rmSync(settingsFile, { force: true });
      rmSync(cwd, { recursive: true, force: true });
    }
  }, 20000);
}
