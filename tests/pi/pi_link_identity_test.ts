import { describe, expect, test } from "bun:test";
import {
  applyAgentIdentity,
  applyUserIdentity,
  fullName,
  groupOf,
  initialIdentity,
  normalizeName,
  type IdentityOrigin,
  type LinkIdentity,
} from "../../tools/pi-link/identity";

const fresh = (): LinkIdentity => initialIdentity({ generatedName: "t-a1b2", entries: [] });
const saved = (identity: LinkIdentity) => ({ type: "custom", customType: "link-identity", data: identity });
const legacy = (name: string) => ({ type: "custom", customType: "link-name", data: { name } });
const chosen: LinkIdentity = { name: "reviewer", group: "prose", nameOrigin: "agent", groupOrigin: "agent" };

function accepted(current: LinkIdentity, update: { name?: string; group?: string }): LinkIdentity {
  const result = applyAgentIdentity(current, update);
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error(result.error);
  return result.identity;
}

describe("identity startup precedence and persisted boundary", () => {
  // Adjacent rows remove only the highest-precedence source. This catches a
  // source reorder without binding callers to particular generated spellings.
  const cases = [
    { cliName: " cli@c ", envName: "env@e", entries: [saved(chosen)], sessionName: "session@s", expected: "cli@c", origins: ["user", "user"] },
    { envName: " env@e ", entries: [saved(chosen)], sessionName: "session@s", expected: "env@e", origins: ["user", "user"] },
    { entries: [saved(chosen)], sessionName: "session@s", expected: "reviewer@prose", origins: ["agent", "agent"] },
    { entries: [], sessionName: " session@s ", expected: "session@s", origins: ["user", "user"] },
    { entries: [], expected: "other-default", origins: ["generated", "generated"] },
  ];
  for (const [index, row] of cases.entries()) {
    test(`precedence row ${index}`, () => {
      const identity = initialIdentity({ generatedName: "other-default", ...row });
      expect(fullName(identity)).toBe(row.expected);
      expect([identity.nameOrigin, identity.groupOrigin]).toEqual(row.origins);
    });
  }

  test("blank overrides fall through using historical Unicode whitespace normalization", () => {
    expect(initialIdentity({ generatedName: "random", cliName: "\t \n", envName: "\u2003", entries: [legacy(" older\n name@a@b ")] })).toEqual({
      name: "older name", group: "a@b", nameOrigin: "user", groupOrigin: "user",
    });
  });

  test("legacy and new entries participate in the same last-write-wins order", () => {
    const options = { generatedName: "random", sessionName: "fallback" };
    expect(initialIdentity({ ...options, entries: [legacy("old@one"), saved(chosen)] })).toEqual(chosen);
    expect(initialIdentity({ ...options, entries: [saved(chosen), legacy("last")] })).toEqual({
      name: "last", group: "", nameOrigin: "user", groupOrigin: "user",
    });
  });

  test("unrelated and malformed entries cannot supply values or origins", () => {
    const unknown: unknown[] = [null, undefined, 3, "entry", [], {},
      { customType: "link-name", data: { name: "missing-type" } },
      { type: "message", customType: "link-name", data: { name: "message" } },
      { type: "custom", customType: "other", data: chosen },
      { type: "custom", customType: "link-name", data: { name: 42 } },
      legacy(" \n"),
      { type: "custom", customType: "link-identity", data: { ...chosen, groupOrigin: "unknown" } },
      { type: "custom", customType: "link-identity", data: { ...chosen, name: "injected@group" } },
      { type: "custom", customType: "link-identity", data: null },
    ];
    expect(initialIdentity({ generatedName: "t-a1b2", entries: unknown })).toEqual(fresh());
    expect(initialIdentity({ generatedName: "random", entries: [saved(chosen), ...unknown] })).toEqual(chosen);
  });

  test("explicit empty group spelling and protection both survive persistence", () => {
    const identity = applyUserIdentity(fresh(), "reader@");
    expect(fullName(identity)).toBe("reader@");
    expect(initialIdentity({ generatedName: "random", entries: [saved(identity)] })).toEqual(identity);
    expect(applyAgentIdentity(identity, { group: "prose" })).toMatchObject({ ok: false, protectedFields: ["group"] });
  });

  test("a plain startup override clears a saved group and protects the clearing", () => {
    expect(initialIdentity({ generatedName: "random", entries: [saved(chosen)], cliName: "reader" })).toEqual({
      name: "reader", group: "", nameOrigin: "user", groupOrigin: "user",
    });
    expect(initialIdentity({ generatedName: "random", entries: [], cliName: "reader" }).groupOrigin).toBe("generated");
  });

  test("generated-looking user names have no spelling-based exemption", () => {
    for (const options of [{ cliName: "t-a1b2" }, { envName: "t-a1b2" }, { sessionName: "t-a1b2" }, { entries: [legacy("t-a1b2")] }]) {
      const identity = initialIdentity({ generatedName: "t-a1b2", entries: [], ...options });
      expect(applyAgentIdentity(identity, { name: "reviewer" })).toMatchObject({ ok: false, protectedFields: ["name"] });
    }
    expect(accepted(fresh(), { name: "reviewer" }).nameOrigin).toBe("agent");
  });
});

