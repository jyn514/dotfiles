import { expect, test } from "bun:test";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { AgentManager, CHILD_BUILTIN_EXTENSION_NAMES, SUBAGENT_DIR, parseAgentDefinitionText, resolveChildExtensionPaths } from "../core.ts";
import { jsonl, sourceRpc, until } from "./source-runtime.ts";
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
      writeFileSync(join(base, "SYSTEM.md"), `${prefix.toUpperCase()}_BASE_MARKER`);
      writeFileSync(join(base, "APPEND_SYSTEM.md"), `${prefix.toUpperCase()}_APPEND_MARKER`);
    }
    writeFileSync(join(cwd, "AGENTS.md"), "SHARED_CWD_CONTEXT_MARKER");
    writeFileSync(settingsFile, JSON.stringify({ packages: [packageRoot] }));
    writeFileSync(templateFile, `---\nname: ${templateName}\ndisabledExtensions: pi-codex-subagents\nextensions: ${deny}\n---\n`);
    const roleFile = join(SUBAGENT_DIR, "SYSTEM.md");
    const previousRole = existsSync(roleFile) ? readFileSync(roleFile) : undefined;
    writeFileSync(roleFile, "EDITED_DISCOVERY_CHILD_ROLE_MARKER");
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
      expect(calls[0].systemPrompt).toContain("EDITED_DISCOVERY_CHILD_ROLE_MARKER");
      expect(calls[0].systemPrompt).toContain("SHARED_CWD_CONTEXT_MARKER");
      for (const suffix of ["BASE_MARKER", "APPEND_MARKER"]) {
        expect(calls[0].systemPrompt).toContain(`${trusted ? "PROJECT" : "GLOBAL"}_${suffix}`);
        expect(calls[0].systemPrompt).not.toContain(`${trusted ? "GLOBAL" : "PROJECT"}_${suffix}`);
      }
      expect(calls[0].systemPrompt).not.toContain("You are an expert coding assistant");
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
      if (previousRole === undefined) rmSync(roleFile, { force: true }); else writeFileSync(roleFile, previousRole);
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

