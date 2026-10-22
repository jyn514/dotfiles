/** Preferred identity only: hub collision suffixes and connection state live elsewhere. */
export type IdentityOrigin = "generated" | "agent" | "user";

export type LinkIdentity = {
  name: string;
  group: string;
  nameOrigin: IdentityOrigin;
  groupOrigin: IdentityOrigin;
  /** Retain an explicit separator even with an empty group (reader@ != reader). */
  explicitGroup?: boolean;
};

/** Historical caller normalization applies to the combined name, not its parts. */
export function normalizeName(name: string | undefined | null): string | undefined {
  const n = name?.trim().replace(/\s+/g, " ");
  return n ? n : undefined;
}

/** Everything after the FIRST @ is group text, including subsequent @ characters. */
export function groupOf(fullName: string): string {
  const at = fullName.indexOf("@");
  return at === -1 ? "" : fullName.slice(at + 1);
}

export function fullName(identity: LinkIdentity): string {
  return identity.group || identity.explicitGroup
    ? `${identity.name}@${identity.group}`
    : identity.name;
}

function splitName(combined: string): Pick<LinkIdentity, "name" | "group" | "explicitGroup"> {
  const at = combined.indexOf("@");
  return {
    name: at === -1 ? combined : combined.slice(0, at),
    group: groupOf(combined),
    // Nonempty groups already imply the separator. Only the empty suffix needs
    // extra spelling state; ownership remains a separate, independent concern.
    ...(at === combined.length - 1 ? { explicitGroup: true } : {}),
  };
}

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

// Session entries are an external persisted boundary. Narrow unknown data here
// instead of asserting that arbitrary Pi custom entries have identity-shaped data.
type NamingEntry =
  | { customType: "link-identity"; data: LinkIdentity }
  | { customType: "link-name"; data: { name: string } };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function origin(value: unknown): value is IdentityOrigin {
  return value === "generated" || value === "agent" || value === "user";
}

function namingEntry(value: unknown): NamingEntry | undefined {
  if (!record(value) || value.type !== "custom" || !record(value.data)) return;
  const data = value.data;
  if (value.customType === "link-name" && typeof data.name === "string") {
    const name = normalizeName(data.name);
    if (name) return { customType: "link-name", data: { name } };
  }
  if (
    value.customType === "link-identity" &&
    typeof data.name === "string" && !data.name.includes("@") &&
    typeof data.group === "string" &&
    (data.explicitGroup === undefined || typeof data.explicitGroup === "boolean") &&
    origin(data.nameOrigin) && origin(data.groupOrigin)
  ) {
    return {
      customType: "link-identity",
      data: {
        name: data.name,
        group: data.group,
        nameOrigin: data.nameOrigin,
        groupOrigin: data.groupOrigin,
        ...(typeof data.explicitGroup === "boolean" ? { explicitGroup: data.explicitGroup } : {}),
      },
    };
  }
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
    const entry = namingEntry(value);
    if (!entry) continue;
    identity = entry.customType === "link-identity"
      ? entry.data
      : { ...splitName(entry.data.name), nameOrigin: "user", groupOrigin: "user" };
  }
  const override = normalizeName(options.cliName) ?? normalizeName(options.envName);
  return override ? applyUserIdentity(identity, override) : identity;
}