describe("manual ownership", () => {
  test("same-value manual assignments claim explicit fields, repeatedly", () => {
    const localOnly = applyUserIdentity(fresh(), "t-a1b2");
    expect(localOnly).toEqual({ ...fresh(), nameOrigin: "user" });
    expect(applyUserIdentity(localOnly, "t-a1b2")).toEqual(localOnly);
    expect(applyUserIdentity(chosen, "reviewer@prose")).toEqual({ ...chosen, nameOrigin: "user", groupOrigin: "user" });
    expect(applyUserIdentity(localOnly, "t-a1b2@").groupOrigin).toBe("user");
  });

  test("plain names clear nonempty groups but do not newly claim an already empty group", () => {
    expect(applyUserIdentity(chosen, "reader")).toEqual({ name: "reader", group: "", nameOrigin: "user", groupOrigin: "user" });
    for (const groupOrigin of ["generated", "agent", "user"] as const) {
      const current = { ...fresh(), groupOrigin };
      expect(applyUserIdentity(current, "reader").groupOrigin).toBe(groupOrigin);
    }
  });

  test("manual combined normalization preserves boundary spaces and all first-@ suffix text", () => {
    for (const [input, name, group] of [
      [" \u2003Zoë\n 翼 @ prose\t@team  ", "Zoë 翼 ", " prose @team"],
      ["@group", "", "group"],
      ["all", "all", ""],
      ["*", "*", ""],
      ["a@@", "a", "@"],
    ]) {
      expect(applyUserIdentity(fresh(), input)).toMatchObject({ name, group });
    }
    expect(() => applyUserIdentity(fresh(), " \t ")).toThrow();
  });
});

describe("agent field updates", () => {
  test("partial updates retain omitted values and independent ownership", () => {
    const userName = applyUserIdentity(fresh(), "reader");
    expect(accepted(userName, { group: " \u2003prose\t team@inner \n" })).toEqual({
      name: "reader", group: "prose team@inner", nameOrigin: "user", groupOrigin: "agent",
    });
    const userGroup = { ...chosen, groupOrigin: "user" as const };
    expect(accepted(userGroup, { name: "writer" })).toEqual({ ...userGroup, name: "writer", nameOrigin: "agent" });
    expect(accepted(chosen, { group: " \u2003 " })).toEqual({ ...chosen, group: "" });
  });

  test("no field, empty local name, and @ injection are rejected without mutation", () => {
    for (const update of [{}, { name: undefined }, { name: "" }, { name: "\t\n" }, { name: "local@group" }, { name: "@" }]) {
      const current = Object.freeze({ ...chosen });
      expect(applyAgentIdentity(current, update).ok).toBe(false);
      expect(current).toEqual(chosen);
    }
  });

  test("unchanged normalized user fields are no-ops, not agent ownership claims", () => {
    const current = { ...chosen, nameOrigin: "user" as const, groupOrigin: "user" as const };
    expect(accepted(current, { name: " reviewer ", group: "\tprose\n" })).toEqual(current);
    expect(accepted({ ...current, groupOrigin: "generated" }, { name: "reviewer", group: "new" })).toEqual({
      ...current, group: "new", groupOrigin: "agent",
    });
  });

  // Bounded exhaustive decision table: ownership is independent per field;
  // changed/same/omitted requests must be checked before committing either field.
  test("all ownership and partial-update combinations enforce atomic protection", () => {
    const origins: IdentityOrigin[] = ["generated", "agent", "user"];
    let cases = 0;
    let refused = 0;
    for (const nameOrigin of origins) for (const groupOrigin of origins) {
      for (const name of [undefined, "reader", "writer"]) for (const group of [undefined, "prose", "other"]) {
        if (name === undefined && group === undefined) continue;
        const current = Object.freeze({ name: "reader", group: "prose", nameOrigin, groupOrigin });
        const protectedFields: string[] = [];
        if (name === "writer" && nameOrigin === "user") protectedFields.push("name");
        if (group === "other" && groupOrigin === "user") protectedFields.push("group");
        const result = applyAgentIdentity(current, { name, group });
        if (protectedFields.length) {
          expect(result).toMatchObject({ ok: false, protectedFields });
          refused++;
        } else {
          expect(result).toEqual({ ok: true, identity: {
            name: name ?? "reader", group: group ?? "prose",
            nameOrigin: name === "writer" ? "agent" : nameOrigin,
            groupOrigin: group === "other" ? "agent" : groupOrigin,
          } });
        }
        expect(current).toEqual({ name: "reader", group: "prose", nameOrigin, groupOrigin });
        cases++;
      }
    }
    expect(cases).toBe(72);
    expect(refused).toBe(17);
  });
});

