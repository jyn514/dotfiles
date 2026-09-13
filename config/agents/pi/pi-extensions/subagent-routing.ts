import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  isToolCallEventType,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import {
  classifySubagentRoute,
  type SpawnAgentInput,
} from "./subagent-routing-core.ts";

const LUNA_TEMPLATE = join(
  homedir(),
  ".pi",
  "agent",
  "pi-codex-subagents",
  "agents",
  "luna.md",
);
const LUNA_PROVIDER = "openai-codex";
const LUNA_MODEL = "gpt-5.6-luna";

interface RoutingDependencies {
  templateExists?: () => boolean;
}

export default function subagentRouting(
  pi: ExtensionAPI,
  dependencies: RoutingDependencies = {},
): void {
  const templateExists = dependencies.templateExists ?? (() => existsSync(LUNA_TEMPLATE));

  pi.on("tool_call", (event, ctx) => {
    if (!isToolCallEventType<"spawn_agent", SpawnAgentInput>("spawn_agent", event)) return;

    const decision = classifySubagentRoute(event.input);
    if (decision.route !== "luna") return;

    const model = ctx.modelRegistry.find(LUNA_PROVIDER, LUNA_MODEL);
    if (!templateExists() || !model || !ctx.modelRegistry.hasConfiguredAuth(model)) return;

    event.input.agent_type = "luna";
    ctx.ui.notify(`Subagent routed to Luna: ${decision.reason}`, "info");
  });
}
