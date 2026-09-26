---
name: jj-conflict-resolution
description: Resolve Jujutsu conflicts semantically by composing snapshots and diffs, never ours/theirs or union heuristics. Use for jj rebase, merge, restack, or conflict-resolution tasks; route history design and general provenance work to jj-workflow.
---

# Jujutsu conflict resolution

Resolve the file result, not marker text. Jujutsu conflict content is a complete snapshot plus one or more diffs; concatenating sections is invalid.

## Scope and authority

This skill owns semantic resolution and validation. It does not choose rebase targets, abandon changes, rewrite shared history, or decide product behavior; use `jj-workflow` for those decisions. If the conflict representation is unclear, investigate it before editing. Inspection does not authorize mutation: edit only when the user requests resolution or repair.

Treat existing working-copy changes as protected until ownership is established. If a dirty file contains unrelated work, stop and ask before overwriting it.

## Inspect first

Start with one of:

```bash
jj status
jj log -r @ --no-graph \
  -T '"conflicts: " ++ if(conflict, "true", "false") ++ "\\n" ++ conflicted_files.map(|f| f.path().display()).join("\\n") ++ "\\n"'
```

Use the second command when the working-copy commit is known to be conflicted; otherwise use `jj status`. Identify the exact conflicted revision and target change before creating the resolution commit.

Inspect the whole conflict and surrounding destination code for each file. See
the [`jj-conflict` command reference](../libexec/agent-wrappers/README.md) for
selection semantics. If the repository provides the wrapper, use:

```bash
jj-conflict inspect path/to/file --json
```

For a checkout that does not install the wrapper, invoke its tracked path directly:

```bash
libexec/agent-wrappers/jj-conflict inspect path/to/file --json
```

Preview a composition, write it, then check the file:

```bash
jj-conflict apply path/to/file --edit 1,3:2 --stdout
jj-conflict apply path/to/file --edit 1,3:2
jj-conflict check path/to/file
```

Unselected conflicts use their snapshot alternative. Inspect the alternatives before selecting one; the helper rejects conflict shapes it cannot compose safely rather than adding another heuristic.

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

For a diff side, inspect its base file:

```bash
jj file show --revision BASE -- path/to/file
```

Apply the diff to the base region, then place the result into the destination snapshot. Preserve destination refactors and unrelated lines. If both sides change the same behavior, reconcile it explicitly; do not keep both blocks merely because both appeared in the conflict.

Do not use `:ours`, `:theirs`, equivalent whole-side selection, union merge tools, text concatenation, blind search-and-replace across all conflicts, or `jj undo` as recovery machinery.

For a multi-sided conflict, inspect every diff alternative and choose the required semantic result explicitly with `conflict:diff`. If the representation is unclear or a diff cannot be applied uniquely to its base, stop and inspect the exact Jujutsu format before editing. An unresolved ambiguity is safer than a syntactically valid but semantically damaged merge.

## Preserve Jujutsu history

Resolve in a fresh working-copy commit on top of the first conflicted change, then squash it into the exact introducing change:

```bash
jj new CONFLICTED_CHANGE
# edit and inspect the files
jj diff --summary
jj squash --from @ --into CONFLICTED_CHANGE
```

Use the stable change ID, not a nearby `@-`, as the squash target. Let descendants restack; then repeat inspection and resolution for each conflicted descendant. Do not abandon a change until its patch and resulting tree are understood.

If a mutating command fails or is interrupted, inspect `jj status`, `jj log`, and operation state before retrying. Do not restore files or undo operations on assumption.

## Validate

After each resolution:

```bash
jj status
rg -n --hidden --glob '!node_modules/**' --glob '!.git/**' \
  '^(<<<<<<<|%%%%%%%|\+{7,}|>{7,})' path/to/resolved/files
```

Then inspect `jj diff -r CHANGE_ID` and run the narrowest relevant tests. Before completion, verify:

- no intended conflict remains in the current commit or descendants;
- no conflict markers remain in tracked source files;
- unrelated working-copy changes are preserved;
- generated files were restored or regenerated from their authoritative source;
- type checks and tests pass, or unrelated baseline failures are recorded precisely.

A resolution is complete only when the resulting file is semantically reviewed, the exact change has received the resolution, descendants have been checked, and validation evidence covers every affected path.
