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
jj-conflict apply path/to/file --edit <conflict>[:<diff>][,...] [--stdout]
jj-conflict check path/to/file...
```

### Inspect

`inspect` reports every conflict and its diff alternatives. With `--json`, the
report includes the conflict number, line range, snapshot source, alternative
source and destination, changed lines, and snapshot length.

The numbers used by `apply` are the `edit` numbers in this report. A single
alternative is selected as `1`; a multi-sided conflict requires the form
`<conflict>:<diff>`, such as `2:1`. Changed lines retain their diff markers in
text and JSON output: `-` means removed and `+` means added.

### Apply

`--edit` selects diff alternatives for the listed conflicts:

```text
jj-conflict apply path/to/file --edit 1,3:2 --stdout
jj-conflict apply path/to/file --edit 1,3:2
```

The first command previews the composed file. The second writes it back. In
`1,3:2`, conflict 1 uses its first diff alternative and conflict 3 uses its
second. Conflicts omitted from `--edit` retain their embedded complete
snapshot; this is the default, not an unresolved partial merge.

The command fetches each selected diff's base file with `jj file show`, applies
the diff to that base, and replaces the corresponding conflict region in the
destination snapshot. It rejects malformed conflict sections, ambiguous diff
context, missing bases, duplicate selections, and invalid alternative numbers.

### Check

`check` exits successfully only when the supplied files contain no recognized
Jujutsu conflicts:

```text
jj-conflict check path/to/file other/file
```

It is a structural check for this conflict format, not a general source-code
or merge-quality check.
