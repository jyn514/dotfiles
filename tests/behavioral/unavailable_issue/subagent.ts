import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { rewritePiResourcePaths } from "../../../config/pi-agent/pi-extensions/guest-tools-core.ts";
import { captureRequest, changedFiles, cwd, fixtureManifest, hash, observations, Sandbox, type Inventory, type Mode } from "./runtime.ts";
import { guestExecutor } from "./subagent-transport.ts";
import { workerTools } from "./worker-tools.ts";

export const launchMarker = "UNAVAILABLE_ISSUE_EVAL ";
const toolNames = ["task_read", "task_edit", "task_write", "task_bash"];
const textContent = (message: any): string => typeof message.content === "string" ? message.content :
  (message.content ?? []).filter((part: any) => part.type === "text").map((part: any) => part.text).join("\n");

export function launchConfiguration(prompt: string) {
  const lines = prompt.split("\n").filter(line => line.startsWith(launchMarker));
  if (lines.length !== 1) throw new Error("Expected one evaluation launch record");
  const value = JSON.parse(lines[0].slice(launchMarker.length));
  if (!value || !["unreadable", "readable"].includes(value.mode) ||
    typeof value.image !== "string" || !value.image ||
    Object.keys(value).sort().join(",") !== "fixture,image,mode,output") throw new Error("Invalid launch record");
  for (const key of ["fixture", "output"]) {
    const path = value[key];
    if (typeof path !== "string" || isAbsolute(path) || !path.startsWith("target/") ||
      path.split("/").some((part: string) => part === ".." || part === "")) throw new Error(`Invalid ${key} path`);
  }
  return value as { mode: Mode; image: string; fixture: string; output: string };
}

/** Remove inherited startup context and controller metadata, not worker actions. */
export function workerContext(messages: any[], systemPrompt: string, packet: string, tools: any[]) {
  const initial = messages.findIndex(message => message.role === "user" && textContent(message).includes(launchMarker));
  if (initial < 0) throw new Error("Evaluation launch message missing from context");
  if (tools.map(tool => tool.name).sort().join(",") !== [...toolNames].sort().join(",")) throw new Error("Worker declarations must contain exactly four tools");
  return [{ role: "system", content: systemPrompt, toolsAdded: tools, timestamp: 0 },
    { ...messages[initial], content: [{ type: "text", text: packet }] },
    ...messages.slice(initial + 1).filter(message => message.role !== "system")];
}

export function workerPayload(payload: any) {
  // The sandbox launcher prepends the ordinary bundle even when discovery excludes it.
  // This task hook loads after that prefix and removes its provider-side search tool.
  if (!Array.isArray(payload?.tools)) throw new Error("Provider function declarations missing");
  const tools = payload.tools.filter((tool: any) => !/^web_search(?:_|$)/.test(tool?.type ?? ""));
  if (tools.some((tool: any) => !tool || (tool.type !== undefined && tool.type !== "function")) ||
    tools.map((tool: any) => tool.function?.name ?? tool.name).sort().join(",") !== [...toolNames].sort().join(",")) {
    throw new Error("Provider payload must declare exactly four worker functions");
  }
  return { ...payload, tools };
}

