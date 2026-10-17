# Pi loader checks

Read this reference when a discovery change requires a Pi loader check, or when investigating Pi skill loading.

Prefer `validate_skill` when available.
Confirm the expected name loaded and inspect all diagnostics.
This checks the explicit file, not normal discovery precedence or interactive startup.
Otherwise, check the installed CLI options and load the skill from a discoverable location in a normal Pi session;
inspect startup diagnostics and `/skill:<name>`.
Run `/reload` after edits in an active session.
If that session is unavailable, report the missing check.

## Programmatic normal-discovery check

Use `DefaultResourceLoader`, not `loadSkills`, to check normal startup discovery.
The resource loader finds locations such as `~/.agents/skills`; the lower-level `loadSkills` function does not discover those locations itself.
Check the installed Pi API before adapting this example.
The example isolates directory discovery, with configured packages and unrelated resources disabled.

Prepare a disposable HOME with the proposed skill installed under `.agents/skills`, matching its intended layout or symlinks.
Set `PI_PACKAGE_DIR` to the installed Pi package directory, not an older unit-test dependency.
Save this as `check-discovery.mjs` and run `node check-discovery.mjs <expected-skill-name>` inside that isolated environment:

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const expectedName = process.argv[2];
assert.ok(expectedName, "Pass the expected skill name");
const packageDir = process.env.PI_PACKAGE_DIR;
assert.ok(packageDir, "Set PI_PACKAGE_DIR to the installed Pi package");
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const { DefaultResourceLoader, SettingsManager } = await import(pathToFileURL(
  resolve(packageDir, manifest.exports["."].import)).href);
const loader = new DefaultResourceLoader({
  cwd: process.cwd(),
  agentDir: join(homedir(), ".pi/agent"),
  settingsManager: SettingsManager.inMemory({ packages: [] }),
  noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
});
await loader.reload();
const { skills, diagnostics } = loader.getSkills();
assert.deepEqual(diagnostics, []);
const matches = skills.filter(skill => skill.name === expectedName);
assert.equal(matches.length, 1, "Expected one normally discovered skill");
assert.equal(matches[0].disableModelInvocation, false);
console.log(JSON.stringify(matches[0], null, 2));
```

Do not pass `additionalSkillPaths` or override the skill list: that would bypass the discovery being checked.
This checks discovery and automatic-selection eligibility, not whether the model follows the skill or an existing session has reloaded it.
