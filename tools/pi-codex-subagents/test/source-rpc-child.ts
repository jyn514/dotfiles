/** A real public-SDK AgentSession and the shipped RPC loop; only model I/O is faux.
 * Accepts the extension manager's CLI-shaped argv, not a replacement production API.
 */
import { appendFileSync, mkdirSync, realpathSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseFactory } from "@earendil-works/pi-ai/providers/faux";
import { providerCallsFile } from "./held-tool-extension.ts";
import { CONTINUATION_MESSAGE } from "../handoff.ts";
import {
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  type CreateAgentSessionRuntimeFactory,
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
const extensions = argv.flatMap((arg, i) => arg === "--extension" ? [resolve(argv[i + 1])] : []);
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
  if (sessionFile) appendFileSync(providerCallsFile(sessionFile), `${JSON.stringify({ pid: process.pid, text, lastRole: context.messages.at(-1)?.role })}\n`);
  const parentTask = context.messages.filter(message => message.role === "user")
    .map(messageText).map(text => text.match(/^parent-(nested-)?held-task:(.+)$/m)).find(Boolean);
  if (parentTask) {
    const completed = (name: string) => context.messages.some(message => message.role === "toolResult" && message.toolName === name && !message.isError);
    if (!completed("spawn_agent")) return fauxAssistantMessage(fauxToolCall("spawn_agent", {
      task_name: "native-child", agent_type: "source-parent-roundtrip", message: `hold-tool:${parentTask[2]}`,
    }), { stopReason: "toolUse" });
    if (!completed("wait_agent")) return fauxAssistantMessage([
      fauxToolCall("wait_agent", { targets: ["native-child"] }),
      fauxToolCall(parentTask[1] ? "faux_nested_send" : "send_message", { target: "native-child", message: "same-batch steering after pause" }),
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
  const services = await createAgentSessionServices({
    cwd, agentDir, modelRuntime,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
    resourceLoaderOptions: {
      noExtensions: true, noSkills: true, noPromptTemplates: true,
      noThemes: true, noContextFiles: true, additionalExtensionPaths: extensions,
      systemPrompt: "Deterministic source integration fixture.",
    },
  });
  const result = await createAgentSessionFromServices({
    services, sessionManager, sessionStartEvent, model: faux.getModel(),
    thinkingLevel: "off", noTools: "builtin",
  });
  if (result.extensionsResult.errors.length) throw new Error(JSON.stringify(result.extensionsResult.errors));
  return { ...result, services, diagnostics: services.diagnostics };
};
const runtime = await createAgentSessionRuntime(createRuntime, {
  cwd: process.cwd(), agentDir,
  sessionManager: sessionFile ? SessionManager.open(sessionFile) : SessionManager.inMemory(process.cwd()),
});
await runRpcMode(runtime);