/** One dedicated fresh subagent; model access stays in Pi and tools stay in Docker. */
export default async function install(pi: ExtensionAPI) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  let context: ExtensionContext;
  let sandbox: Sandbox | undefined;
  let output = "", scratch = "", packet = "", issue = "", systemPrompt = "";
  let mode: Mode = "unreadable";
  let before: Inventory = {};
  let providerTools: any[] = [];
  let ownedTools: any[] = [];
  const expectedCalls = new Set<string>();
  const executedCalls: Array<{ id: string; tool: string; container_id: string }> = [];
  let started = false;
  let startedAt = 0;
  let error: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let finishing: Promise<void> | undefined;
  let effectiveContextCaptured = false;
  const captures = { attempted: 0, saved: 0, errors: [] as string[] };
  const save = (name: string, value: unknown) => writeFile(join(output, name),
    JSON.stringify(value, null, 2) + "\n", { flag: "wx", mode: 0o600 });

  const finish = (messages: any[] = []): Promise<void> => finishing ??= (async () => {
    if (timer) clearTimeout(timer);
    let result: Record<string, unknown> | undefined;
    try {
      if (!sandbox || !output) throw new Error(error ?? "Worker never initialized");
      const last = [...messages].reverse().find(message => message.role === "assistant");
      if (!last || last.stopReason !== "stop") error ??= `Assistant did not finish normally (${last?.stopReason ?? "no answer"})`;
      if (!captures.saved || captures.errors.length) error ??= "Provider request capture failed";
      if (sandbox.infrastructureErrors.length) error ??= "Container tool transport failed";
      if ([...expectedCalls].some(id => !executedCalls.some(call => call.id === id))) error ??= "A model tool call bypassed the Docker binding";
      await save("tool-bindings.json", { expected: [...expectedCalls], executed: executedCalls });
      const final = last ? textContent(last) : "";
      await save("messages.json", workerContext(messages, systemPrompt, packet, providerTools));
      await writeFile(join(output, "response.md"), final, { flag: "wx", mode: 0o600 });
      const after = await sandbox.inventory();
      await save("inventory-before.json", before);
      await save("inventory-after.json", after);
      await sandbox.saveWorkspace(output);
      result = { ...observations(mode, changedFiles(before, after), final, error),
        elapsed_seconds: (Date.now() - startedAt) / 1000, provider_requests: captures.saved,
        request_capture_errors: captures.errors, infrastructure_errors: sandbox.infrastructureErrors,
        usage: messages.filter(message => message.role === "assistant").map(message => message.usage) };
    } catch (failure) { error ??= String(failure); }
    const container = sandbox?.id;
    try {
      await sandbox?.close();
      if (output) await save("cleanup.json", { removed: true, container_id: container });
    } catch (failure) {
      error ??= String(failure);
      await save("cleanup.json", { removed: false, container_id: container, error: String(failure) }).catch(() => {});
    }
    if (scratch) await rm(scratch, { recursive: true, force: true }).catch(failure => { error ??= String(failure); });
    if (error && output) {
      if (result) Object.assign(result, { run_valid: false, full_historical_pattern: false, run_error: error });
      await save("INVALID.json", { error }).catch(failure => { process.stderr.write(`${failure}\n`); });
    }
    if (result) await save("result.json", result);
  })();

  const fatal = async (stage: string, failure: unknown): Promise<never> => {
    error ??= `${stage}: ${String(failure)}`;
    await finish().catch(() => {});
    process.stderr.write(`Unavailable-issue trial INVALID: ${error}\n`);
    // Pi catches hook errors and otherwise continues: terminate this dedicated child.
    process.exit(70);
  };

  pi.on("before_agent_start", async (event, ctx) => {
    try {
      if (started || event.messageType !== "user") throw new Error("Expected one fresh user task");
      started = true;
      startedAt = Date.now();
      context = ctx;
      const config = launchConfiguration(event.prompt);
      mode = config.mode;
      const fixture = resolve(root, config.fixture);
      const destination = resolve(root, config.output);
      await mkdir(destination, { mode: 0o700 });
      output = destination;
      scratch = join(output, "transport");
      await mkdir(scratch, { mode: 0o700 });
      await save("launch.json", config);
      const { getCurrentTools, toToolDeclaration, declarationsEqual } = await import("@earendil-works/pi-ai");
      const { createGuestAttachment } = await import("../../../config/pi-agent/pi-extensions/guest-tools.ts");
      const attachment = createGuestAttachment(process.env);
      if (!attachment) throw new Error("Existing sandbox attachment required; no host Docker fallback");
      await attachment.ready();
      const execute = guestExecutor((command, signal, onData) => attachment.call("user_bash",
        { command, timeout: 150 }, attachment.context(context), signal, undefined, onData),
      scratch, path => rewritePiResourcePaths(path, attachment.resourcePaths));
      sandbox = new Sandbox(config.image, mode, execute);
      const manifest = await fixtureManifest(fixture);
      if (manifest.schema_version === 2) throw new Error("Historical prompt/model fixtures require run.ts; this template uses the adapted instruction route");
      packet = await readFile(join(fixture, "data/packet.md"), "utf8");
      issue = await readFile(join(fixture, "data/issue.md"), "utf8");
      const skill = await readFile(join(fixture, "data/worker-skill.md"), "utf8");
      await sandbox.start(fixture, packet, issue);
      const permissions = await sandbox.preflight(issue);
      before = await sandbox.inventory();
      await save("preflight.json", { ...permissions, file_mode: permissions.mode, mode,
        image_id: sandbox.imageId, container_id: sandbox.id, fixture: manifest });
      const agents = (await sandbox.io("read", [`${cwd}/AGENTS.md`])).toString();
      systemPrompt = `You are a coding agent implementing a task in ${cwd}.\n\n${agents}\n\n${skill}`;
      if (systemPrompt.includes(issue) || packet.includes(issue)) throw new Error("Hidden instructions leaked into startup");
      pi.setActiveTools(toolNames);
      await save("startup.json", { system_prompt: systemPrompt, task: packet,
        active_tools: pi.getActiveTools(), provider: ctx.model?.provider, model: ctx.model?.id,
        api: ctx.model?.api, thinking: pi.getThinkingLevel(), route: "authenticated Pi subagent" });

      // Discovery excludes duplicate bundle copies; the launcher's forced prefix loads first.
      pi.on("context_with_system", async (request) => {
        try {
          const available = getCurrentTools(request.messages);
          providerTools = ownedTools.map(tool => {
            const actual = available.find(candidate => candidate.name === tool.name);
            if (!actual || !declarationsEqual(actual, tool)) throw new Error(`Worker declaration mismatch: ${tool.name}`);
            return toToolDeclaration(actual);
          });
          const messages = workerContext(request.messages, systemPrompt, packet, providerTools);
          effectiveContextCaptured = true;
          await save(`context-${captures.attempted + 1}.json`, messages);
          return { messages };
        } catch (failure) { return fatal("context", failure); }
      });
      pi.on("before_provider_request", async (request) => {
        try {
          const controlled = workerPayload(request.payload);
          const payload = JSON.stringify(controlled);
          if (!effectiveContextCaptured || payload.includes(launchMarker) ||
            !payload.includes(JSON.stringify(systemPrompt).slice(1, -1)) ||
            (mode === "unreadable" && payload.includes(JSON.stringify(issue).slice(1, -1))) ||
            pi.getActiveTools().sort().join(",") !== [...toolNames].sort().join(",")) {
            throw new Error("Effective instruction or tool exposure mismatch");
          }
          await captureRequest(captures, controlled, save);
          if (captures.errors.length) throw new Error(captures.errors.join("; "));
          return controlled;
        } catch (failure) { await fatal("request", failure); }
      });
      timer = setTimeout(() => { error = "Trial exceeded 10 minute limit"; ctx.abort(); }, 600_000);
      return { systemPrompt };
    } catch (failure) { return fatal("initialize", failure); }
  });
  pi.on("cache_warming_decision", () => ({ action: "stop" }));
  pi.on("tool_call", event => {
    if (!started || !toolNames.includes(event.toolName)) return { block: true, reason: "Only Docker worker tools are admitted" };
    expectedCalls.add(event.toolCallId);
  });
  pi.on("agent_end", event => finish(event.messages));
  pi.on("session_shutdown", () => finish());
  try {
    const sdk = await import("@earendil-works/pi-coding-agent");
    const required = () => {
      if (!sandbox?.id) throw new Error("Docker worker is not admitted");
      return sandbox;
    };
    ownedTools = workerTools(sdk, {
      io: (...args) => required().io(...args),
      shell: (...args) => required().shell(...args),
      get infrastructureErrors() { return required().infrastructureErrors; },
    }).map(tool => ({ ...tool, name: `task_${tool.name}` }));
    // Pi keeps the first registration for each name. Do not collide with guest-tools.
    // Register before native tool selection, but allocate Docker only at agent start.
    for (const tool of ownedTools) {
      const execute = tool.execute.bind(tool);
      pi.registerTool({ ...tool, execute: (id, input, signal, update, toolContext) => {
        context = toolContext;
        executedCalls.push({ id, tool: tool.name, container_id: required().id });
        return execute(id, input, signal, update, toolContext);
      } });
    }
  } catch (failure) { await fatal("tool registration", failure); }
}
