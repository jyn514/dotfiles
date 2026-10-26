# Agent skills

These skills follow the Agent Skills directory format and are intentionally small and composable. Use them manually at first; automate only the sequences you actually repeat.

## Install

Install the repository through a supported harness, or copy an individual directory from `skills/` into that harness's skill directory.

### Pi

```sh
pi install git:github.com/jyn514/dotfiles
```

### Claude Code

```sh
claude plugin marketplace add jyn514/dotfiles
claude plugin install judgement-yields-navigation@jyn-plugins
```

### Codex

Once published, install the npm package through this repository's Codex marketplace:

```sh
codex plugin marketplace add jyn514/dotfiles
codex plugin add judgement-yields-navigation@jyn-plugins
```

In `plugin@marketplace`, the suffix names the Codex marketplace; it is not an npm scope.

### Other Agent Skills clients

Copy or symlink the desired skill directories into the client's user or project skill directory. For clients that use the shared convention, install them under `~/.agents/skills/` or `.agents/skills/`.

This repository's `./setup dotfiles` command links the complete `skills/` directory to `~/.agents/skills/`.

`references/` contains shared on-demand guidance, not registered skills.
[Change with evidence](references/change-with-evidence.md) supplies code, configuration,
and test standards when the shared agent instructions request it. Plain reference
files add no startup skill descriptions. The sandbox's existing live skills mount
makes reference changes readable without restarting its worker.

`property-based-testing` is adapted from Trail of Bits with additional Hegel review
checks. Its [attribution and license notice](property-based-testing/README.md)
identifies the CC-BY-SA-4.0 material and MIT contribution; repository-owned skills
remain under Unlicense. Keep the bundled license files when copying this skill.

`mutation-testing` is also adapted from Trail of Bits under CC-BY-SA-4.0. Its
[attribution notice](mutation-testing/README.md) identifies the source and changes;
keep its notice and license when copying the skill.

## Publish a release

The Codex marketplace pins the npm version in `.agents/plugins/marketplace.json`. Publish that version before pushing the marketplace change. `dev/publish-skills` stages this file as the package-root `README.md` without changing the repository root README.

For packaging-only validation, run `dev/test-environment dev/publish-skills --check`.
It packs offline with lifecycle scripts disabled, then checks the actual archive
for the staged skills, license files, README, and generated plugin manifests.
The temporary package and archive are removed afterward. This does not publish,
check registry permissions, or require an unpublished version. `--check` accepts
no publication arguments; `--dry-run` still means npm's publication dry-run.

1. Set the same new semantic version in `package.json`, `.codex-plugin/plugin.json`, and `.agents/plugins/marketplace.json` (`source.version`).
2. Validate the metadata and npm archive:

   ```sh
   dev/test-environment python3 tests/setup/agent_skills_package_test.py
   dev/test-environment dev/publish-skills --check
   ```

3. Review and commit the release, then authenticate and publish:

   ```sh
   npm login
   npm whoami
   dev/publish-skills --access public
   ```

4. Verify the published version, then push the release commit:

   ```sh
   npm view judgement-yields-navigation version
   ```

5. Test a clean installation and start a new Codex thread so it loads the skills:

   ```sh
   codex plugin marketplace add jyn514/dotfiles
   codex plugin add judgement-yields-navigation@jyn-plugins
   ```

## Agent orchestration

Use [delegation](delegation/SKILL.md) when assigning work to agents, deciding whether to wait, or integrating their results.
It applies to implementation, research, review, and writing.

Use [work-selection](work-selection/SKILL.md) to reassess supporting work and obtain an independent scout's recommendation within an interactive or autonomous task.
It owns the reassessment trigger and next-action comparison; it grants no autonomous permission.

When the problem's framing or approach is uncertain, use
[creative-inquiry](creative-inquiry/SKILL.md) to question assumptions and discover
possibilities. For comparing concrete software-design candidates, use
[architecture-design](architecture-design/SKILL.md); its alternatives and independent-deliberation references are conditional, not a default workflow.

