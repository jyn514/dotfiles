---
name: jj-workflow
description: "Use only when a Jujutsu task requires history-shaping judgment: partial-file splits, rebases/restacks, conflicts, or unclear change ownership. Do not use for commits limited to explicitly owned whole files, even when the working copy contains multiple files or needs multiple commits."
---

# jj Workflow

Use this skill for nontrivial Jujutsu history work. Prefer `jj` over Git history-editing commands, keep changes coherent, and do not rewrite shared history unless asked.

## Inspect and protect work

Start with one command:

- `jj status` for working-copy and parent identity plus dirty paths.
- `jj diff -r @ --summary` for only the dirty-file list.

Do not run both by default. Narrow with path-limited commands such as `jj diff -- path/to/file`; full colored diffs may truncate.

Treat unexpected deltas as authored work until ownership is established. Before mutating a dirty working copy:

- identify each contributor's paths and hunks;
- do not restore, overwrite, commit, rebase, or abandon another contributor's work;
- stop and ask if a needed file contains edits you do not own;
- use provenance and a three-way comparison—not similarity—to distinguish independent, stale, and duplicate changes.

Concurrent workers commit only their work and return its change ID. The coordinator owns integration and restacking.

## Compare and inspect history

Use `jj interdiff --from A --to B` to compare two revisions' patches, especially when their parents differ. `jj diff --from A --to B` compares resulting trees and may include inherited differences.

For ordinary path history, pass the path directly:

```bash
jj log -n 20 doc/spec/flower --no-graph
```

To combine path history with a revset, use `files()` with a quoted path expression:

```bash
jj log -r 'files("doc/spec/flower/**") & ancestors(@)' --no-graph
```

`files(doc/spec/flower/**)` is invalid. For complex selection, consult `jj help -k filesets` and `jj help -k revsets`.

## Commit

Use `jj commit` for a coherent completed change. Verify every included hunk first; split mixed concerns. For whole-file ownership, commit explicit paths:

```bash
jj commit src/flower/petal.clj -m "Fix markdown code fence handling"
jj show -r @- --summary --no-pager
```

Messages should be short and imperative. For non-mechanical changes, add a body explaining the problem, reason, and high-level approach; do not list test commands.

In concurrent worktrees, do not use `jj describe` followed by `jj new`: it mutates the shared working-copy change. Use `jj new` only after committing and when a fresh working change cannot disturb concurrent work.

After a commit, `@` is the new working copy and `@-` is usually the commit. When exact identity matters:

```bash
jj log -r @- --no-graph \
  -T '"commit: " ++ commit_id.short() ++ "\nchange: " ++ change_id.short() ++ "\ntitle: " ++ description.first_line() ++ "\n"'
```

## Split or restore

Prefer splitting when separating work. Restore only changes that should be discarded and are clearly yours, or when explicitly asked.

- Whole-file boundary: use path-limited `jj split -r REV <paths...> -m "Message"`.
- Partial-file or hunk boundary: always use `bb agent-split target/jj-split/<name>.patch -m "Message"`.
- Never use `jj split --interactive`, `jj split --tool :builtin`, or another interactive split editor in this repository.

`bb agent-split` preflights the Git-style patch under ignored `target/jj-split/`, commits through a trusted path boundary, restores the remainder, and verifies both revisions. Failures retain recovery snapshots and print their location.

After either split, inspect selected and remaining changes with `jj status` and focused `jj diff -r @-` / `jj diff -r @`.

## Rebase and abandon

Inspect the target and descendants before `jj rebase`, and inspect the stack afterward. Before rebasing or abandoning, compare both the patch and resulting tree with the intended replacement.

Keep the original visible until the replacement is integrated, descendants are safely restacked, ownership is established, and tree equality is confirmed or every deliberate difference is recorded. Do not abandon while an unexpected difference remains unexplained.

## Conflicts and stacked fixes

Resolve conflicts through Jujutsu, not the Git index. Inspect `jj status`, the conflicted revision, and destination code. Preserve upstream refactors and relocate intended changes when code moved; do not restore obsolete blocks merely because they existed before the rebase.

List conflicts in `@` with:

```bash
jj log -r @ --no-graph \
  -T '"conflicts: " ++ if(conflict, "true", "false") ++ "\n" ++ conflicted_files.map(|f| f.path().display()).join("\n") ++ "\n"'
```

For stacked conflicts, put each resolution into the change that introduced it, using stable change IDs and exact filesets:

```bash
jj squash --from @ --into CHANGE_ID path/to/owned-file
```

After each squash, let descendants restack, then inspect the remaining conflicts and affected revision. Audit possibly obsolete changes with `jj show CHANGE_ID --stat` and focused `jj diff -r CHANGE_ID`; abandon them rather than preserving empty or harmful effects.

If a mutating command is interrupted or partly fails, inspect `jj status` and `jj log` before retrying; history may already have changed.

## Temporary revision workspaces

Use isolated workspaces to generate or compare artifacts at revisions:

```bash
jj workspace add --name NAME -r REV /temporary/path
jj workspace forget --cleanup NAME
```

The workspace files represent a working-copy commit on top of `REV`. Keep artifacts out of the main dirty working copy and forget temporary workspaces when finished.

## Repository-specific authorship

Repository instructions override message guidance. If descriptions must be human-authored, review but do not originate or rewrite them; run `jj describe` only with exact user-supplied text.

## Reporting

After a path-limited commit, report `jj show -r @- --summary --no-pager`. Add `jj diff -r @ --summary` only when remaining dirty files matter. For a stack handoff:

```bash
jj log -r 'ancestors(@, 8)' --no-graph --summary \
  -T 'separate(" ", change_id.short(), commit_id.short(), if(empty, "<empty>", description.first_line())) ++ "\n"'
```
