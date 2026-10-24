/** A real public-SDK AgentSession and the shipped RPC loop; only model I/O is faux.
 * Accepts the extension manager's CLI-shaped argv, not a replacement production API.
 */
import { appendFileSync, mkdirSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { getCurrentSystemPrompt, getCurrentTools } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { CHILD_BUILTIN_EXTENSION_NAMES } from "../core.ts";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseFactory } from "@earendil-works/pi-ai/providers/faux";
import { providerCallsFile } from "./held-tool-extension.ts";
import { CONTINUATION_MESSAGE } from "../handoff.ts";
import {
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  type CreateAgentSessionRuntimeFactory,
  type InlineExtension,
  ModelRuntime,
  runRpcMode,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const root = process.env.PI_TEST_OWNED_ROOT;
if (!root || !process.env.PI_TEST_CORE_TSCONFIG) throw new Error("Use the isolated source-test bootstrap");
const isOwned = (path: string) => {
  const rel = relative(realpathSync(root), realpathSync(path));
  return rel === "" || (rel !== ".." && !rel.startsWith("../") && !rel.startsWith("/"));
};
if (!isOwned(process.cwd()) || !isOwned(process.env.HOME!)) throw new Error("Fixture cwd and HOME must be disposable");
const argv = process.argv.slice(2);
const option = (name: string) => { const i = argv.indexOf(name); return i < 0 ? undefined : argv[i + 1]; };
const sessionFile = option("--session");
if (sessionFile && !isOwned(dirname(resolve(sessionFile)))) throw new Error("Session file must be disposable");
const extensions = argv.flatMap((arg, i) => arg === "--extension"
  ? [argv[i + 1].startsWith("builtin:") ? argv[i + 1] : resolve(argv[i + 1])] : []);
const skills = argv.flatMap((arg, i) => arg === "--skill" ? [resolve(argv[i + 1])] : []);
const agentDir = join(process.env.HOME!, ".pi/agent");
mkdirSync(agentDir, { recursive: true });
const faux = fauxProvider();
function messageText(message: { content: unknown } | undefined): string {
  if (typeof message?.content === "string") return message.content;
  return Array.isArray(message?.content) ? message.content.filter(part => part.type === "text").map(part => part.text).join("\n") : "";
}
// An unlimited deterministic responder permits steer/resume without paid APIs.
// Fixed fixture task texts exercise production tools, not a fixture-only agent API.
const respond: FauxResponseFactory = (context) => {
  faux.appendResponses([respond]);
  const last = context.messages.findLast((message) => message.role === "user");
  const text = messageText(last);
  if (sessionFile) appendFileSync(providerCallsFile(sessionFile), `${JSON.stringify({ pid: process.pid, text, systemPrompt: getCurrentSystemPrompt(context.messages), lastRole: context.messages.at(-1)?.role, tools: getCurrentTools(context.messages).map(tool => tool.name) })}\n`);
  const savedLinkTask = context.messages.filter(message => message.role === "user")
    .map(messageText).map(text => text.match(/^saved-link-reference:(.+)$/m)).find(Boolean);
  if (savedLinkTask) {
    const request = JSON.parse(savedLinkTask[1]) as { path: string; replyTo: string };
    if (text === CONTINUATION_MESSAGE) {
      const userIndex = context.messages.findLastIndex(message => message === last);
      const completed = context.messages.slice(userIndex + 1).some(message => message.role === "toolResult" && message.toolName === "link_reply");
      if (completed) return fauxAssistantMessage("faux:saved-reference-replied");
      const held = context.messages.slice(userIndex + 1).some(message => message.role === "toolResult"
        && message.toolName === "faux_hold" && message.details?.path === `${request.path}.resume`);
      return held ? fauxAssistantMessage(fauxToolCall("link_reply", {
        replyTo: request.replyTo, message: "reply after child recreation",
      }), { stopReason: "toolUse" })
        : fauxAssistantMessage(fauxToolCall("faux_hold", { path: `${request.path}.resume` }), { stopReason: "toolUse" });
    }
    const calls = context.messages.filter(message => message.role === "assistant")
      .flatMap(message => message.content).filter(part => part.type === "toolCall");
    const first = `${request.path}.first`;
    const second = `${request.path}.second`;
    if (!calls.some(call => call.name === "faux_hold" && call.arguments.path === first)) {
      return fauxAssistantMessage(fauxToolCall("faux_hold", { path: first }), { stopReason: "toolUse" });
    }
    if (!calls.some(call => call.name === "faux_hold" && call.arguments.path === second)) {
      return fauxAssistantMessage(fauxToolCall("faux_hold", { path: second }), { stopReason: "toolUse" });
    }
    return fauxAssistantMessage("faux:saved-reference-before-pause");
  }
  const queuedReply = text.match(/^queued-link-reply:(.+)$/m);
  if (queuedReply) {
    const request = JSON.parse(queuedReply[1]) as { path: string; replyTo: string };
    const userIndex = context.messages.findLastIndex(message => message === last);
    const completed = context.messages.slice(userIndex + 1).some(message => message.role === "toolResult" && message.toolName === "link_reply");
    return completed ? fauxAssistantMessage("faux:queued-reply-complete") : fauxAssistantMessage([
      fauxToolCall("faux_hold_sequential", { path: request.path }),
      fauxToolCall("link_reply", { replyTo: request.replyTo, message: "queued attempt" }),
    ], { stopReason: "toolUse" });
  }
  const invoke = text.match(/^invoke-tool:(.+)$/m);
  if (invoke) {
    const request = JSON.parse(invoke[1]) as { name: string; args: Record<string, unknown> };
    const userIndex = context.messages.findLastIndex(message => message === last);
    const completed = context.messages.slice(userIndex + 1).some(message => message.role === "toolResult" && message.toolName === request.name);
    return completed ? fauxAssistantMessage(`faux:invoked:${request.name}`)
      : fauxAssistantMessage(fauxToolCall(request.name, request.args), { stopReason: "toolUse" });
  }
  if (text.startsWith("[Link") && text.includes("ask-link-question")) {
    const reference = text.match(/^Message ID: (.+)$/m)?.[1];
    const originalHold = context.messages.filter(message => message.role === "user")
      .map(messageText).map(text => text.match(/^hold-tool:(.+)$/m)).find(Boolean);
    const userIndex = context.messages.findLastIndex(message => message === last);
    const called = context.messages.slice(userIndex + 1).some(message => message.role === "toolResult" && message.toolName === "link_reply");
    if (reference && originalHold && !called) return fauxAssistantMessage([
      fauxToolCall("link_reply", { replyTo: reference, message: "same question" }),
      fauxToolCall("faux_hold", { path: `${originalHold[1]}.after-question` }),
    ], { stopReason: "toolUse" });
  }
  const linkTask = context.messages.filter(message => message.role === "user")
    .map(messageText).map(text => text.match(/^link-worker:(.+)$/m)).find(Boolean);
  if (linkTask) {
    const calls = context.messages.filter(message => message.role === "assistant")
      .flatMap(message => message.content).filter(part => part.type === "toolCall");
    const first = `${linkTask[1]}.first`;
    const second = `${linkTask[1]}.second`;
    if (!calls.some(call => call.name === "faux_hold" && call.arguments.path === first)) {
      return fauxAssistantMessage(fauxToolCall("faux_hold", { path: first }), { stopReason: "toolUse" });
    }
    const delivered = context.messages.filter(message => message.role === "user").map(messageText)
      .filter(text => text.startsWith("[Link")).map(text => text.match(/^Message ID: (.+)$/m)?.[1]).filter(Boolean);
    const reference = delivered.find(id => !calls.some(call => call.name === "link_reply" && call.arguments.replyTo === id));
    if (reference) return fauxAssistantMessage(fauxToolCall("link_reply", { replyTo: reference, message: "native worker reply" }), { stopReason: "toolUse" });
    if (!calls.some(call => call.name === "faux_hold" && call.arguments.path === second)) {
      return fauxAssistantMessage(fauxToolCall("faux_hold", { path: second }), { stopReason: "toolUse" });
    }
    return fauxAssistantMessage("faux:link-worker-complete");
  }
  const parentTask = context.messages.filter(message => message.role === "user")
    .map(messageText).map(text => text.match(/^parent-(nested-|blocked-)?held-task:(.+)$/m)).find(Boolean);
  if (parentTask) {
    const completed = (name: string) => context.messages.some(message => message.role === "toolResult" && message.toolName === name && !message.isError);
    if (!completed("spawn_agent")) return fauxAssistantMessage(fauxToolCall("spawn_agent", {
      task_name: "native-child", agent_type: "source-parent-roundtrip", message: `hold-tool:${parentTask[2]}`,
    }), { stopReason: "toolUse" });
    if (!completed("wait_agent")) return fauxAssistantMessage([
      fauxToolCall("wait_agent", { targets: ["native-child"] }),
      ...(parentTask[1] === "blocked-" ? [fauxToolCall("faux_hold", { path: `${parentTask[2]}.parent` })] : []),
      fauxToolCall(parentTask[1] === "nested-" ? "faux_nested_send" : "send_message", { target: "native-child", message: "same-batch steering after pause" }),
    ], { stopReason: "toolUse" });
    return fauxAssistantMessage("faux:parent-complete");
  }
  const resumeHold = context.messages.filter(message => message.role === "user")
    .map(messageText).map(text => text.match(/^resume-hold-tool:(.+)$/m)).find(Boolean);
  if (text === CONTINUATION_MESSAGE && resumeHold
    && context.messages.filter(message => message.role === "toolResult" && message.toolName === "faux_hold").length < 2) {
    return fauxAssistantMessage(fauxToolCall("faux_hold", { path: resumeHold[1] }), { stopReason: "toolUse" });
  }
  const hold = text.match(/^hold-tool:(.+)$/m);
  const lastUserIndex = context.messages.findLastIndex((message) => message === last);
  const alreadyExecuted = context.messages.slice(lastUserIndex + 1).some((message) => message.role === "toolResult" && message.toolName === "faux_hold");
  if (hold && !alreadyExecuted) return fauxAssistantMessage(fauxToolCall("faux_hold", { path: hold[1] }), { stopReason: "toolUse" });
  return fauxAssistantMessage(`faux:${text}`);
};
faux.setResponses([respond]);
const modelRuntime = await ModelRuntime.create({
  authPath: join(agentDir, "auth.json"), modelsPath: null,
  allowModelNetwork: false, refreshOnCreate: false,
});
modelRuntime.registerNativeProvider(faux.provider);
const createRuntime: CreateAgentSessionRuntimeFactory = async ({ cwd, agentDir, sessionManager, sessionStartEvent }) => {
  const settingsManager = SettingsManager.create(cwd, agentDir, { projectTrusted: argv.includes("--approve") });
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const systemPrompt = option("--system-prompt");
  const services = await createAgentSessionServices({
    cwd, agentDir, modelRuntime, settingsManager,
    resourceLoaderOptions: {
      noExtensions: argv.includes("--no-extensions"),
      noSkills: argv.includes("--no-skills"), noPromptTemplates: argv.includes("--no-prompt-templates"),
      noThemes: true, noContextFiles: argv.includes("--no-context-files"), additionalExtensionPaths: extensions,
      additionalSkillPaths: skills,
      // Use public built-in factory descriptors, not the CLI's private registry.
      // These no-I/O tools expose selection/registration without model services.
      extensionFactories: CHILD_BUILTIN_EXTENSION_NAMES.map(name => ({
        name, builtin: true,
        factory(pi) {
          if (sessionFile) appendFileSync(`${sessionFile}.builtin-factories.jsonl`, JSON.stringify({ name, phase: "factory", pid: process.pid }) + "\n");
          pi.on("session_start", () => {
            if (sessionFile) appendFileSync(`${sessionFile}.builtin-factories.jsonl`, JSON.stringify({ name, phase: "hook", pid: process.pid }) + "\n");
          });
          pi.registerTool({
            name: `faux_builtin_${name.replaceAll(/[.-]/g, "_")}`, label: `Built-in ${name}`, description: "No-I/O built-in fixture tool.",
            parameters: Type.Object({}),
            async execute() { return { content: [{ type: "text", text: name }], details: {} }; },
          });
        },
      } satisfies InlineExtension)),
      systemPrompt: systemPrompt ? readFileSync(systemPrompt, "utf8") : "Deterministic source integration fixture.",
      appendSystemPrompt: option("--append-system-prompt") === undefined ? undefined : [option("--append-system-prompt")!],
    },
  });
  const result = await createAgentSessionFromServices({
    services, sessionManager, sessionStartEvent, model: faux.getModel(),
    thinkingLevel: "off",
    tools: option("--tools")?.split(",").map(name => name.trim()).filter(Boolean),
    noTools: argv.includes("--no-tools") ? "all"
      : argv.includes("--no-builtin-tools") ? "builtin" : undefined,
  });
  if (result.extensionsResult.errors.length) throw new Error(JSON.stringify(result.extensionsResult.errors));
  return { ...result, services, diagnostics: services.diagnostics };
};
const runtime = await createAgentSessionRuntime(createRuntime, {
  cwd: process.cwd(), agentDir,
  sessionManager: sessionFile ? SessionManager.open(sessionFile) : SessionManager.inMemory(process.cwd()),
});
await runRpcMode(runtime);
