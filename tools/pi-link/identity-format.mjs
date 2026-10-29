/** @typedef {"generated" | "agent" | "user"} IdentityOrigin */
/**
 * Preferred identity only: hub collision suffixes and connection state live elsewhere.
 * @typedef {object} LinkIdentity
 * @property {string} name
 * @property {string} group
 * @property {IdentityOrigin} nameOrigin
 * @property {IdentityOrigin} groupOrigin
 * @property {boolean} [explicitGroup] Retain an explicit empty suffix (reader@ != reader).
 */

/** Historical caller normalization applies to the combined name, not its parts.
 * @param {string | undefined | null} name
 * @returns {string | undefined}
 */
export function normalizeName(name) {
  const n = name?.trim().replace(/\s+/g, " ");
  return n ? n : undefined;
}

/** Everything after the FIRST @ is group text, including subsequent @ characters.
 * @param {string} fullName
 */
export function groupOf(fullName) {
  const at = fullName.indexOf("@");
  return at === -1 ? "" : fullName.slice(at + 1);
}

/** @param {LinkIdentity} identity */
export function fullName(identity) {
  return identity.group || identity.explicitGroup
    ? `${identity.name}@${identity.group}`
    : identity.name;
}

/** @param {string} combined
 * @returns {Pick<LinkIdentity, "name" | "group" | "explicitGroup">}
 */
export function splitName(combined) {
  const at = combined.indexOf("@");
  return {
    name: at === -1 ? combined : combined.slice(0, at),
    group: groupOf(combined),
    // Nonempty groups already imply the separator. Only the empty suffix needs
    // extra spelling state; ownership remains a separate, independent concern.
    ...(at === combined.length - 1 ? { explicitGroup: true } : {}),
  };
}

/** @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function record(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param {unknown} value
 * @returns {value is IdentityOrigin}
 */
function origin(value) {
  return value === "generated" || value === "agent" || value === "user";
}

/**
 * Decode one saved naming entry for both extension startup and CLI discovery.
 * Callers apply valid entries in file order; malformed entries never replace a
 * previous identity. Legacy values have unknown provenance, so remain protected.
 * @param {unknown} value
 * @returns {LinkIdentity | undefined}
 */
export function savedIdentity(value) {
  if (!record(value) || value.type !== "custom" || !record(value.data)) return;
  const data = value.data;
  if (value.customType === "link-name" && typeof data.name === "string") {
    const name = normalizeName(data.name);
    if (name) return { ...splitName(name), nameOrigin: "user", groupOrigin: "user" };
  }
  if (
    value.customType === "link-identity" &&
    typeof data.name === "string" && !data.name.includes("@") &&
    typeof data.group === "string" &&
    (data.explicitGroup === undefined || typeof data.explicitGroup === "boolean") &&
    origin(data.nameOrigin) && origin(data.groupOrigin)
  ) {
    return {
      name: data.name,
      group: data.group,
      nameOrigin: data.nameOrigin,
      groupOrigin: data.groupOrigin,
      ...(typeof data.explicitGroup === "boolean" ? { explicitGroup: data.explicitGroup } : {}),
    };
  }
}
