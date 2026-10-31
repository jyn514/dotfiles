# Agent skills

This collection covers software design, testing, writing, and coordinating work among coding agents.
Choose a section by the work you need:

- [Test code and assess tests](#test-code-and-assess-tests): write properties and generators, review existing tests, or check whether tests detect plausible implementation mistakes.
- [Design and plan changes](#design-and-plan-changes): question the task's framing, compare designs, select improvements, or plan a chosen change.
- [Write and revise](#write-and-revise): develop an explanation, polish prose, write documentation, or reorganize existing docs.
- [Coordinate, review, and finish work](#coordinate-review-and-finish-work): divide work among agents, turn goals into tickets, review results, and close out a session.
- [Specialized work](#specialized-work): investigate performance and crashes, review dependencies, work with Jujutsu history, and use project-specific tools.

See [Install and use](#install-and-use) for setup and invocation.

## Test code and assess tests

[Property-based testing](property-based-testing/SKILL.md) helps write and review tests across a domain of inputs.
Use it for parsers, serializers, validators, data structures, and other behavior where a few chosen examples leave important cases out.
It covers choosing properties, generating valid inputs, and interpreting a reduced failing case.
For existing tests, it asks whether the generator reaches the relevant cases and whether the assertions check the intended behavior.

[Mutation testing](mutation-testing/SKILL.md) asks a different question: would the tests notice a plausible implementation mistake?
It guides deliberate, bounded changes to the implementation and checks whether the intended tests fail.
A surviving change can reveal a test gap, leave behavior unchanged, or remain inconclusive; those results need different explanations.
Use it when test sensitivity is in question, not as an automatic extra step after every bug fix.

Neither skill requires replacing the project's test framework.
For both, provide the behavior the tests should protect and the implementation or tests to examine.
Say whether you want an assessment, new tests, or implementation changes.

## Design and plan changes

[Architecture design](architecture-design/SKILL.md) starts with the existing implementation and the change you need.
It traces a real caller through the code, identifies who owns the behavior, and compares the smallest sufficient change with alternatives.
Use it to critique a proposed architecture or abstraction, choose an API or subsystem boundary, or decide whether a refactor is worth doing.

[Creative inquiry](creative-inquiry/SKILL.md) questions the framing of the task itself.
Use it when exploring possibilities, examining assumptions, or asking whether the current approach solves the right problem.
[Work selection](work-selection/SKILL.md) makes a more immediate comparison: whether another investigation, workaround, or prerequisite
is a better next action than a smaller way to reach the requested outcome.

Once a change is selected, [implementation planning](implementation-plan/SKILL.md) turns it into a repository-specific plan
with affected files, tests, and logical commits.
An architecture assessment does not automatically call for a plan, and a request for a plan does not authorize implementation.

If you have not selected an improvement, [opportunity scan](opportunity-scan/SKILL.md) compares opportunities across the project.
For an area already selected for cleanup, [cleanup triage](cleanup-triage/SKILL.md) prioritizes concrete work.
[Pain axis](pain-axis/SKILL.md) examines recurring problems in history, issues, and tests before redesigning a failure-prone subsystem.

For a new independently invoked tool or service, [new-tool development](new-tool-development/SKILL.md) coordinates the stages
from a human-authored product brief through requirements and implementation handoff.
[Requirements definition](requirements-definition/SKILL.md) drafts requirements from an approved brief.
These are for developing a new tool, not prerequisites for every feature or script.

## Write and revise

[Holistic writing](holistic-writing/SKILL.md) works on the whole artifact: what it explains, how the explanation develops,
and whether the prose is worth following.
Use it for reports, essays, instructions, prompts, and substantial revisions.
[Tighten prose](tighten-prose/SKILL.md) is for local wording, rhythm, repetition, and clarity when the surrounding explanation already works.

[README writing](readme-writing/SKILL.md) introduces a project to someone deciding whether or how to use it.
For tutorials, how-to guides, references, and explanations, consult the [documentation checks](holistic-writing/references/documentation.md)
for prerequisites, warnings, and the routes readers need to complete a task.
[Reorganize docs](reorganize-docs/SKILL.md) changes the arrangement of existing documentation: splits, consolidation, navigation, and archives.
Choose by what needs changing; documentation checks are a reference, not another writing workflow.

For an upstream bug report, support question, or design discussion, use [issue reporting](issue-reporting/SKILL.md).
For creating or evaluating a skill's behavior, triggers, and procedures, use [skill authoring](skill-authoring/SKILL.md).

Provide the draft, its intended readers, and what they need to understand or do.
For factual or technical prose, include the source material the agent must preserve.

## Coordinate, review, and finish work

[Delegation](delegation/SKILL.md) helps divide work among agents, give each a usable assignment, and integrate the results.
[Autonomous work](autonomous-work/SKILL.md) guides an explicitly authorized unattended run or active tracked goal.
It keeps the requested outcome, permissions, evidence, and remaining work available as the run continues.
It does not turn an ordinary request into an autonomous run.

- [goal-to-issue-graph](goal-to-issue-graph/SKILL.md) — turn a brief goal into bounded tickets, justified dependencies and observable whole-goal acceptance.
  Distinguish successful outcomes from diagnosed holds, and a ready plan from a completed product.
  The goal can be selected while architecture or input facts remain unresolved.

[Specification review](spec-review/SKILL.md) audits a specification's contract for consistency, requirement traceability, unsupported restrictions, and stage-appropriate completeness.
[Specification/implementation audit](audit-spec-against-impl/SKILL.md) finds disagreements between the specification, implementation, and tests.
[Completion audit](completion-audit/SKILL.md) checks completed substantial owned work against the requested outcome and acceptance conditions.
They share [evidence standards](references/review-evidence.md), not a mandatory sequence of reviews.
For a small, localized edit, a diff review and the appropriate native check can be enough.
A review request does not authorize repairs.

[Human review packets](human-review-packets/SKILL.md) explain a decision's concrete consequences for the person making it.
[Commit quality](commit-quality/SKILL.md) groups changes into coherent commits and explains their purpose.
[Session closeout](session-closeout/SKILL.md) checks the whole session for unfinished requirements, owned changes, and useful follow-ups
before committing the session's work and ending it.

## Specialized work

| Task | Skill |
| --- | --- |
| Create, edit, or review Dockerfiles and Docker Bake builds | [Dockerfiles](dockerfiles/SKILL.md) |
| Review a proposed dependency addition or update | [Dependency review](dependency-review/SKILL.md) |
| Investigate slow execution or benchmark a change | [Performance investigation](performance-investigation/SKILL.md) |
| Diagnose native-process crashes, hangs, or missing symbols | [Process debugging](process-debugging/SKILL.md) |
| Inspect or reshape Jujutsu history | [JJ workflow](jj-workflow/SKILL.md) |
| Compose Jujutsu conflict snapshots semantically | [JJ conflict resolution](jj-conflict-resolution/SKILL.md) |
| Enforce an established rule while reducing existing violations | [Ratchet](ratchet/SKILL.md) |
| Work with TicGit tickets | [TicGit](ticgit/SKILL.md) |
| Read Rust Zulip discussions | [Zulip API](zulip-api/SKILL.md) |
| Find and test Rust compiler diagnostic gaps | [Rustc diagnostic gap tests](rustc-diagnostic-gap-tests/SKILL.md) |
| Write Typst markup or diagrams | [Typst](typst/SKILL.md), [Typst diagrams](typst-diagrams/SKILL.md) |
| Review and rename past Pi sessions | [Session title curation](session-title-curation/SKILL.md) |

## Install and use

### Pi

```sh
pi install git:github.com/jyn514/dotfiles
```

Ask for a task normally, or load a skill explicitly with `/skill:name` and put your request after it:

```text
/skill:holistic-writing revise the introduction in README.md
```

An explicit invocation loads the instructions rather than relying on the model to select them.

### Claude Code

```sh
claude plugin marketplace add jyn514/dotfiles
claude plugin install judgement-yields-navigation@jyn-plugins
```

### Codex

Once the npm package is published, install it through this repository's Codex marketplace:

```sh
codex plugin marketplace add jyn514/dotfiles
codex plugin add judgement-yields-navigation@jyn-plugins
```

The `@jyn-plugins` suffix names the marketplace, not an npm scope.

### Other clients and manual installation

Copy or symlink the desired directories from `skills/` into your client's skill directory.
Clients using the shared Agent Skills locations can load them from `~/.agents/skills/` or `.agents/skills/`.
This repository's `./setup dotfiles` command links the complete directory to `~/.agents/skills/`.

When copying individual skills, keep their linked shared references, required companion skills, and bundled license notices.
For example, `autonomous-work` also uses `work-selection` and `goal-to-issue-graph`.
The `references/` directory supplies guidance used by skills and shared instructions; it is not a collection of additional skills.

## Maintenance

### Updating an installation

Reload Pi or start a new client session to refresh the skill catalog after updating it.
The former `review` entry point is split into [spec-review](spec-review/SKILL.md),
[audit-spec-against-impl](audit-spec-against-impl/SKILL.md), and [completion-audit](completion-audit/SKILL.md).
The former `double-check` task belongs to completion-audit.
The former `technical-docs` skill is now a [documentation reference](holistic-writing/references/documentation.md) within holistic-writing.
Whole-artifact work formerly called `tighten-docs` belongs to [holistic writing](holistic-writing/SKILL.md);
local polishing belongs to [tighten prose](tighten-prose/SKILL.md).

Some former design skills are now on-demand references within [architecture design](architecture-design/SKILL.md)
or the shared [change guidelines](references/change-with-evidence.md).
The alternatives and independent-deliberation helpers under `architecture-design/references/` are supporting material,
not standalone skills or slash commands.

### Publishing a release

`dev/publish-skills` stages this file as the npm package's root README without changing the repository root README.
The Codex marketplace pins the npm version in `.agents/plugins/marketplace.json`.
Publish that version before pushing the marketplace change.

1. Set the same new semantic version in `package.json`, `.codex-plugin/plugin.json`, and `.agents/plugins/marketplace.json` (`source.version`).
2. Validate the metadata and actual npm archive without publishing:

   ```sh
   dev/test-environment python3 tests/setup/agent_skills_package_test.py
   dev/test-environment dev/publish-skills --check
   ```

   `--check` packs offline with lifecycle scripts disabled, checks the staged files, and removes the temporary package and archive.
   It does not check registry permissions and accepts no publication arguments.
   `--dry-run` is npm's publication dry-run, not the packaging-only check.

3. Review and commit the release, then authenticate and publish:

   ```sh
   npm login
   npm whoami
   dev/publish-skills --access public
   ```

4. Verify the published version before pushing the release commit:

   ```sh
   npm view judgement-yields-navigation version
   ```

5. Test a clean installation and start a new Codex thread so it loads the skills:

   ```sh
   codex plugin marketplace add jyn514/dotfiles
   codex plugin add judgement-yields-navigation@jyn-plugins
   ```

### Attribution and licenses

Repository-owned skills are under Unlicense.
[Property-based testing](property-based-testing/README.md) and [mutation testing](mutation-testing/README.md)
are adapted from Trail of Bits under CC-BY-SA-4.0.
The property-based testing skill also incorporates MIT-licensed Hegel review guidance.
Keep their attribution notices and bundled license files when copying them.

[Creative inquiry](creative-inquiry/SKILL.md) is imported from
[`nia-e/rustc-project-skills`](https://github.com/nia-e/rustc-project-skills/tree/0fe6e4d11a99b8c62776048d13f59a4e5e4ff6ca/creative-inquiry),
with a locally adapted trigger and software-design references.