`creative-inquiry` is imported from
[`nia-e/rustc-project-skills`](https://github.com/nia-e/rustc-project-skills/tree/0fe6e4d11a99b8c62776048d13f59a4e5e4ff6ca/creative-inquiry),
with a locally adapted trigger and routes to software-design references.

Optional design techniques live under `architecture-design/references/` and add no startup skill descriptions.
Read [alternatives](architecture-design/references/alternatives.md) only for a demonstrated unresolved choice.
Use [independent deliberation](architecture-design/references/deliberation.md) only when the choice needs independent elaboration and critique.
Its phase helpers preserve candidate isolation and explicit abstention; they are not slash commands or names for subagent skill preloading.
When copying individual skills, preserve their linked shared references and required companion directories.

### Focused new-tool workflow

For a new independently invoked tool, CLI, service, or reusable executable subsystem, use `new-tool-development`.
Product briefs are human-authored; agents may review them and add permitted TODO comments.
Use `requirements-definition` for requirements and `technical-docs` for implementation-spec document form, reader tasks, ownership, and prerequisites.
Use `holistic-writing` for whole-artifact explanation and reader experience, and [review's design mode](review/references/design.md) for maturity, upstream/downstream consistency, and stale invalidation review.

## Design, planning, and review

Start architecture work by tracing one real caller through its handler and effects.
Recommend the existing path or smallest sufficient change before opening alternatives.
Maintain one boundary contract and carry it into specifications, requested plans, and coupled-worker assignments; do not repeat a declaration phase at each handoff.
[Boundary-contract questions](architecture-design/references/boundary-contracts.md) address only unresolved or changed guarantees.
[Delegation's shared-contract check](delegation/references/shared-contracts.md) checks coupled assignments without requiring architecture analysis.

Use `implementation-plan` only for a requested plan of a selected change.
It consumes settled decisions and reopens only concrete unresolved choices or contradictory evidence.
Architecture assessment alone does not require implementation tasks or commit sequencing.

Use [review](review/SKILL.md) with one explicit comparison target:

- a design or specification against its purpose, maturity, and governing constraints;
- implementation and tests against a normative specification, bounded or whole-spec;
- a completed substantial owned change against task acceptance.

Review-only work does not authorize repair, specification edits, or issue filing.
[Evidence standards](review/references/evidence.md) can be consulted without starting a completion audit.
Implementation preferences live in [change guidelines](references/change-with-evidence.md#design-choices).
Read [testing guidance](references/testing.md) for new or materially changed tests and uncertain test strategies or oracles.
Use [complexity justification](references/complexity-justification.md) when a proposed mechanism's necessity or required variability remains unclear.
These are on-demand references, not additional registered workflows.

### Updating an existing installation

Reload Pi or start a new harness session to refresh the skill catalog after installing this reorganization.
The retired skill names have no forwarding entries:

| Former skill | Current owner |
| --- | --- |
| `boundary-declaration` | Architecture's [boundary contracts](architecture-design/references/boundary-contracts.md); delegation's [assignment check](delegation/references/shared-contracts.md) |
| `design-space-scout`, `design-deliberation` | Architecture's optional [alternatives](architecture-design/references/alternatives.md) and [deliberation](architecture-design/references/deliberation.md) references |
| `second-user` | Shared [complexity justification](references/complexity-justification.md) |
| `design-for-change` | Shared [change guidelines](references/change-with-evidence.md#design-choices) and [testing guidance](references/testing.md) |
| `spec-review`, `audit-spec-against-impl`, `double-check` | [Review](review/SKILL.md), selecting design, conformance, or completion mode |
| `tighten-docs` | [Holistic writing](holistic-writing/SKILL.md) for whole-artifact editing; [tighten-prose](tighten-prose/SKILL.md) for bounded local polishing |

## Focused workflows

Use these independently when their target is already selected:

- `architecture-design` — assess, design, or choose a bounded architecture, reusing settled contracts and consulting alternatives only when needed.
- [autonomous-work](autonomous-work/SKILL.md) — pursue explicitly authorized autonomous runs and active user-authorized goals.
  Covers implementation, research, writing, planning, and review while preserving activity, acceptance order, independent progress, and resumable state.
  Implementation testing, integration, audit, and commit procedures apply only when that activity and its effects are authorized.
  Next-action selection delegates to `work-selection`; multi-outcome goals use `goal-to-issue-graph` for a current, minimal outcome graph.
  Install those companions too when copying `autonomous-work` individually.
- `cleanup-triage` — prioritize and slice cleanup after cleanup has been selected as the opportunity.
- `review` — select design, conformance, or completion review by its comparison target; use a diff review and native check for localized edits.
- [property-based-testing](property-based-testing/SKILL.md) — design generators and independent properties, review weak oracles, and diagnose counterexamples using the project's existing test framework.
- [mutation-testing](mutation-testing/SKILL.md) — challenge existing tests with bounded implementation changes, verify the tested consumer uses the mutation, and distinguish test gaps from equivalent or unresolved survivors; use project-compatible engines or an explicit manual pilot.
- `jj-conflict-resolution` — semantically compose Jujutsu conflict snapshots and diffs without ours/theirs or union heuristics.
- [human-review-packets](human-review-packets/SKILL.md) — prepare human decisions with concrete examples, recommendations, and simple questions; keep technical evidence optional and deferred approvals out of the active queue.
- `reorganize-docs` — change documentation information architecture, navigation, splits, consolidation, or archives.

`opportunity-scan` may hand a selected cleanup or architectural opportunity to the corresponding focused skill.
Use [Documentation placement](technical-docs/references/placement.md) for new-content destinations and routine additions, without loading an authoring skill.
Choose the writing workflow by the task, not a mandatory chain:

- [Holistic writing](holistic-writing/SKILL.md) owns whole-artifact authoring, substantial revision, and reader experience across reports, essays, prompts, instructions, skills, and documentation.
- [Technical docs](technical-docs/SKILL.md) owns documentation-specific forms, reader tasks, canonical owners, prerequisites, and routes.
  It does not own general editorial review merely because an artifact contains technical prose.
- [README writing](readme-writing/SKILL.md) is an independently usable workflow for introductory repository, package, or tool-entrypoint READMEs.
  It is sufficient to begin that task; do not load all writing workflows by default.
- [Tighten prose](tighten-prose/SKILL.md) owns local wording and cadence within an established explanation, not whole-artifact judgment.
- [Reorganize docs](reorganize-docs/SKILL.md) owns actual multi-page movement, consolidation, splits, archives, and navigation changes.
  Choosing where new content belongs uses the placement reference instead.

## Minimal use

You do not need the whole chain every time.

- Small refactor: implement directly when ownership and invariants are clear; consult change/testing references for unresolved decisions and complexity justification only when added machinery lacks a concrete need.
- Simple configuration edit: inspect the diff and validate with the native parser; no work-selection, design, or completion-audit skill is required.
- Another substantive prerequisite, workaround, or diagnostic round: use [work-selection](work-selection/SKILL.md) before extending the current approach.
- Architecture decision: use [architecture-design](architecture-design/SKILL.md) to trace the existing path and resolve the actual choice; alternatives and independent deliberation remain optional.
- Legacy subsystem: start with `pain-axis` before scouting.
- Explicit autonomous run or active user-authorized goal: start with [autonomous-work](autonomous-work/SKILL.md).
  Preserve the requested activity and follow its conditional companion-skill routes.
  A paused goal alone or an ordinary bounded request does not activate it.
  Add `ratchet` only for unresolved enforcement-policy decisions about baselines, violation identity or counts, bounded exceptions, or replacing guarantees.

## Important rule

Treat model judgments as evidence, not verification. Prefer repository facts, tests, type checks, benchmarks, and historical evidence whenever they exist. `council-review` may return `ABSTAIN`; that is a valid result.
