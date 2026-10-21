import { StringEnum } from "@earendil-works/pi-ai";
import type { AgentToolResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { goalToolResponse, toToolText, type GoalToolResponse } from "./format.ts";
import { createGoal, parseTokenBudgetPolicy, replaceGoal, type TokenBudgetPolicy } from "./state.ts";
import { TOOL_PROMPT_GUIDELINES } from "./prompts.ts";
import type { GoalToolStatus, GoalEntrySource, GoalResult, ThreadGoal } from "./types.ts";

const EmptyParams = Type.Object({});

function createGoalParams(policy: TokenBudgetPolicy) {
  return Type.Object({
    objective: Type.String({
      description: "Concrete objective to pursue until completion.",
    }),
    ...(policy === "disabled" ? {} : {
      token_budget: Type.Optional(Type.Integer({
        description: `Optional integer token budget of at least ${policy}; omit for unlimited.`,
        minimum: policy,
        maximum: Number.MAX_SAFE_INTEGER,
      })),
    }),
    replace_existing: Type.Optional(Type.Boolean({
      description:
        "Replace an existing non-complete goal. Use only when the user explicitly asks to set a new goal over the current one.",
    })),
  }, policy === "disabled" ? { additionalProperties: false } : {});
}

const UpdateGoalParams = Type.Object({
  status: StringEnum(["complete", "blocked", "paused", "active"] as const, {
    description: "Complete only when no required work remains; blocked only when a dependency prevents all remaining authorized work. Paused only annotates an already-paused goal; active only reactivates an identified blocked goal after dependency resolution.",
  }),
  goal_id: Type.Optional(Type.String({ minLength: 1, description: "Required only for active: use the exact current goalId to reactivate a blocked goal." })),
  reason: Type.Optional(Type.String({ minLength: 1, description: "Required for blocked: explain the dependency, what it prevents, and why no independent authorized work remains. Required for paused: annotate an already-paused goal without resuming it. Required for active: explain how new information resolves the recorded dependency." })),
});

export interface ToolHost {
  getGoal(): ThreadGoal | null;
  setGoal(goal: ThreadGoal, source: GoalEntrySource, ctx: ExtensionContext): void;
  updateGoal(source: GoalEntrySource, ctx: ExtensionContext, toolCallId: string, status: GoalToolStatus, reason?: string, goalId?: string, signal?: AbortSignal): GoalResult;
}

function textResult(
  text: string,
  goal: ThreadGoal | null,
  includeCompletionBudgetReport = false,
): AgentToolResult<GoalToolResponse & { error: string | null }> {
  return {
    content: [{ type: "text", text }],
    details: { ...goalToolResponse(goal, includeCompletionBudgetReport), error: null },
  };
}

function throwToolError(message: string): never {
  throw new Error(message);
}

export function registerGoalTools(pi: ExtensionAPI, host: ToolHost): void {
  const policy = parseTokenBudgetPolicy(process.env.PI_CODEX_GOAL_TOKEN_BUDGET_POLICY);
  pi.registerTool({
    name: "get_goal",
    label: "Get Goal",
    description: "Get the current Codex-style goal and usage for this pi session.",
    promptSnippet: "Inspect the current goal, status, token budget, tokens used, and active elapsed time.",
    promptGuidelines: TOOL_PROMPT_GUIDELINES,
    parameters: EmptyParams,
    async execute() {
      const goal = host.getGoal();
      return textResult(toToolText(goal), goal);
    },
  });

  pi.registerTool({
    name: "create_goal",
    label: "Create Goal",
    description: "Create a Codex-style long-running goal for this pi session.",
    promptSnippet:
      "Create one goal with an objective and optional token budget (unlimited if omitted). Fails when a non-complete goal already exists unless replace_existing is true; replaces a completed goal.",
    promptGuidelines: TOOL_PROMPT_GUIDELINES,
    parameters: createGoalParams(policy),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const current = host.getGoal();
      if (policy === "disabled" && params.token_budget !== undefined) {
        throwToolError("Explicit token budgets are disabled; omit token_budget for unlimited.");
      }
      const tokenBudget = params.token_budget;
      if (tokenBudget != null && typeof tokenBudget !== "number") {
        throwToolError("Token budget must be a number.");
      }
      const shouldReplaceExisting = params.replace_existing === true && current !== null && current.status !== "complete";
      const result = shouldReplaceExisting
        ? replaceGoal(params.objective, tokenBudget ?? null, policy)
        : createGoal(current, params.objective, tokenBudget ?? null, policy);
      if (!result.ok || !result.goal) {
        throwToolError(result.message);
      }
      host.setGoal(result.goal, "tool", ctx);
      return textResult(toToolText(result.goal), result.goal);
    },
  });

  pi.registerTool({
    name: "update_goal",
    label: "Update Goal",
    description:
      "Mark the whole goal complete only after the objective is achieved, or blocked only when remaining unmet outcomes and independent authorized work cannot progress. A blocked investigation is not a blocked goal. Blocking requires a dependency reason and stops automatic continuation until explicit reactivation. Use active with goal_id and a resolution reason only when new information resolves the blocked dependency; never bypass a human pause or budget limit. Use paused with a reason to annotate an already-paused goal.",
    promptSnippet: "Complete only after verified achievement of the whole objective; block only when no authorized progress remains. Reactivate only blocked goals with active, matching goal_id, and a resolution reason; never bypass a human pause or budget limit. Use paused with a reason only to annotate an already-paused goal.",
    promptGuidelines: TOOL_PROMPT_GUIDELINES,
    parameters: UpdateGoalParams,
    executionMode: "sequential",
    async execute(toolCallId, params, signal, _onUpdate, ctx) {
      if (params.status !== "complete" && params.status !== "blocked" && params.status !== "paused" && params.status !== "active") {
        throwToolError("Status must be complete, blocked, paused, or active.");
      }
      const result = host.updateGoal("tool", ctx, toolCallId, params.status, params.reason, params.goal_id, signal);
      if (!result.ok || !result.goal) {
        throwToolError(result.message);
      }
      const includeCompletionReport = result.goal.status === "complete";
      return textResult(toToolText(result.goal, includeCompletionReport), result.goal, includeCompletionReport);
    },
  });
}