describe("explicit empty group spelling compatibility", () => {
  test("all combined startup sources and both persisted formats retain reader@ and lone @", () => {
    for (const combined of ["reader@", "@"]) {
      const expected = { name: combined === "@" ? "" : "reader", group: "", explicitGroup: true };
      for (const source of [
        { generatedName: combined },
        { cliName: combined },
        { envName: combined },
        { sessionName: combined },
        { entries: [legacy(combined)] },
      ]) {
        const identity = initialIdentity({ generatedName: "random", entries: [], ...source });
        expect(identity).toMatchObject(expected);
        expect(fullName(identity)).toBe(combined);
        const restored = initialIdentity({ generatedName: "different", entries: [saved(identity)] });
        expect(restored).toEqual(identity);
        expect(fullName(restored)).toBe(combined);
      }
    }
  });

  test("reader and reader@ remain distinct terminal names in the same empty group", () => {
    const plain = applyUserIdentity(fresh(), "reader");
    const explicit = applyUserIdentity(fresh(), "reader@");
    expect(new Set([fullName(plain), fullName(explicit)]).size).toBe(2);
    expect(groupOf(fullName(plain))).toBe("");
    expect(groupOf(fullName(explicit))).toBe("");
    const cleared = applyUserIdentity(explicit, "reader");
    expect(fullName(cleared)).toBe("reader");
    expect(cleared.groupOrigin).toBe("user");
    expect(applyUserIdentity(cleared, "reader@")).toEqual(explicit);
  });

  test("omitted or unchanged agent group updates preserve spelling, actual changes may clear it", () => {
    const explicit = initialIdentity({ generatedName: "reader@", entries: [] });
    expect(fullName(accepted(explicit, { name: "writer" }))).toBe("writer@");
    expect(accepted(explicit, { group: " \n\t" })).toEqual(explicit);
    const grouped = accepted(explicit, { group: "prose" });
    expect(fullName(grouped)).toBe("reader@prose");
    expect(fullName(accepted(grouped, { group: "" }))).toBe("reader");
    const protectedIdentity = applyUserIdentity(fresh(), "reader@");
    expect(accepted(protectedIdentity, { group: "" })).toEqual(protectedIdentity);
    expect(applyAgentIdentity(protectedIdentity, { group: "prose" })).toMatchObject({ ok: false, protectedFields: ["group"] });
  });

  test("new entries validate optional separator state without requiring it in older entries", () => {
    const plain = { ...chosen, group: "" };
    expect(fullName(initialIdentity({ generatedName: "random", entries: [saved(plain)] }))).toBe("reviewer");
    const explicit = { ...plain, explicitGroup: true };
    expect(fullName(initialIdentity({ generatedName: "random", entries: [saved(explicit)] }))).toBe("reviewer@");
    expect(initialIdentity({ generatedName: "random", entries: [saved(explicit), {
      type: "custom", customType: "link-identity", data: { ...plain, explicitGroup: "true" },
    }] })).toEqual(explicit);
  });
});

test("bounded combined-name roundtrips preserve historical Unicode and multi-@ groups", () => {
  // Deterministic Cartesian generation needs no seed or filtering. Expectations
  // are authored components, not another copy of the parser's splitting logic.
  const names = ["reader", "t-1234", "Zoë 翼", "*", "all", "a-b_./:"];
  const groups = ["", "prose", "a@b", "@", "équipe 翼"];
  let cases = 0;
  for (const name of names) for (const group of groups) for (const explicitEmpty of group ? [false] : [false, true]) {
    const combined = group || explicitEmpty ? `${name}@${group}` : name;
    const identity = applyUserIdentity(fresh(), `\u2003${combined}\n`);
    expect(identity.name).toBe(name);
    expect(identity.group).toBe(group);
    expect(fullName(identity)).toBe(combined);
    expect(groupOf(combined)).toBe(group);
    expect(normalizeName(`\t${combined}\n`)).toBe(combined);
    expect(initialIdentity({ generatedName: "random", entries: [saved(identity)] })).toEqual(identity);
    cases++;
  }
  expect(cases).toBe(36);
  expect(normalizeName(null)).toBeUndefined();
  expect(normalizeName(undefined)).toBeUndefined();
  expect(normalizeName("\u2003\n\t")).toBeUndefined();
  expect(normalizeName(" \tZoë\n\u2003翼  ")).toBe("Zoë 翼");
});