// Both modes use native resource loading. The optional integration loads the actual
// dotfiles hook, rather than a copy that could conceal ordering or ROOT regressions.
for (const withIncludes of [false, true]) for (const configured of [false, true]) {
  const compositionTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG || (withIncludes && !process.env.PI_TEST_INSTRUCTION_INCLUDES_SOURCE));
  compositionTest(`Native provider instruction composition: ${configured ? "configured base/append" : "default coding prompt"}, ${withIncludes ? "actual optional instruction-includes source" : "no custom include hook"}`, async () => {
    const ancestor = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "instructions-"));
    const cwd = join(ancestor, "project");
    const agentDir = getAgentDir();
    const roleFile = join(SUBAGENT_DIR, "SYSTEM.md");
    const previousRole = existsSync(roleFile) ? readFileSync(roleFile) : undefined;
    const settingsFile = join(agentDir, "settings.json");
    const templateName = `instructions-${randomUUID()}`;
    const templateFile = join(SUBAGENT_DIR, "agents", `${templateName}.md`);
    const rootFile = join(cwd, "root.jsonl");
    mkdirSync(cwd, { recursive: true });
    mkdirSync(join(SUBAGENT_DIR, "agents"), { recursive: true });
    mkdirSync(join(agentDir, "skills", "composition-skill"), { recursive: true });
    writeFileSync(join(agentDir, "skills", "composition-skill", "SKILL.md"), "---\nname: composition-skill\ndescription: COMPOSITION_SKILL_CATALOG_MARKER\n---\nSkill body");
    writeFileSync(join(agentDir, "AGENTS.md"), `SHARED_GLOBAL_MARKER\n${withIncludes ? "@../../.agents/shared.md\n" : ""}`);
    writeFileSync(join(ancestor, "AGENTS.md"), "SHARED_ANCESTOR_MARKER");
    writeFileSync(join(cwd, "AGENTS.md"), "SHADOWED_CWD_MARKER");
    writeFileSync(join(cwd, "AGENTS.override.md"), "SHARED_CWD_OVERRIDE_MARKER");
    const editedRole = `EDITED_COMPOSITION_CHILD_ROLE_MARKER\n${withIncludes ? "@role-extra.md\n" : ""}`;
    writeFileSync(roleFile, editedRole);
    writeFileSync(templateFile, `---\nname: ${templateName}\ntools: read\n---\nCOMPOSITION_TEMPLATE_MARKER\n`);
    if (configured) {
      writeFileSync(join(agentDir, "SYSTEM.md"), "CONFIGURED_GLOBAL_BASE_MARKER");
      writeFileSync(join(agentDir, "APPEND_SYSTEM.md"), "CONFIGURED_GLOBAL_APPEND_MARKER");
    }
    if (withIncludes) {
      // Preserve the installed route shape, including a symlink and nested relative include.
      const shared = join(ancestor, "shared-rules");
      mkdirSync(join(shared, "nested"), { recursive: true });
      writeFileSync(join(shared, "shared.md"), "SHARED_SYMLINK_INCLUDE_MARKER\n@nested/rules.md\n");
      writeFileSync(join(shared, "nested", "rules.md"), "SHARED_NESTED_INCLUDE_MARKER");
      symlinkSync(shared, join(process.env.HOME!, ".agents"));
      writeFileSync(join(SUBAGENT_DIR, "role-extra.md"), "CHILD_ROLE_INCLUDE_MARKER");
      writeFileSync(settingsFile, JSON.stringify({ extensions: [process.env.PI_TEST_INSTRUCTION_INCLUDES_SOURCE] }));
    }
    const manager = new AgentManager({ modelResponseTimeoutMs: 20000 });
    const root = sourceRpc(cwd, rootFile, false, []);
    const count = (text: string, marker: string) => text.split(marker).length - 1;
    const checkShared = (prompt: string) => {
      for (const marker of ["SHARED_GLOBAL_MARKER", "SHARED_ANCESTOR_MARKER", "SHARED_CWD_OVERRIDE_MARKER", "COMPOSITION_SKILL_CATALOG_MARKER"]) expect(count(prompt, marker), marker).toBe(1);
      expect(prompt).not.toContain("SHADOWED_CWD_MARKER");
      if (configured) {
        expect(count(prompt, "CONFIGURED_GLOBAL_BASE_MARKER")).toBe(1);
        expect(count(prompt, "CONFIGURED_GLOBAL_APPEND_MARKER")).toBe(1);
        expect(prompt).not.toContain("You are an expert coding assistant");
      } else {
        expect(prompt).toContain("You are an expert coding assistant");
        expect(prompt).toContain("Pi documentation");
      }
      if (withIncludes) for (const marker of ["SHARED_SYMLINK_INCLUDE_MARKER", "SHARED_NESTED_INCLUDE_MARKER"]) expect(count(prompt, marker), marker).toBe(1);
    };
    try {
      await root.request({ type: "prompt", message: "root without ROOT file" });
      await until(() => root.records.filter(record => record.type === "agent_settled").length === 1, "root without optional ROOT settles");
      const firstRoot = jsonl(providerCallsFile(rootFile))[0];
      checkShared(firstRoot.systemPrompt);
      expect(firstRoot.systemPrompt).not.toContain("EDITED_COMPOSITION_CHILD_ROLE_MARKER");
      expect(firstRoot.systemPrompt).not.toContain("ROOT_ONLY_COMPOSITION_MARKER");
      if (withIncludes) {
        writeFileSync(join(agentDir, "ROOT.md"), "ROOT_ONLY_COMPOSITION_MARKER");
        await root.request({ type: "prompt", message: "root with ROOT file" });
        await until(() => root.records.filter(record => record.type === "agent_settled").length === 2, "root with optional ROOT settles");
        const currentRoot = jsonl(providerCallsFile(rootFile)).at(-1);
        checkShared(currentRoot.systemPrompt);
        expect(count(currentRoot.systemPrompt, "ROOT_ONLY_COMPOSITION_MARKER")).toBe(1);
        // Native extension failures are reported but do not prevent provider work.
        const nestedRules = join(ancestor, "shared-rules", "nested", "rules.md");
        rmSync(nestedRules);
        await root.request({ type: "prompt", message: "ROOT_INCLUDE_FAILURE_STILL_REACHES_PROVIDER" });
        await until(() => root.records.filter(record => record.type === "agent_settled").length === 3, "root continues after include hook failure");
        expect(root.records.some(record => record.type === "extension_error" && record.event === "before_agent_start" && record.error.includes(nestedRules))).toBe(true);
        expect(jsonl(providerCallsFile(rootFile)).at(-1).text).toBe("ROOT_INCLUDE_FAILURE_STILL_REACHES_PROVIDER");
        writeFileSync(nestedRules, "SHARED_NESTED_INCLUDE_MARKER");
      }
      const parentSessionId = randomUUID();
      await manager.spawnAgent({ task_name: "composition", message: "COMPOSITION_ASSIGNED_TASK_MARKER", agent_type: templateName,
        cwd, projectTrusted: false, parentSessionId, inheritedProvider: "faux", inheritedModelId: "faux-1", inheritedThinking: "off" });
      await until(() => manager.getAgentInfo("composition", parentSessionId).status === "completed", "child instruction composition completes");
      const info = manager.getAgentInfo("composition", parentSessionId);
      const calls = jsonl(providerCallsFile(info.sessionFile));
      expect(calls).toHaveLength(1);
      checkShared(calls[0].systemPrompt);
      expect(count(calls[0].systemPrompt, "EDITED_COMPOSITION_CHILD_ROLE_MARKER")).toBe(1);
      expect(calls[0].systemPrompt).not.toContain("ROOT_ONLY_COMPOSITION_MARKER");
      if (withIncludes) expect(count(calls[0].systemPrompt, "CHILD_ROLE_INCLUDE_MARKER")).toBe(1);
      expect(count(calls[0].text, "COMPOSITION_TEMPLATE_MARKER")).toBe(1);
      expect(count(calls[0].text, "COMPOSITION_ASSIGNED_TASK_MARKER")).toBe(1);
      expect(calls[0].tools.sort()).toEqual(["link_reply", "read"]);
      expect(readFileSync(roleFile, "utf8")).toBe(editedRole);
    } finally {
      await root.close();
      await manager.shutdown();
      if (previousRole === undefined) rmSync(roleFile, { force: true }); else writeFileSync(roleFile, previousRole);
      rmSync(templateFile, { force: true });
      rmSync(join(SUBAGENT_DIR, "role-extra.md"), { force: true });
      for (const name of ["AGENTS.md", "ROOT.md", "SYSTEM.md", "APPEND_SYSTEM.md", "skills", "settings.json"]) rmSync(join(agentDir, name), { recursive: true, force: true });
      if (withIncludes) rmSync(join(process.env.HOME!, ".agents"), { force: true });
      rmSync(ancestor, { recursive: true, force: true });
    }
  }, 30000);
}
