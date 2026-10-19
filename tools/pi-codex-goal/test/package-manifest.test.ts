import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function frontmatter(prompt: string): Record<string, string> {
  const match = /^---\n(?<body>[\s\S]*?)\n---\n/.exec(prompt);
  assert.ok(match?.groups?.body, "prompt has frontmatter");

  return Object.fromEntries(
    match.groups.body.split("\n").map((line) => {
      const separator = line.indexOf(":");
      assert.notEqual(separator, -1, `frontmatter line has key/value: ${line}`);
      return [line.slice(0, separator), line.slice(separator + 1).trim()];
    }),
  );
}

test("package ships the TypeScript extension source plus create-goal prompt entrypoints", () => {
  const packageJson = JSON.parse(readFileSync("package.json", "utf8")) as {
    files?: string[];
    pi?: { extensions?: string[]; prompts?: string[] };
  };

  assert.deepEqual(packageJson.pi?.extensions, ["./extensions"]);
  assert.ok(packageJson.files?.includes("extensions"));
  assert.ok(packageJson.files?.includes("src"));
  assert.ok(packageJson.files?.includes("prompts"));
  assert.ok(packageJson.pi?.prompts?.includes("./prompts"));
});

test("create-goal prompt preserves task scope, evidence, replacement and budget contracts", () => {
  const prompt = readFileSync("prompts/create-goal.md", "utf8").replace(/\r\n/g, "\n");
  const metadata = frontmatter(prompt);

  assert.equal(metadata.description, "Convert a plain task into a strict evidence-based pi-codex goal and create it");
  assert.equal(metadata["argument-hint"], '"<task>"');
  assert.match(prompt, /Turn the user task into exactly one durable pi-codex-goal objective/);
  assert.match(prompt, /pass `replace_existing: true`/);
  assert.match(prompt, /Do not set a token budget limit unless the user explicitly provides a budget\/limit/);
  assert.match(prompt, /Outcome: what must be true when complete/);
  assert.match(prompt, /Verification evidence: the concrete checks or artifacts/);
  assert.match(prompt, /Task-specific constraints: preserve the user's permissions, protected behavior and files, acceptance boundaries/);
  assert.match(prompt, /Preserve existing behavior unless the task changes it, and do not discard user changes/);
  assert.match(prompt, /every explicit requirement must have concrete verification evidence and no required work may remain/);
  assert.match(prompt, /Do not add requirements or narrow scope without user approval/);
  assert.match(prompt, /call `update_goal` with status `blocked` and a dependency reason/);
  assert.match(prompt, /Do not block while useful work remains/);
  assert.match(prompt, /Only explicit `\/goal resume` reactivates a blocked goal; ordinary input does not/);
  assert.match(prompt, /Never complete a blocked goal/);
});

test("create-goal routes every active goal without changing its objective or permissions", () => {
  const prompt = readFileSync("prompts/create-goal.md", "utf8");
  assert.match(prompt, /Keep standing workflow instructions out of the saved objective/);
  assert.match(prompt, /After creating an active goal, read the `autonomous-work` skill file at its advertised path, if available, when work starts or resumes/);
  assert.match(prompt, /work selection, iteration, recovery, and activity-specific verification/);
  assert.match(prompt, /does not expand the task's authorized activity or effects/);
  assert.match(prompt, /Research and review do not authorize fixes, planning does not authorize execution, and drafting does not authorize publication/);
  assert.match(prompt, /An unavailable optional skill is not a blocker/);
  assert.doesNotMatch(prompt, /autonomous-implementation|Do not activate that skill for plan-only|\/skill:autonomous-work/);
  assert.doesNotMatch(prompt, /Iteration policy/);
  assert.doesNotMatch(prompt, /Do not leave unapproved shortcuts/);
  assert.doesNotMatch(prompt, /Phrases like "for the scope this is complete"/);
});
