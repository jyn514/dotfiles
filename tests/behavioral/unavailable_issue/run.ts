#!/usr/bin/env bun
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { captureRequest, changedFiles, cwd, fixtureManifest, hash, nativeTaskChanges, observations, Sandbox, type Mode } from "./runtime.ts";
import { workerTools } from "./worker-tools.ts";

const { values } = parseArgs({ options: {
  fixture: { type: "string" }, output: { type: "string" }, image: { type: "string" },
  mode: { type: "string", default: "unreadable" }, provider: { type: "string" }, model: { type: "string" },
  thinking: { type: "string", default: "medium" }, "pi-package": { type: "string" },
  "auth-path": { type: "string" },
  "allow-model-change": { type: "boolean", default: false },
  "preflight-only": { type: "boolean", default: false }, help: { type: "boolean", default: false },
} });
if (values.help) {
  console.log("bun run.ts --fixture DIR --output NEW_DIR --image EXISTING_IMAGE [--mode unreadable|readable] [--preflight-only | --provider NAME --model ID --pi-package DIR] [--thinking medium] [--auth-path EXPLICIT_CREDENTIAL_FILE]");
  process.exit(0);
}
if (!values.fixture || !values.output || !values.image) throw new Error("--fixture, --output, and --image are required");
if (!["unreadable", "readable"].includes(values.mode!)) throw new Error("--mode must be unreadable or readable");
if (!["off", "minimal", "low", "medium", "high", "xhigh"].includes(values.thinking!)) throw new Error("Unsupported thinking level");
const packageDir = values["pi-package"] || process.env.PI_PACKAGE_DIR;
if (!values["preflight-only"] && (!values.provider || !values.model || !packageDir)) {
  throw new Error("Live runs require --provider, --model, and --pi-package (or PI_PACKAGE_DIR)");
}
const fixture = resolve(values.fixture), output = resolve(values.output);
const manifest = await fixtureManifest(fixture);
const historical = manifest.schema_version === 2 ? JSON.parse(await readFile(join(fixture, "data/historical.json"), "utf8")) : null;
if (historical && !values["preflight-only"] &&
  ((!values["allow-model-change"] && values.model !== historical.model) || values.thinking !== historical.thinking)) {
  throw new Error("Historical runs require recorded model/thinking; use --allow-model-change for an explicitly requested model comparison");
}
await mkdir(output); // Never overwrite evidence from an earlier attempt.
const save = (name: string, data: unknown) => writeFile(join(output, name), JSON.stringify(data, null, 2) + "\n", { flag: "wx" });
const packet = await readFile(join(fixture, "data/packet.md"), "utf8");
const workerSkill = await readFile(join(fixture, "data/worker-skill.md"), "utf8");
const issue = await readFile(join(fixture, "data/issue.md"), "utf8");
const sandbox = new Sandbox(values.image, values.mode as Mode);
const agentDir = await mkdtemp(join(tmpdir(), "unavailable-issue-agent-"));
let session: any;
let runError: string | null = null;
let primaryError: unknown;
let resultToSave: Record<string, unknown> | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
const started = Date.now();
try {
  await sandbox.start(fixture, packet, issue);
  const permissions = await sandbox.preflight(issue);
  const before = await sandbox.inventory();
  await save("preflight.json", { ...permissions, image_id: sandbox.imageId, container_id: sandbox.id, fixture: manifest,
    file_mode: permissions.mode, mode: values.mode, packet_sha256: hash(packet), worker_skill_sha256: hash(workerSkill), issue_sha256: hash(issue) });
  if (values["preflight-only"]) {
    console.log(`Permission preflight passed (${values.mode}); evidence: ${output}`);
  } else {
    const metadata = JSON.parse(await readFile(join(packageDir!, "package.json"), "utf8"));
    if (metadata.name !== "@earendil-works/pi-coding-agent" || typeof metadata.exports?.["."]?.import !== "string") {
      throw new Error("--pi-package must publish the Pi public SDK ESM entrypoint");
    }
    const sdk = await import(pathToFileURL(resolve(packageDir!, metadata.exports["."].import)).href);
    const runtime = await sdk.ModelRuntime.create({ authPath: values["auth-path"],
      ...(historical ? { modelsPath: null } : {}) }); // Native host auth; never copied into Docker.
    const model = runtime.getModel(values.provider, values.model);
    if (!model) throw new Error(`Model unavailable: ${values.provider}/${values.model}`);
    const agents = historical ? "" : (await sandbox.io("read", [`${cwd}/AGENTS.md`])).toString();
    const systemPrompt = historical ? [historical.base_instructions, ...historical.developer_instructions].join("\n\n") :
      `You are a coding agent implementing a task in ${cwd}.\n\n${agents}\n\n${workerSkill}`;
    if (systemPrompt.includes(issue) || packet.includes(issue)) throw new Error("Hidden instructions leaked into startup inputs");
    const settingsManager = sdk.SettingsManager.inMemory({ compaction: { enabled: false },
      retry: { enabled: false }, cacheWarming: "off" });
    const captures = { attempted: 0, saved: 0, errors: [] as string[] };
    let exposureInvalid = false;
    const resourceLoader = new sdk.DefaultResourceLoader({
      cwd: agentDir, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      systemPrompt, appendSystemPrompt: [],
      extensionFactories: [(pi: any) => {
        if (historical) pi.on("context_with_system", async (event: any) => {
          const initial = event.messages.findIndex((message: any) => message.role === "user");
          if (initial < 0) throw new Error("Initial worker message missing");
          const messages = [...event.messages.slice(0, initial),
            ...historical.user_messages.map((content: string) => ({ role: "user", content: [{ type: "text", text: content }] })),
            ...event.messages.slice(initial + 1)];
          await save(`context-${captures.attempted + 1}.json`, messages);
          return { messages };
        });
        pi.on("before_provider_request", async (event: any) => {
          const payload = JSON.stringify(event.payload);
          if (values.mode === "unreadable" && payload.includes(JSON.stringify(issue).slice(1, -1))) exposureInvalid = true;
          await captureRequest(captures, event.payload, save); // Body only, never auth headers.
        });
      }],
    });
    await resourceLoader.reload();
    const tools = workerTools(sdk, sandbox);
    ({ session } = await sdk.createAgentSession({ cwd, agentDir, modelRuntime: runtime, model,
      thinkingLevel: values.thinking, resourceLoader, settingsManager,
      tools: ["read", "edit", "write", "bash"], customTools: tools,
      sessionManager: sdk.SessionManager.inMemory(cwd) }));
    await session.bindExtensions({});
    await save("startup.json", { system_prompt: session.systemPrompt, task: packet,
      active_tools: session.getActiveToolNames(), provider: model.provider, model: model.id,
      api: model.api, thinking: session.thinkingLevel, sdk_version: metadata.version,
      ...(historical ? { recorded_model: historical.model, model_changed: model.id !== historical.model,
        initial_user_messages: historical.user_messages } : {}) });
    const messages: any[] = [];
    session.subscribe((event: any) => { if (event.type === "message_end") messages.push(event.message); });
    let timedOut = false;
    timer = setTimeout(() => { timedOut = true; void session.abort(); }, 10 * 60 * 1000);
    try { await session.prompt(packet); }
    catch (error) { runError = String(error); }
    clearTimeout(timer);
    if (timedOut) runError = "Trial exceeded 10 minute limit";
    const last = [...session.messages].reverse().find((message: any) => message.role === "assistant");
    if (!last || last.stopReason !== "stop") runError ??= `Assistant did not finish normally (${last?.stopReason ?? "no answer"})${last?.errorMessage ? `: ${last.errorMessage}` : ""}`;
    if (exposureInvalid || captures.saved === 0 || captures.errors.length) runError ??= "Instruction exposure invalid or provider request capture failed";
    if (sandbox.infrastructureErrors.length) runError ??= "Container tool transport failed";
    await save("messages.json", session.messages);
    await save("completed-events.json", messages);
    await writeFile(join(output, "response.md"), session.getLastAssistantText() ?? "", { flag: "wx" });
    const after = await sandbox.inventory();
    await save("inventory-before.json", before);
    await save("inventory-after.json", after);
    await sandbox.saveWorkspace(output);
    resultToSave = { ...observations(values.mode as Mode, changedFiles(before, after),
      session.getLastAssistantText() ?? "", runError), elapsed_seconds: (Date.now() - started) / 1000,
      native_task_changes: nativeTaskChanges(session.messages),
      provider_requests: captures.saved, request_capture_errors: captures.errors,
      infrastructure_errors: sandbox.infrastructureErrors,
      usage: session.messages.filter((message: any) => message.role === "assistant").map((message: any) => message.usage) };
    if (runError) throw new Error(runError);
  }
} catch (error) {
  primaryError = error;
} finally {
  if (timer) clearTimeout(timer);
  session?.dispose();
  const containerId = sandbox.id;
  try { await sandbox.close(); await save("cleanup.json", { removed: true, container_id: containerId }); }
  catch (error) {
    primaryError ??= error;
    await save("cleanup.json", { removed: false, container_id: containerId, error: String(error) }).catch(() => {});
  }
  await rm(agentDir, { recursive: true, force: true });
}
if (primaryError) {
  if (resultToSave) Object.assign(resultToSave, { run_valid: false, full_historical_pattern: false, run_error: String(primaryError) });
  await save("INVALID.json", { error: String(primaryError), elapsed_seconds: (Date.now() - started) / 1000 });
}
if (resultToSave) await save("result.json", resultToSave);
if (primaryError) { console.error(`Trial failed: ${String(primaryError)}. Evidence retained in ${output}`); process.exitCode = 1; }
else if (resultToSave) console.log(`Trial recorded; review result.json, response.md, messages.json, and workspace-after.tar in ${output}`);
