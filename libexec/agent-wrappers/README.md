# `jj-conflict`

`jj-conflict` inspects and composes Jujutsu's file-conflict representation. It
does not concatenate conflict sections or choose `ours` and `theirs`; each
conflict contains one complete snapshot plus one or more diff alternatives.

The wrapper is intended for semantic resolution workflows. For the decision
process and validation requirements, see
[`skills/jj-conflict-resolution/SKILL.md`](../../skills/jj-conflict-resolution/SKILL.md).

## Commands

Run the wrapper from the repository root, or invoke it by its tracked path:

```text
jj-conflict inspect path/to/file [--json]
jj-conflict apply path/to/file --edit <conflict>[:<diff>][,...] [--stdout | --preview]
jj-conflict check path/to/file...
```

### Inspect

`inspect` reports every conflict and its diff alternatives. With `--json`, the
report includes the conflict number, line range, snapshot source, alternative
source and destination, changed lines, snapshot contents (`snapshot`),
snapshot length (`snapshotLines`), and its first content line (`snapshotStartLine`).
Text output also shows the snapshot contents.

The numbers used by `apply` are the `edit` numbers in this report. A single
alternative is selected as `1`; a multi-sided conflict requires the form
`<conflict>:<diff>`, such as `2:1`. Changed lines retain their diff markers in
text and JSON output: `-` means removed and `+` means added. Inspect again after
a partial resolution: `edit` numbers refer to the conflicts currently in the file.

### Apply

`--edit` selects diff alternatives for the listed conflicts:

```text
jj-conflict apply path/to/file --edit 1,3:2 --preview
jj-conflict apply path/to/file --edit 1,3:2
```

The first command shows a concise diff against each selected conflict's snapshot,
with three context lines around each change. Line numbers are relative to that
snapshot, not the whole file. It does not write the file. The second command
writes the composition. Use `--stdout` instead of `--preview` to print the entire
composed file without writing it; the two flags cannot be combined. Status and
the unresolved conflict count go to stderr.

In `1,3:2`, conflict 1 uses its first diff alternative and conflict 3 uses its
second. Omitted conflicts retain their original marker blocks and remain
unresolved. Text outside selected conflicts and unchanged snapshot lines retain
their original line endings. Added lines use the replaced line's ending, or an
adjacent line's ending for insertions; empty snapshots use the marker's ending.

The command fetches each selected diff's historical source file with `jj file
show`. When a source label contains a change ID and commit hash, it uses the hash
because the change ID may be divergent. The diff's old text must match exactly
once in both that source file and the current conflict snapshot. The command
replaces only the matching snapshot region, preserving the rest of the snapshot.
It does not replay historical context over destination changes. Changed context
or overlapping edits require manual resolution.

It rejects malformed conflict sections, ambiguous diff context, missing bases,
duplicate selections, and invalid alternative numbers before writing anything.
A context-free insertion into a nonempty source or snapshot cannot be placed
safely; inspect the snapshots and resolve that change manually. Differing native
`(no terminating newline)` labels, including newline-only edits, require manual
resolution. `\ No newline at end of file` annotations are also rejected rather
than ignored. The command handles UTF-8 text, not binary files.

### Check

`check` exits successfully only when the supplied files contain no recognized
Jujutsu conflicts:

```text
jj-conflict check path/to/file other/file
```

It is a structural check for this conflict format, not a general source-code
or merge-quality check.
