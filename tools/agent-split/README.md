# agent-split operator guide

## Purpose

`agent-split` selects patch-level changes for `jj split` without an interactive diff editor. The operator supplies a Git-style patch; the wrapper preflights it, runs the repository-supported editor, and verifies both resulting trees.

## Prerequisites and setup

- `bb` (Babashka), `git`, and `jj` on `PATH`
- A Jujutsu working copy
- The repository's `bb` wrapper on `PATH` (normally `libexec/agent-wrappers`)
- `target/jj-split/` ignored by version control

Check dispatch and snapshot safety:

```sh
bb agent-split --help
git check-ignore -q target/jj-split/.probe
```

From the revision's current Git-format diff, create each patch at a fresh path under `target/jj-split/`:

```sh
mkdir -p target/jj-split
jj diff --git -r @
# Write only the selected hunks to target/jj-split/my-change.patch.
```

Hunk line counts are recalculated automatically, so removing lines from a hunk does not require updating its counts. Context must still apply, and selected changes must belong to the revision.

## Common commands

```sh
bb agent-split target/jj-split/my-change.patch -m 'Extract focused change' @

bb agent-split --remaining-message 'Keep unrelated cleanup' \
  target/jj-split/my-change.patch -m 'Extract focused change' @

bb agent-split --json target/jj-split/my-change.patch \
  -m 'Extract focused change' @
```

The revision defaults to `@`. `--json` emits full selected and remaining change IDs for automation. Use `--` to stop wrapper-option parsing.

After success, inspect the IDs reported by the wrapper:

```sh
jj diff --git -r <selected>
jj diff --git -r <remaining>
jj status
```

Run tests or lint appropriate to each newly separated change.

## Safety and recovery

- The patch must contain only changes already present in `jj diff --git -r <revision>`. Never use the tool to introduce new content.
- Keep patches and helper artifacts outside visible source or under ignored `target/jj-split/`; `jj split` snapshots the working copy before invoking its editor.
- The wrapper takes one initial snapshot, then runs revision-only preflight and verification queries with `--ignore-working-copy`; the mutating `jj split` retains normal snapshot behavior.
- Always provide `-m`; interactive patch and description editors are outside this workflow.
- Do not continue after a failure. Exit `1` means preflight failed before mutation, `2` means `jj split` failed, and `3` means post-split verification failed.
- For exit `1`, regenerate the patch from the current diff and retry. For exit `2`, inspect `jj status` and `jj op log` before retrying.
- On verification failure, the wrapper attempts to restore the operation recorded before mutation. If it cannot, stderr names the required `jj op restore <operation>` command; run it before further history edits.
- A successful mechanical split can still be behaviorally incoherent. Include required adjacent/generated changes or choose a different boundary.

## Tests

From the repository root:

```sh
bb -cp tools/agent-split/src tools/agent-split/tests/run.clj
python3 -m unittest discover -s tools/agent-split/tests -p 'bb_wrapper_test.py'
```

The Babashka suite includes unit and real-repository integration coverage and therefore requires `bb`, `git`, and `jj`. The Python suite checks wrapper dispatch and executable resolution.

## Design and reference

For the protocol, invariants, worked example, and rationale, read the [design](./design.typ).
See the [tools overview](../README.md).
