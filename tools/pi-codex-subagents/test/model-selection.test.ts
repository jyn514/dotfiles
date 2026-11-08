import { expect, test } from "bun:test";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { getCurrentTools } from "@earendil-works/pi-ai";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseFactory } from "@earendil-works/pi-ai/providers/faux";
import {
  createAgentSessionFromServices, createAgentSessionServices, getAgentDir,
  ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { getAgent, getAgentDefinition, parentScopeKey } from "../core.ts";
import { jsonl, productionIndex, until } from "./source-runtime.ts";
import { providerCallsFile } from "./held-tool-extension.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("configured guidance, independent role/model choices and strategist parent invariant reach native children", async () => {
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "models-"));
  const source = resolve(import.meta.dir, "../../../config/pi-agent/pi-codex-subagents");
  const configDir = join(getAgentDir(), "pi-codex-subagents");
  const templates = join(configDir, "agents");
  mkdirSync(templates, { recursive: true });
  const copy = (from: string, to: string) => {
    copyFileSync(from, to);
    expect(readFileSync(to)).toEqual(readFileSync(from));
  };
  copy(join(source, "config.json"), join(configDir, "config.json"));
  for (const file of readdirSync(join(source, "agents"))) copy(join(source, "agents", file), join(templates, file));
  const config = JSON.parse(readFileSync(join(configDir, "config.json"), "utf8"));
  // The authority supplies model IDs and advice; changing it must not require changing the fixture.
  const pairs = config.models.map((pair: string) => {
    const slash = pair.indexOf("/");
    return { provider: pair.slice(0, slash), id: pair.slice(slash + 1) };
  });
  expect(pairs.length).toBeGreaterThanOrEqual(2);
  const provider = pairs[0].provider;
  expect(pairs.every((pair: any) => pair.provider === provider)).toBe(true);
  const catalog = { provider, models: [...pairs.map((pair: any) => ({ id: pair.id, reasoning: true })),
    { id: "independent-parent-a", reasoning: true }, { id: "independent-parent-b", reasoning: true }] };
  const previousCatalog = process.env.PI_TEST_MODEL_CATALOG;
  process.env.PI_TEST_MODEL_CATALOG = JSON.stringify(catalog);
  for (const skill of [...Object.keys(config.directSkillRoutes), "strategic-fixture"]) {
    const directory = join(getAgentDir(), "skills", skill);
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, "SKILL.md"), `---\nname: ${skill}\ndescription: Disposable route fixture\n---\nNATIVE_SKILL_${skill}\n`);
  }
  const faux = fauxProvider(catalog);
  const runtime = await ModelRuntime.create({ authPath: join(cwd, "auth.json"), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  runtime.registerNativeProvider(faux.provider);
  const settings = SettingsManager.create(cwd, getAgentDir());
  settings.setExtensionPaths([productionIndex]);
  await settings.flush();
  settings.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const services = await createAgentSessionServices({
    cwd, agentDir: getAgentDir(), modelRuntime: runtime, settingsManager: settings,
    resourceLoaderOptions: { noThemes: true, noContextFiles: true, additionalExtensionPaths: [productionIndex] },
  });
  const { session, extensionsResult } = await createAgentSessionFromServices({
    services, sessionManager: SessionManager.create(cwd), model: faux.getModel("independent-parent-a")!,
    thinkingLevel: "low", noTools: "builtin",
  });
  expect(extensionsResult.errors).toEqual([]);
  const errors: unknown[] = [];
  await session.bindExtensions({ mode: "rpc", onError: error => errors.push(error) });
  const parentId = session.sessionManager.getSessionId();
  const declarations: any[] = [];
  const respond: FauxResponseFactory = (context) => {
    faux.appendResponses([respond]);
    declarations.push(getCurrentTools(context.messages).find(tool => tool.name === "spawn_agent"));
    const lastUser = context.messages.findLast(message => message.role === "user");
    const text = typeof lastUser?.content === "string" ? lastUser.content
      : Array.isArray(lastUser?.content) ? lastUser.content.filter(part => part.type === "text").map(part => part.text).join("\n") : "";
    if (text.startsWith("control:")) {
      const request = JSON.parse(text.slice(8));
      const index = context.messages.findLastIndex(message => message === lastUser);
      if (!context.messages.slice(index + 1).some(message => message.role === "toolResult" && message.toolName === request.name)) {
        return fauxAssistantMessage(fauxToolCall(request.name, request.args), { stopReason: "toolUse" });
      }
    }
    if (text.startsWith("spawn:")) {
      const args = JSON.parse(text.slice(6));
      const exists = context.messages.some(message => message.role === "assistant" && message.content.some(
        part => part.type === "toolCall" && part.name === "spawn_agent" && part.arguments.task_name === args.task_name));
      if (!exists) return fauxAssistantMessage(fauxToolCall("spawn_agent", args), { stopReason: "toolUse" });
    }
    return fauxAssistantMessage("parent available");
  };
  faux.setResponses([respond]);
  const finished = async (name: string) => {
    await until(() => ["completed", "failed", "interrupted"].includes(getAgent(name, parentId)?.status ?? ""),
      `child ${name} settles`, 20000);
    expect(getAgent(name, parentId)?.status, JSON.stringify(getAgent(name, parentId))).toBe("completed");
    await until(() => !session.isStreaming, "parent completion delivery settles");
    const info = getAgent(name, parentId)!;
    const calls = jsonl(providerCallsFile(info.sessionFile));
    expect(calls).toHaveLength(1);
    return { info, call: calls[0] };
  };
  const spawn = async (args: any) => {
    await session.prompt("spawn:" + JSON.stringify({ message: "minimal native task", ...args }));
    return finished(args.task_name);
  };
  try {
    await session.prompt("inspect native tool declarations");
    const tool = declarations.at(-1);
    expect(tool.description).toContain(config.modelGuidance);
    expect(tool.parameters.properties.model.enum).toEqual(config.models);
    expect(tool.parameters.properties.thinking.enum).toContain("high");

    // Role instructions and permissions stay stable while the caller chooses a model.
    for (const role of ["builder", "qa", "designer", "executive", "parent", "luna", "archivist", "strategist"]) {
      const chosen = pairs[1];
      const { info, call } = await spawn({ task_name: role, agent_type: role,
        model: `${chosen.provider}/${chosen.id}`, thinking: "high" });
      const modelId = role === "strategist" ? "independent-parent-a" : chosen.id;
      expect(info).toMatchObject({ provider: chosen.provider, modelId, thinking: "high" });
      expect(call).toMatchObject({ provider: chosen.provider, modelId, thinking: "high" });
      expect(call.text).toBe(getAgentDefinition(role)!.prompt + "\n\nminimal native task");
      // Permission is a governing expectation, not an oracle derived from the template exclusion.
      for (const tool of ["spawn_agent", "wait_agent", "list_agents", "read_agent_response", "steer_subagent", "interrupt_agent"]) {
        expect(call.tools).toContain(tool);
      }
      expect(tool.description).toContain(getAgentDefinition(role)!.hint);
    }
    // Real builder -> Luna -> builder round trip, including provider consumption of the helper result.
    await session.prompt("spawn:" + JSON.stringify({
      task_name: "builder-with-helper", agent_type: "builder", message: "role-helper-task",
    }));
    await until(() => getAgent("builder-with-helper", parentId)?.status === "completed", "builder integrates Luna result", 20000);
    await until(() => !session.isStreaming, "nested completion reaches original parent");
    const builder = getAgent("builder-with-helper", parentId)!;
    const builderSession = SessionManager.open(builder.sessionFile);
    const helper = getAgent("bounded-luna-helper", builderSession.getSessionId())!;
    expect(helper).toMatchObject({ agentType: "luna", status: "completed",
      provider: getAgentDefinition("luna")!.provider, modelId: getAgentDefinition("luna")!.model });
    const helperCalls = jsonl(providerCallsFile(helper.sessionFile));
    expect(helperCalls).toHaveLength(1);
    expect(helperCalls[0].text).toBe(getAgentDefinition("luna")!.prompt + "\n\nbounded-luna-result");
    const results = builderSession.getBranch().filter((entry: any) => entry.type === "message"
      && entry.message.role === "toolResult") as any[];
    expect(results.filter(entry => entry.message.toolName === "spawn_agent")).toHaveLength(1);
    expect(results.filter(entry => entry.message.toolName === "wait_agent")).toHaveLength(1);
    expect(results.every(entry => !entry.message.isError)).toBe(true);
    expect(builder.finalResponse).toStartWith("builder-integrated:");
    expect(builder.finalResponse).toContain("bounded-luna-result");

    // Non-strategist template model defaults still lose to caller overrides; omitted values inherit.
    const preset = getAgentDefinition("luna")!;
    const overridden = await spawn({ task_name: "preset-override", agent_type: "luna",
      model: config.models[1], thinking: "high" });
    expect(overridden.call.modelId).toBe(pairs[1].id);
    const inherited = await spawn({ task_name: "inherited", agent_type: "builder" });
    expect(inherited.call).toMatchObject({ modelId: "independent-parent-a", thinking: "low" });

    const nominal = await spawn({ task_name: "strategist-nominal", agent_type: "strategist", thinking: "high" });
    expect(nominal.call).toMatchObject({ provider, modelId: "independent-parent-a", thinking: "high" });

    // A conflicting template default must not defeat the strategist role invariant.
    const strategistFile = join(templates, "strategist.md");
    const strategist = readFileSync(strategistFile, "utf8");
    writeFileSync(strategistFile, strategist.replace("name: strategist",
      `name: strategist\nprovider: ${provider}\nmodel: ${pairs[1].id}\nthinking: medium`));
    const normal = await spawn({ task_name: "strategist-template", agent_type: "strategist" });
    expect(normal.call).toMatchObject({ provider, modelId: "independent-parent-a", thinking: "medium" });
    const conflicting = await spawn({ task_name: "strategist-override", agent_type: "strategist",
      model: config.models[0], thinking: "high" });
    expect(conflicting.call).toMatchObject({ provider, modelId: "independent-parent-a", thinking: "high" });
    expect(conflicting.call.text).toBe(getAgentDefinition("strategist")!.prompt + "\n\nminimal native task");

    await session.setModel(faux.getModel("independent-parent-b")!);
    const switched = await spawn({ task_name: "strategist-new-parent", agent_type: "strategist", model: config.models[1] });
    expect(switched.call).toMatchObject({ modelId: "independent-parent-b", thinking: "medium" });
    // Native history selection must not restore the source model over the current parent model.
    const origin = SessionManager.open(inherited.info.sessionFile);
    const forked = await spawn({ task_name: "strategist-fork", agent_type: "strategist", model: config.models[0],
      fork_from: { session_id: origin.getSessionId(), through_entry_id: origin.getLeafId() } });
    expect(forked.call).toMatchObject({ modelId: "independent-parent-b" });

    // Keep both real convenience routes, including proposal-only delivery.
    const directOwners = new Map<string, any>();
    for (const [skill, route] of Object.entries(config.directSkillRoutes) as [string, any][]) {
      await session.prompt(`/skill:${skill} route check`);
      const prefix = `direct/${skill}/`;
      const scope = join(configDir, "runs", parentScopeKey(parentId));
      const find = () => readdirSync(scope).filter(file => file.endsWith(".info.json"))
        .map(file => JSON.parse(readFileSync(join(scope, file), "utf8"))).find(info => info.taskName.startsWith(prefix));
      await until(() => Boolean(find()), "direct route child created");
      const routed = await finished(find().taskName);
      directOwners.set(skill, routed.info);
      // Root routing remains asynchronous/handled; only its selected child has a native run.
      const lastInput = session.messages.findLast(message => message.role === "user");
      expect(lastInput && JSON.stringify(lastInput)).not.toContain(`/skill:${skill} route check`);
      expect(routed.call).toMatchObject({ provider: preset.provider, modelId: preset.model, thinking: preset.thinking });
      expect(routed.call.text).toContain(`NATIVE_SKILL_${skill}`);
      if (route.proposalOnly) expect(routed.call.text).toContain("Operate in suggest mode only");
    }

    const routedChildren = (owner: any, skill: string) => {
      const id = SessionManager.open(owner.sessionFile).getSessionId();
      const scope = join(configDir, "runs", parentScopeKey(id));
      try {
        return readdirSync(scope).filter(file => file.endsWith(".info.json"))
          .map(file => JSON.parse(readFileSync(join(scope, file), "utf8")))
          .filter(info => info.taskName.startsWith(`direct/${skill}/`));
      } catch (error: any) {
        if (error.code === "ENOENT") return [];
        throw error;
      }
    };
    const continueSkill = async (owner: any, skill: string, locally: boolean) => {
      const before = jsonl(providerCallsFile(owner.sessionFile)).length;
      await session.prompt("control:" + JSON.stringify({ name: "steer_subagent",
        args: { target: owner.taskName, message: `/skill:${skill} continued native route check` } }));
      if (locally) {
        await until(() => jsonl(providerCallsFile(owner.sessionFile)).length > before,
          "continued skill reaches its existing native owner");
        expect(routedChildren(owner, skill)).toHaveLength(0);
        expect(jsonl(providerCallsFile(owner.sessionFile)).at(-1).text).toContain(`NATIVE_SKILL_${skill}`);
      } else {
        await until(() => routedChildren(owner, skill).some(child => child.status === "completed"),
          "worker's other skill reaches its routed child", 20000).catch(error => {
          console.error(JSON.stringify({ task: owner.taskName, skill, owner: getAgent(owner.taskName, parentId),
            children: routedChildren(owner, skill), providerCallCount: jsonl(providerCallsFile(owner.sessionFile)).length,
            controlResults: session.messages.filter(message => message.role === "toolResult" && message.toolName === "steer_subagent") }));
          throw error;
        });
        const child = routedChildren(owner, skill)[0];
        const calls = jsonl(providerCallsFile(child.sessionFile));
        expect(calls).toHaveLength(1);
        expect(calls[0].text).toContain(`NATIVE_SKILL_${skill}`);
        if (config.directSkillRoutes[skill].proposalOnly) expect(calls[0].text).toContain("Operate in suggest mode only");
      }
      await until(() => getAgent(owner.taskName, parentId)?.status === "completed"
        && jsonl(providerCallsFile(owner.sessionFile)).length > before, "continued owner settles", 20000);
      await until(() => !session.isStreaming, "continued completion delivery settles");
      if (!locally) {
        const fresh = getAgent(owner.taskName, parentId)!;
        expect(fresh.finalResponse).toStartWith("worker-integrated:");
        expect(fresh.finalResponse).toContain("continued native route check");
        expect(fresh.finalResponse).toContain("NATIVE_SKILL_" + skill);
        const ownerCalls = jsonl(providerCallsFile(owner.sessionFile)).slice(before);
        expect(ownerCalls[0].text).toContain(`/skill:${skill} continued native route check`);
        if (config.directSkillRoutes[skill].proposalOnly) expect(ownerCalls[0].text).toContain("Operate in suggest mode only");
        const branch = SessionManager.open(owner.sessionFile).getBranch() as any[];
        const lastUser = branch.findLastIndex(entry => entry.type === "message" && entry.message.role === "user");
        const waits = branch.slice(lastUser + 1).filter(entry => entry.type === "message"
          && entry.message.role === "toolResult" && entry.message.toolName === "wait_agent");
        expect(waits).toHaveLength(1);
        expect(waits[0].message.isError).not.toBe(true);
      }
    };
    const skills = Object.keys(config.directSkillRoutes);
    for (const skill of skills) await continueSkill(directOwners.get(skill), skill, true);
    // Matching identity owns only its selected skill, not every configured route.
    await continueSkill(directOwners.get(skills[0]), skills[1], false);
    // Ordinary technical workers retain automatic routes as well as the explicit helper round trip above.
    await continueSkill(getAgent("builder", parentId)!, skills[0], false);
    // A fresh fork keeps native history but does not inherit the source's routing ownership.
    const routedSource = SessionManager.open(directOwners.get(skills[0]).sessionFile);
    const freshFork = await spawn({ task_name: "fresh-builder-fork", agent_type: "builder",
      fork_from: { session_id: routedSource.getSessionId(), through_entry_id: routedSource.getLeafId() } });
    await continueSkill(freshFork.info, skills[0], false);

    // Direct input routes share the same invariant, without a model-issued spawn tool call.
    writeFileSync(join(configDir, "config.json"), JSON.stringify({
      ...config, directSkillRoutes: { ...config.directSkillRoutes, "strategic-fixture": { agentType: "strategist" } },
    }));
    await session.prompt("/skill:strategic-fixture choose next work");
    const scope = join(configDir, "runs", parentScopeKey(parentId));
    const routedName = () => readdirSync(scope).filter(file => file.endsWith(".info.json"))
      .map(file => JSON.parse(readFileSync(join(scope, file), "utf8")))
      .find(info => info.taskName.startsWith("direct/strategic-fixture/"))?.taskName;
    await until(() => Boolean(routedName()), "strategist skill route created");
    const routed = await finished(routedName());
    expect(routed.call).toMatchObject({ modelId: "independent-parent-b", thinking: "medium" });
    expect(routed.call.text).toContain("NATIVE_SKILL_strategic-fixture");
    expect(routed.call.text).toContain(getAgentDefinition("strategist")!.prompt);
    expect(errors).toEqual([]);
  } finally {
    session.dispose();
    if (previousCatalog === undefined) delete process.env.PI_TEST_MODEL_CATALOG;
    else process.env.PI_TEST_MODEL_CATALOG = previousCatalog;
  }
}, 90000);
