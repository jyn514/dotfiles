export interface SpawnAgentInput {
  agent_type?: unknown;
  skills?: unknown;
  [key: string]: unknown;
}

export type SubagentRouteDecision =
  | { route: "luna"; reason: string }
  | { route: "parent"; reason: string };

export const LUNA_SAFE_SKILLS = new Set([
  "session-title-curation",
  "tighten-docs",
]);

export function classifySubagentRoute(input: SpawnAgentInput): SubagentRouteDecision {
  if (typeof input.agent_type === "string" && input.agent_type.trim()) {
    return { route: "parent", reason: "explicit agent template" };
  }

  if (!Array.isArray(input.skills) || input.skills.length === 0) {
    return { route: "parent", reason: "no routing skill" };
  }

  if (!input.skills.every(
    (skill): skill is string => typeof skill === "string" && LUNA_SAFE_SKILLS.has(skill),
  )) {
    return { route: "parent", reason: "skill set requires the parent model" };
  }

  return {
    route: "luna",
    reason: `Luna-safe skill: ${input.skills.join(", ")}`,
  };
}
