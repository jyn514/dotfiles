---
name: jj-conflict-resolution
description: Resolve Jujutsu conflicts semantically by composing snapshots and diffs, never with ours/theirs or union heuristics. Use for jj rebase, merge, restack, or conflict-resolution tasks; route history design and general provenance work to jj-workflow.
---

# Jujutsu conflict resolution

Resolve the file result, not marker text. Jujutsu conflict content is a complete snapshot plus one or more diffs; concatenating sections is invalid.

## Scope and authority

This skill owns semantic resolution and validation. It does not choose rebase targets, abandon changes, rewrite shared history, or decide product behavior; use `jj-workflow` for those decisions. If the conflict representation is unclear, investigate it before editing.

Treat existing working-copy changes as protected until ownership is established. If a dirty file contains unrelated work, stop and ask before overwriting it.

## Isolate the operation

Perform the rebase, merge, or restack and its resolution in a disposable workspace, or entirely in the repository database without updating the live checkout.
Isolation starts before the operation that can introduce conflicts, not after conflicts appear.
Follow `jj-workflow`'s temporary-workspace procedure.
A separate workspace shares history: construct candidate revisions without rewriting the live checkout's revision while the result is unresolved or unvalidated.
Check the chosen command's working-copy effects before using a database-only approach.

Record the live checkout's revision and parents before starting.
Keep that checkout usable throughout resolution and validation, even when no other agent is editing it.
If it already contains conflicts, preserve its authored changes and continue resolution in isolation.

## Inspect first

Start with one of these commands:

```bash
jj status
jj log -r @ --no-graph \
  -T '"conflicts: " ++ if(conflict, "true", "false") ++ "\\n" ++ conflicted_files.map(|f| f.path().display()).join("\\n") ++ "\\n"'
```

Use `jj status` unless you already know the working-copy commit is conflicted; then use the second command. Before creating a resolution commit, identify the exact conflicted revision and target change.

Inspect the whole conflict and surrounding destination code for each file.
Check the installed `jj-conflict --help` interface rather than assuming its source documentation ships beside an installed skill.
If the repository provides the wrapper, use:

```bash
jj-conflict inspect path/to/file --json
```

For a checkout that does not install the wrapper, invoke its tracked path directly:

```bash
libexec/agent-wrappers/jj-conflict inspect path/to/file --json
```

Preview a composition first. If it is correct, write it and check the file:

```bash
jj-conflict apply path/to/file --edit 1,3:2 --preview
jj-conflict apply path/to/file --edit 1,3:2
jj-conflict check path/to/file
```

Unselected conflicts remain unresolved. Inspect again after a partial resolution before selecting more edits; the numbers refer to the remaining conflicts. The helper rejects conflict shapes it cannot compose safely rather than adding another heuristic.

Marker order may vary. Parse both forms:

- a `%%%%%%% diff from: BASE` section followed by a `+++++++ SIDE` snapshot;
- a `+++++++ SIDE` snapshot followed by a diff section.

Marker lengths may exceed seven characters. Do not identify sections by fixed-width markers.

## Resolve one file

For each conflict, record:

1. current destination snapshot;
2. base revision named by `diff from:`;
3. each transformed side and affected region;
4. unrelated destination changes to preserve;
5. semantic result required by both changes.

For each diff side, inspect its base file:

```bash
jj file show --revision BASE -- path/to/file
```

Verify the diff against that base, then apply its changes to the current destination snapshot. Preserve destination refactors and unrelated lines. If destination changes invalidate the diff's context, resolve that region manually; do not restore historical context. If both sides change the same behavior, reconcile the changes explicitly. Do not keep both blocks just because both appeared in the conflict.

When lifecycle ordering changed, trace the old and destination transitions before composing the fork behavior.
For example, destination startup may reserve a run before an extension callback that previously ran before reservation.
Preserve the destination's control flow and helper placement unless a required fork contract needs a different result.
Do not reverse that ordering just to preserve an old race fixture.
Test the required state, not merely the callback mechanism, using the [testing guidance on concurrent lifecycles](../references/testing.md#test-failures-and-concurrent-lifecycles).
If preserving the fork contract requires changing destination policy, ask before dependent edits rather than treating the old test setup as authority.

Do not use `:ours`, `:theirs`, equivalent whole-side selection, union merge tools, text concatenation, blind search-and-replace across all conflicts, or `jj undo` as recovery machinery.

For a multi-sided conflict, inspect every diff alternative and choose the required semantic result explicitly with `conflict:diff`. If the representation is unclear or a diff cannot be applied uniquely to its base, stop and inspect the exact Jujutsu format before editing. An unresolved ambiguity is safer than a syntactically valid but semantically damaged merge.

## Preserve Jujutsu history

In the disposable workspace, resolve in a fresh working-copy commit on top of the first conflicted candidate change.
Squash it into that exact change only if it is mutable and rewriting it is authorized; otherwise use `jj-workflow` to choose an allowed history strategy.
These commands run in the disposable workspace:

```bash
jj new CONFLICTED_CHANGE
# edit and inspect the files
jj diff --summary
jj squash --from @ --into CONFLICTED_CHANGE path/to/resolved-file
```

Select only owned resolution paths; if a path also contains unrelated edits, separate the hunks through `jj-workflow` before squashing.
Inspect any changes left in the resolution commit and preserve unrelated work.

Use the stable change ID, not a nearby `@-`, as the squash target. Let descendants restack; then repeat inspection and resolution for each conflicted descendant. Do not abandon a change until its patch and resulting tree are understood.

If a mutating command fails or is interrupted, inspect `jj status`, `jj log`, and operation state before retrying. Do not restore files or undo operations on assumption.

## Validate

After each resolution:

```bash
jj status
rg -n --hidden --glob '!node_modules/**' --glob '!.git/**' \
  '^(<<<<<<<|%%%%%%%|\+{7,}|>{7,})' path/to/resolved/files
```

Review marker-scan matches; intentional conflict fixtures are not unresolved conflicts.
Then inspect `jj diff -r CHANGE_ID` and run the narrowest relevant tests.
After descendants restack, rerun affected tests at the final intended tip.
Passing checks at an intermediate resolution do not establish that the assembled result works.
Validate the complete candidate before updating the live checkout, including files Jujutsu merged without conflicts.
Use native parsers for affected configuration: a clean text merge can still produce duplicate TOML keys or other invalid input.
Before completion, verify:

- no intended conflict remains in the current commit or descendants;
- no unintended conflict markers remain in tracked source files;
- unrelated working-copy changes are preserved;
- generated files were restored or regenerated from their authoritative source;
- type checks and tests pass, or unrelated baseline failures are recorded precisely.

A resolution is complete only when the resulting file is semantically reviewed, the exact change has received the resolution, descendants have been checked, and validation evidence covers every affected path.

## Update the live checkout

After validating the candidate, check the live checkout for edits made during the work.
Preserve those edits when integrating the candidate; if they change the validated result, compose and validate the new result in isolation first.
Update the live checkout only to the validated result, then verify its revision, conflict status, and affected configuration.
Do not expose intermediate conflicts or invalid configuration through a rebase, squash, or stale-workspace update.

## Review

Consider:
- Does your conflict resolution preserve the spirit of the original changes?
- Did you introduce any new bugs?
- Are any simplifications possible now that the base commit has changes?
- Did you make any breaking changes?
- Does the new code follow all existing rules and procedures for the repo? If not, identify which you introduced and which are pre-existing.
