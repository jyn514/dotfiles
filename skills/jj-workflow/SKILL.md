---
name: jj-workflow
description: "Use when a task involves inspecting file or revision history, establishing change provenance or ownership, comparing revisions, or shaping history through splits, rebases, restacks, conflicts, or abandonment. Do not use for routine status, diff, or commit tasks that need no history judgment."
---

# jj Workflow

Use this skill for nontrivial Jujutsu history work: inspect or interpret path history, annotations, revision ancestry, provenance, or change ownership; compare revisions; or shape history. Prefer `jj` over Git history-editing commands, keep changes coherent, and do not rewrite shared history unless asked. For semantic file conflict composition, use `jj-conflict-resolution`; this skill owns provenance, revision selection, and history shaping.

## Inspect and protect work

Start with one command:

- `jj status` for working-copy and parent identity plus dirty paths.
- `jj diff -r @ --summary` for only the dirty-file list.

Do not run both by default. Narrow with path-limited commands such as `jj diff -- path/to/file`; full colored diffs may truncate.

Treat unexpected deltas as authored work until ownership is established. Before mutating a dirty working copy:

- identify each contributor's paths and hunks;
- follow the [shared work ownership constraints](~/.agents/shared.md#before-mutating-a-working-copy)
  before restoring, overwriting, committing, rebasing, or abandoning another contributor's work;
- stop dependent mutations and ask if ownership or authorization remains unclear;
- use provenance and a three-way comparison—not similarity—to distinguish independent, stale, and duplicate changes.

Concurrent workers commit only their work and return its change ID. The coordinator owns integration and restacking.

## Compare and inspect history

Before comparing revisions, state the comparison question and establish the exact revision pair from history. For fork-only reviews, establish the fork's starting revision and head; neither upstream HEAD nor a merge base with today's upstream establishes that starting revision. A common-ancestor query answers only for its selected ref; confirm that ref belongs to the requested lineage. Support each fork-only attribution with the diff or history in that range. If the base is unresolved, report the evidence needed to resolve it and defer fork-only attributions and keep/drop priorities. Do not rank inherited code from broader tree diffs or commit titles, even provisionally.

Use `jj interdiff --from A --to B` to compare two revisions' patches, especially when their parents differ. `jj diff --from A --to B` compares resulting trees and may include inherited differences.
`jj show` does not accept filesets; for a path-limited revision patch, use `jj diff -r REV <paths>`.

For ordinary path history, pass the path directly:

```bash
jj log -n 20 doc/spec/flower --no-graph
```

When investigating a constraint, start with the relevant `jj log`.
Use `jj file annotate` and `jj diff -r <rev> <files...>` for the lines or revisions that explain it, and read their tests.

To combine path history with a revset, use `files()` with a quoted path expression:

```bash
jj log -r 'files("doc/spec/flower/**") & ancestors(@)' --no-graph
```

`files(doc/spec/flower/**)` is invalid. For complex selection, consult `jj help -k filesets` and `jj help -k revsets`.

## Commit

Use `jj commit` for a coherent completed change. Verify every included hunk first; split mixed concerns. For whole-file ownership, commit explicit paths:

```bash
jj commit src/flower/petal.clj -m "Fix markdown code fence handling"
jj show -r CHANGE_ID --summary --no-pager
```

Messages should be short and imperative. For non-mechanical changes, add a body explaining the problem, reason, and high-level approach; do not list test commands.

In concurrent worktrees, do not use `jj describe` followed by `jj new`: it mutates the shared working-copy change. Use `jj new` only after committing and when a fresh working change cannot disturb concurrent work.

After a commit, `@` is the new working copy and `@-` is usually the commit. Do not use `@-` as a squash target merely because it is nearby: descendants, rebases, or prior squashes may make it the wrong change. Identify the target by its stable change ID, inspect its patch and descendants, and use that ID explicitly, for example `jj squash --from @ --into CHANGE_ID path/to/owned-file`.

When exact identity matters:

```bash
jj log -r CHANGE_ID --no-graph \
  -T '"commit: " ++ commit_id.short() ++ "\nchange: " ++ change_id.short() ++ "\ntitle: " ++ description.first_line() ++ "\n"'
```

## Split or restore

Prefer splitting when separating work. Restore only changes that should be discarded and are clearly yours, or when explicitly asked.

- Whole-file boundary: use path-limited `jj split -r REV <paths...> -m "Message"`.
- Partial-file or hunk boundary: always use `bb agent-split target/jj-split/<name>.patch -m "Message"`.
- Never use `jj split --interactive`, `jj split --tool :builtin`, or another interactive split editor in this repository.

`bb agent-split` preflights the Git-style patch under ignored `target/jj-split/`, commits through a trusted path boundary, restores the remainder, and verifies both revisions. Failures retain recovery snapshots and print their location.

After either split, inspect selected and remaining changes with `jj status` and focused `jj diff -r CHANGE_ID` / `jj diff -r @`.

## Rebase and abandon

### Select the affected history

Establish the intended tip, destination, and authorized stack before choosing flags.
Read the installed `jj rebase --help` when their selection semantics are uncertain.
Expand the proposed selection with `jj log`, including revisions outside the intended tip's ancestry:

- `-s SOURCE` moves `SOURCE::`, not just the path from SOURCE to the intended tip.
- `-b TIP -o DEST` moves `(DEST..TIP)::`, including sibling branches descended from that range.
- `-r SET` moves the selected patches, but also reparents descendants to fill the holes; it does not guarantee unchanged sibling identities.

Compare the affected descendants and bookmarks with the authorized scope before mutating.
If siblings must keep their ancestry, duplicate only the intended stack onto the destination rather than moving its shared ancestors.
Do not perform a broad rebase and then repair unrelated branches.
Record the operation ID, intended tip, and affected heads before mutation; inspect the operation diff and verify untouched heads afterward.

### Maintain a fork stack

For ongoing authorized fork maintenance, prefer an upstream sync between feature groups over accumulating unrelated work on an old base.
This is a working cadence, not permission to schedule background fetches, rewrites, or pushes.
Use the lineage comparison above to identify upstream-equivalent changes; titles and empty-looking summaries are only candidates.
Inspect their patches, resulting trees, bookmarks, and descendants before abandonment.
Fold superseded metadata-only follow-ups into their introducing feature when intermediate revisions remain valid.
Keep manifests, lockfiles, generated artifacts, and their authoritative inputs coherent at each retained revision.
Do not remove intentional functionality merely to shorten the stack.

Before rebasing or abandoning, compare both the patch and resulting tree with the intended replacement.
Keep the original visible until the replacement is integrated, descendants are safely restacked, ownership is established, and tree equality is confirmed or every deliberate difference is recorded.
For history-only cleanup, require an empty whole-tree diff between the original and replacement tips, separately from unrelated working-copy edits.
Do not abandon while an unexpected difference remains unexplained.

## Conflicts and stacked fixes

Resolve conflicts through Jujutsu, not the Git index. Inspect `jj status`, the conflicted revision, and destination code. Preserve upstream refactors and relocate intended changes when code moved; do not restore obsolete blocks merely because they existed before the rebase.

List conflicts in `@` with:

```bash
jj log -r @ --no-graph \
  -T '"conflicts: " ++ if(conflict, "true", "false") ++ "\n" ++ conflicted_files.map(|f| f.path().display()).join("\n") ++ "\n"'
```

For stacked conflicts, use the introducing change's stable ID and exact fileset. Do not substitute nearby `@-`: descendants, rebases, or prior squashes may make it the wrong change:

```bash
jj squash --from @ --into CHANGE_ID path/to/owned-file
```

After each squash, let descendants restack, then inspect the remaining conflicts and affected revision. Audit possibly obsolete changes with `jj show CHANGE_ID --stat` and focused `jj diff -r CHANGE_ID`; abandon them rather than preserving empty or harmful effects.

If a mutating command is interrupted or partly fails, inspect `jj status` and `jj log` before retrying; history may already have changed.

## Temporary revision workspaces

Use isolated workspaces to generate or compare artifacts at revisions:

```bash
jj workspace add --name NAME -r REV /temporary/path
jj workspace remove NAME
```

The workspace files represent a working-copy commit on top of `REV`.
Keep artifacts out of the main dirty working copy and remove temporary workspaces when finished.

## Repository-specific authorship

Repository instructions override message guidance. If descriptions must be human-authored, review but do not originate or rewrite them; run `jj describe` only with exact user-supplied text.

## Reporting

After a path-limited commit, report `jj show -r CHANGE_ID --summary --no-pager`. Add `jj diff -r @ --summary` only when remaining dirty files matter. For a stack handoff:

```bash
jj log -r 'ancestors(@, 8)' --no-graph --summary \
  -T 'separate(" ", change_id.short(), commit_id.short(), if(empty, "<empty>", description.first_line())) ++ "\n"'
```
