import { fullName, normalizeName, savedIdentity, splitName, type LinkIdentity } from "./identity-format.mjs";

// Keep the extension's existing import surface; the Node CLI uses the same decoder.
export { fullName, groupOf, normalizeName } from "./identity-format.mjs";
export type { IdentityOrigin, LinkIdentity } from "./identity-format.mjs";

/**
 * Apply an accepted manual combined-name assignment. Blank input is not an
 * assignment (the command resolves its session-name fallback before calling us).
 * Do not impose the agent API's local-name restrictions on historical user names.
 */
export function applyUserIdentity(
  current: LinkIdentity,
  combinedName: string,
): LinkIdentity {
  const combined = normalizeName(combinedName);
  if (!combined) throw new Error("A user identity requires a nonempty combined name");
  return {
    ...splitName(combined),
    nameOrigin: "user",
    groupOrigin:
      combined.includes("@") || current.group !== ""
        ? "user"
        : current.groupOrigin,
  };
}

type IdentityField = "name" | "group";
export type AgentIdentityResult =
  | { ok: true; identity: LinkIdentity }
  | { ok: false; error: string; protectedFields?: IdentityField[] };

/** Validate first, then commit both fields together; a refusal never mutates current. */
export function applyAgentIdentity(
  current: LinkIdentity,
  update: { name?: string; group?: string },
): AgentIdentityResult {
  if (update.name === undefined && update.group === undefined) {
    return { ok: false, error: "Supply at least one of name or group" };
  }
  let name = current.name;
  let group = current.group;
  if (update.name !== undefined) {
    // The public tool schema supplies strings; reject malformed runtime callers too.
    if (typeof update.name !== "string") {
      return { ok: false, error: "Name must be a string" };
    }
    const normalized = normalizeName(update.name);
    if (!normalized || normalized.includes("@")) {
      return { ok: false, error: "Name must be nonempty and must not contain @" };
    }
    name = normalized;
  }
  if (update.group !== undefined) {
    if (typeof update.group !== "string") {
      return { ok: false, error: "Group must be a string" };
    }
    group = normalizeName(update.group) ?? "";
  }
  const protectedFields: IdentityField[] = [];
  if (name !== current.name && current.nameOrigin === "user") protectedFields.push("name");
  if (group !== current.group && current.groupOrigin === "user") protectedFields.push("group");
  if (protectedFields.length) {
    return {
      ok: false,
      error: `User-owned identity fields cannot be replaced: ${protectedFields.join(", ")}`,
      protectedFields,
    };
  }
  return {
    ok: true,
    identity: {
      name,
      group,
      nameOrigin: name === current.name ? current.nameOrigin : "agent",
      groupOrigin: group === current.group ? current.groupOrigin : "agent",
      ...(group === current.group && current.explicitGroup !== undefined
        ? { explicitGroup: current.explicitGroup }
        : {}),
    },
  };
}

/**
 * The manager inherits this snapshot and supplies PI_SUBAGENT_PARENT_SESSION_ID.
 * Match that ID so an ordinary nested terminal cannot inherit a worker default.
 * Missing, stale, or malformed handoffs keep the independent random default.
 */
export function generatedName(suffix: string, parentSessionId?: string, parentIdentity?: string): string {
  const fallback = `t-${suffix}`;
  if (!parentSessionId || !parentIdentity) return fallback;
  let value: unknown;
  try { value = JSON.parse(parentIdentity); } catch { return fallback; }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return fallback;
  const snapshot = value as Record<string, unknown>;
  if (snapshot.version !== 1 || snapshot.sessionId !== parentSessionId || typeof snapshot.name !== "string") return fallback;
  const combined = normalizeName(snapshot.name);
  if (!combined) return fallback;
  const parent = splitName(combined);
  if (!parent.name) return fallback;
  const prefix = parent.name.startsWith("t-") ? parent.name : `t-${parent.name}`;
  return fullName({ ...parent, name: `${prefix}-subagent-${suffix}`, nameOrigin: "generated", groupOrigin: "generated" });
}

/** Resolve CLI > environment > latest saved naming entry > session > generated. */
export function initialIdentity(options: {
  generatedName: string;
  entries: readonly unknown[];
  cliName?: string;
  envName?: string;
  sessionName?: string;
}): LinkIdentity {
  const generated = normalizeName(options.generatedName);
  if (!generated) throw new Error("A generated identity requires a nonempty combined name");
  let identity: LinkIdentity = {
    ...splitName(generated),
    nameOrigin: "generated",
    groupOrigin: "generated",
  };
  const sessionName = normalizeName(options.sessionName);
  if (sessionName) {
    identity = { ...splitName(sessionName), nameOrigin: "user", groupOrigin: "user" };
  }
  for (const value of options.entries) {
    identity = savedIdentity(value) ?? identity;
  }
  const override = normalizeName(options.cliName) ?? normalizeName(options.envName);
  return override ? applyUserIdentity(identity, override) : identity;
}
