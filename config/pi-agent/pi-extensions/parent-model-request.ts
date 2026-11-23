import * as piAI from "@earendil-works/pi-ai";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import {
  convertToLlm, getAgentDir, loadProjectContextFiles, SettingsManager, VERSION,
  type ExtensionAPI, type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type { Model, Provider, SimpleStreamOptions, TranscriptContext } from "@earendil-works/pi-ai";
import { isDeepStrictEqual } from "node:util";
import { detailedReasoningPayload } from "./detailed-reasoning.ts";
import { capOpenRouterOutput } from "./openrouter-output-cap.ts";
import { addWebSearchToPayload } from "./pi-web-search-core.ts";
import { prepareInstructionContext } from "./pi-instruction-includes.ts";
import { guestContextProjection } from "./guest-context.ts";

type Projection = (messages: AgentMessage[], ctx: ExtensionContext) => Promise<AgentMessage[]>;

type Snapshot = {
  model: Model<any>;
  context: TranscriptContext;
  options: SimpleStreamOptions;
  canonical: AgentMessage[];
  sessionId: string;
  settings: string;
  thinkingLevel: ExtensionContext["thinkingLevel"];
  loadout: string;
  hiddenDeclarations: string[];
  basePrompt: string;
  effectivePrompt: string;
  cwd: string;
};

function selectedToolRegistrations(pi: ExtensionAPI) {
  const active = new Set(pi.getActiveTools());
  return pi.getAllTools().filter(tool => active.has(tool.name)).map(tool => ({
    name: tool.name, description: tool.description, parameters: tool.parameters,
  }));
}

function loadoutKey(pi: ExtensionAPI): string {
  // Callable/deferred registrations also change codemode's prepared description.
  return JSON.stringify({ active: pi.getActiveTools(), registered: pi.getAllTools() });
}

function hideDeclarations(messages: AgentMessage[], hidden: string[]): AgentMessage[] {
  if (!hidden.length) return messages;
  const names = new Set(hidden);
  return messages.map(message => {
    if (message.role !== "system" || (!message.toolsAdded && !message.toolsRemoved)) return message;
    const { toolsAdded, toolsRemoved, ...rest } = message;
    const added = toolsAdded?.filter(tool => !names.has(tool.name)) ?? [];
    const removed = toolsRemoved?.filter(tool => !names.has(tool.name)) ?? [];
    return { ...rest, ...(added.length ? { toolsAdded: added } : {}), ...(removed.length ? { toolsRemoved: removed } : {}) };
  });
}

function settingsKey(pi: ExtensionAPI): string {
  return JSON.stringify(pi.getSettings());
}

function convert(messages: AgentMessage[], settings: SettingsManager) {
  const converted = convertToLlm(messages);
  if (!settings.getBlockImages()) return converted;
  return converted.map(message => {
    if ((message.role !== "user" && message.role !== "toolResult") || !Array.isArray(message.content)) return message;
    return {
      ...message,
      content: message.content.map(block => block.type === "image"
        ? { type: "text" as const, text: "Image reading is disabled." } : block)
        .filter((block, index, blocks) => !(block.type === "text" && block.text === "Image reading is disabled."
          && index > 0 && blocks[index - 1].type === "text" && blocks[index - 1].text === block.text)),
    };
  });
}

function coldOptions(pi: ExtensionAPI, ctx: ExtensionContext, settings: SettingsManager): SimpleStreamOptions {
  const retry = settings.getProviderRetrySettings();
  const idle = settings.getHttpIdleTimeoutMs();
  const telemetry = process.env.PI_TELEMETRY;
  const attribution = telemetry === undefined ? settings.getEnableInstallTelemetry()
    : ["1", "true", "yes"].includes(telemetry.toLowerCase());
  return {
    reasoning: ctx.thinkingLevel === "off" ? undefined : ctx.thinkingLevel,
    sessionId: ctx.sessionManager.getSessionId(),
    transport: settings.getTransport(),
    thinkingBudgets: settings.getThinkingBudgets(),
    timeoutMs: retry.timeoutMs ?? (idle === 0 ? 2147483647 : idle),
    websocketConnectTimeoutMs: settings.getWebSocketConnectTimeoutMs(),
    maxRetries: retry.maxRetries,
    maxRetryDelayMs: retry.maxRetryDelayMs,
    identity: { userAgent: "detailed", version: VERSION, attribution: attribution ? piAI.PI_ATTRIBUTION : null },
    // These are the bundle's actual payload transformations, shared with their
    // normal handlers. A cold session has no captured SDK dispatcher to reuse.
    onPayload(payload) {
      let next = detailedReasoningPayload(payload, ctx.model);
      next = addWebSearchToPayload(next, ctx.model?.api);
      if (ctx.model?.provider === "openrouter" && ["anthropic-messages", "openai-completions"].includes(ctx.model.api)) {
        const cap = Number(pi.getFlag("openrouter-max-tokens") ?? "10000");
        if (!Number.isSafeInteger(cap) || cap < 2048) throw new Error("Invalid --openrouter-max-tokens");
        next = capOpenRouterOutput(next, cap);
      }
      return next;
    },
  };
}

const instructionFileText = ({ path, content }: { path: string; content: string }) =>
  `<project_instructions path="${path}">\n${content}\n</project_instructions>`;

async function currentInstructionUpdate(ctx: ExtensionContext, canonical: AgentMessage[], previous?: Snapshot) {
  const base = ctx.getSystemPrompt();
  // Use Pi's file provider, then accept only exact records already rendered in
  // the current base. This does not parse XML or introduce disabled context files.
  const baseFiles = loadProjectContextFiles({ cwd: ctx.cwd, agentDir: getAgentDir() })
    .filter(file => base.includes(instructionFileText(file)));
  const { contextFiles, rootPath, expanded } = await prepareInstructionContext(baseFiles, ctx.cwd);
  const root = contextFiles.find(file => file.path === rootPath);
  const sections = piAI.getCurrentSystemMessage(canonical)?.sections ?? {};
  const rootChanged = root ? !sections.project_context?.includes(instructionFileText(root))
    : sections.project_context?.includes(`<project_instructions path="${rootPath}">`);
  const includes = expanded.length ? `## Expanded instruction includes\n\n${expanded.join("\n\n")}` : undefined;
  const includesChanged = (sections.instruction_includes ?? null) !== (includes ? `<instruction_includes>\n${includes}\n</instruction_includes>` : null);
  const unchanged = base === previous?.basePrompt || base === previous?.effectivePrompt || base === piAI.getCurrentSystemPrompt(canonical);
  if (unchanged && !rootChanged && !includesChanged) return;
  return [
    "Current parent instruction update for this checkpoint. This base supersedes earlier base instructions where they differ. Other run-specific instructions remain in force. The current ROOT and expanded includes below supersede corresponding earlier source blocks, including any in the base text.",
    base,
    root ? `Current ROOT instructions:\n${instructionFileText(root)}` : "No ROOT instructions currently apply; do not apply an earlier ROOT-only contribution.",
    includes ?? "No expanded instruction includes currently apply; do not apply an earlier generated includes contribution.",
  ].join("\n\n");
}

/** Observe Pi's resolved provider rather than rebuilding a live parent request.
 * Snapshots are memory-only and never contain saved credentials or headers.
 * Dispatch remains ModelRegistry.streamSimple, which resolves fresh auth.
 */
export function parentModelRequest(
  pi: ExtensionAPI,
  project: Projection = guestContextProjection(),
) {
  let snapshot: Snapshot | undefined;
  let basePrompt: string | undefined;
  pi.on("before_agent_start", (_event, ctx) => { basePrompt = ctx.getSystemPrompt(); });
  let generating = false;
  const decorated = new Map<string, { original: Provider; wrapper: Provider }>();
  const clear = () => { snapshot = undefined; };

  function install(ctx: ExtensionContext) {
    if (!ctx.model) return;
    const original = ctx.modelRegistry.getProvider(ctx.model.provider);
    if (!original) return;
    const previous = decorated.get(original.id);
    if (previous?.wrapper === original) return;
    const observe = (method: Provider["streamSimple"]) => (model: Model<any>, context: TranscriptContext, options?: SimpleStreamOptions) => {
      // Idle cache warming and other extensions' independent requests must not
      // replace the actual parent request. Summary generation is not a turn.
      if (!generating && ctx.signal && options?.signal === ctx.signal
        && options.sessionId === ctx.sessionManager.getSessionId()
        && ctx.model?.provider === model.provider && ctx.model.id === model.id) {
        const { apiKey: _key, headers: _headers, env: _env, signal: _signal, telemetry: _telemetry, ...reusable } = options;
        snapshot = {
          model, context: structuredClone(context), options: reusable,
          canonical: structuredClone(ctx.sessionManager.buildSessionProjection().messages),
          sessionId: ctx.sessionManager.getSessionId(), settings: settingsKey(pi), thinkingLevel: ctx.thinkingLevel,
          loadout: loadoutKey(pi),
          hiddenDeclarations: pi.getActiveTools().filter(name => !piAI.getCurrentTools(context.messages).some(tool => tool.name === name)),
          basePrompt: basePrompt ?? ctx.getSystemPrompt(), effectivePrompt: ctx.getSystemPrompt(), cwd: ctx.cwd,
        };
      }
      return method.call(original, model, context, options);
    };
    const wrapper = { ...original, stream: observe(original.stream), streamSimple: observe(original.streamSimple) } as Provider;
    decorated.set(original.id, { original, wrapper });
    pi.registerProvider(wrapper);
  }

  pi.on("session_start", (_event, ctx) => { clear(); install(ctx); });
  pi.on("model_select", (_event, ctx) => { clear(); install(ctx); });
  pi.on("session_switch", (_event, ctx) => { clear(); install(ctx); });
  pi.on("session_tree", clear);
  pi.on("session_compact", clear);
  pi.on("session_shutdown", (_event, ctx) => {
    clear();
    for (const { original, wrapper } of decorated.values()) {
      // Do not overwrite a provider another extension replaced after ours.
      if (ctx.modelRegistry.getProvider(original.id) === wrapper) pi.registerProvider(original);
    }
    decorated.clear();
  });

  return {
    async prepare(ctx: ExtensionContext) {
      if (!ctx.model) throw new Error("No active parent model is available");
      const settings = SettingsManager.inMemory(pi.getSettings());
      const projection = ctx.sessionManager.buildSessionProjection();
      const canonical = projection.messages;
      const prefixOffset = canonical.some(message => message.role === "system") ? 0 : 1;
      const prior = snapshot;
      const sameLoadout = prior && prior.sessionId === ctx.sessionManager.getSessionId()
        && prior.settings === settingsKey(pi) && prior.loadout === loadoutKey(pi);
      // Registered definitions are not prepared declarations: codemode changes
      // descriptions and can hide direct tools. A stable loadout keeps the
      // actual normal caller's effective declarations even when thinking or
      // historical context changes require rebuilding its message projection.
      const tools = sameLoadout ? piAI.getCurrentTools(prior.context.messages) : selectedToolRegistrations(pi);
      const systemPrompt = ctx.getSystemPrompt();
      const head: AgentMessage[] = prefixOffset ? [{ role: "system", content: systemPrompt,
        toolsAdded: tools, timestamp: Date.now() }] : [];
      const reusable = sameLoadout && prior.sessionId === ctx.sessionManager.getSessionId()
        && prior.model.provider === ctx.model.provider && prior.model.id === ctx.model.id
        && prior.settings === settingsKey(pi) && prior.thinkingLevel === ctx.thinkingLevel
        && isDeepStrictEqual(canonical.slice(0, prior.canonical.length), prior.canonical);
      const prepared = hideDeclarations([...head, ...structuredClone(canonical)], sameLoadout ? prior.hiddenDeclarations : []);
      const instructionUpdate = await currentInstructionUpdate(ctx, prepared, prior);
      if (instructionUpdate) prepared.push({ role: "system", content: "", sections: {
        current_parent_instructions: `<current_parent_instructions>\n${instructionUpdate}\n</current_parent_instructions>`,
      }, timestamp: Date.now() });
      const changes = piAI.getToolStateChanges(piAI.getCurrentTools(prepared), tools);
      if (!reusable && (changes.toolsAdded.length || changes.toolsRemoved.length)) {
        // Tool selection can change without a turn. Apply its pending delta,
        // but retain canonical prompt sections: ctx.getSystemPrompt() is the
        // base prompt after settlement and omits before_agent_start sections.
        prepared.push({ role: "system", content: "", ...changes, timestamp: Date.now() });
      }
      const current = await project(prepared, ctx);
      // Guest source inputs can change while canonical host history does not.
      // Compare only the projection-owned sections: Pi applies a forced base
      // prompt after context hooks, so comparing the entire system would reject
      // a valid warm snapshot and discard that normal-caller transformation.
      const currentSections = piAI.getCurrentSystemMessage(current)?.sections ?? {};
      const capturedSections = prior ? piAI.getCurrentSystemMessage(prior.context.messages)?.sections ?? {} : {};
      const sameProjection = prior?.cwd === ctx.cwd && ["sandbox_context", "sandbox_instructions"]
        .every(name => (currentSections[name] ?? null) === (capturedSections[name] ?? null));
      const warm = reusable && !instructionUpdate && sameProjection;
      const context: TranscriptContext = warm
        ? { ...prior.context, messages: [...prior.context.messages, ...convert(current.slice(prefixOffset + prior.canonical.length), settings)] }
        : { messages: convert(current, settings) };
      return { model: ctx.model, context, options: warm ? prior.options : coldOptions(pi, ctx, settings),
        projection, current, prefixOffset, mode: warm ? "reused" as const : "rebuilt" as const };
    },
    async complete(ctx: ExtensionContext, request: Awaited<ReturnType<typeof this.prepare>>, task: string, signal: AbortSignal) {
      signal.throwIfAborted();
      generating = true;
      try {
        return await ctx.modelRegistry.streamSimple(request.model, {
          ...request.context,
          messages: [...request.context.messages, { role: "user", content: [{ type: "text", text: task }], timestamp: Date.now() }],
        }, { ...request.options, signal }).result();
      } finally {
        generating = false;
      }
    },
  };
}
