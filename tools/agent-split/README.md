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

Containment identifies removed lines by base occurrence and associates additions with their edit region, preserving repeats and terminal-newline state.
Pure insertions accept any ordered subsequence at the same base anchor, including non-prefix selections; replacements retain ordinal correspondence.
It does not compare sets of line strings.

Separated edits remain selectable when earlier unselected edits change line counts.
Adjacent one-for-one replacements can also be selected independently.
Partial unequal-length replacements within one contiguous region can be rejected conservatively when replacement correspondence is ambiguous.
This is an implementation limitation, not a declaration that every rejected subset is invalid; selecting the complete region avoids it.

JJ-generated regular-file/symlink conversion patches currently fail Git's dry-run apply with a mode mismatch before history changes.
Whether to support an alternative conversion encoding remains unresolved; ordinary executable-bit changes are not file-kind conversions.
Whole-blob binary selections require equality of canonical Git binary sections from the original and selected trees, ignoring only trailing section-framing newlines.
The tool does not parse binary payloads or authorize their content by file mode alone; partial binary selections are unsupported.
Canonical text diffs must decode losslessly as UTF-8.
Otherwise, preflight rejects before mutation rather than allowing malformed bytes to alias a legitimate U+FFFD character.

Symlink materialization uses documented `jj git root` and `jj log -T commit_id`, then reads the target verbatim with `git cat-file blob`.
`jj file show` excludes symlinks on the tested JJ version, so it is not a target-byte API.
This repair was verified with native JJ 0.45.1 and Git 2.49.1 in colocated Git-backend repositories.
Non-Git backends, older JJ versions lacking these commands, and protected proxy access to Git blobs are not established by the native tests.

## Common commands

```sh
bb agent-split target/jj-split/my-change.patch -m 'Extract focused change' @

bb agent-split target/jj-split/my-change.patch \
  -m 'Extract focused change' \
  -m 'Explain why this change belongs in a separate commit.' @

bb agent-split --remaining-message 'Keep unrelated cleanup' \
  target/jj-split/my-change.patch -m 'Extract focused change' @

bb agent-split --json target/jj-split/my-change.patch \
  -m 'Extract focused change' @
```

The revision defaults to `@`. `--json` emits full selected and remaining change IDs for automation. Use `--` to stop wrapper-option parsing.
Repeat `-m` to join message paragraphs with a blank line, in argument order.
Each `-m` consumes the next argument as literal text, even when it looks like an option.

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
- The wrapper resolves its route once and takes one initial snapshot. Native revision-only preflight and verification queries use `--ignore-working-copy`; protected proxy queries instead use child-scoped `JJ_PROXY_INSPECT=1` without that forbidden caller option. The trusted proxy executor injects its own working-copy-ignore flag after validation. Snapshot, structured split, and description requests remain mutations; inspection mode is not globally exported.
- Always provide `-m`; interactive patch and description editors are outside this workflow.
- Do not continue after a failure. Exit `1` means preflight failed before mutation, `2` means `jj split` failed, and `3` means post-split verification failed.
- Once the target resolves, preflight errors include the requested revision and the commit and parent IDs resolved before the checks.
  Compare those IDs with the current target when another writer may have committed; they do not guarantee the target stayed unchanged during preflight.
  Failures before target resolution cannot include these IDs.
- For exit `1`, regenerate selected hunks from `jj diff --git -r <revision>` and retain unchanged context from the revision's parent.
  When the normal dry-run fails but Git's diagnostic `--unidiff-zero --check` succeeds, the error identifies missing context.
  This extra check never applies the patch or enables zero-context matching for a split.
  If both checks fail, the error retains the normal Git failure without attributing it to zero-context matching.
  For exit `2`, inspect `jj status` and `jj op log` before retrying.
- Independent container-local repositories use native `jj split`, even with a sandbox proxy mounted. The shared JJ router resolves the workspace and backing metadata against effective mounts, not socket presence. Rootfs, private tmpfs, and guest-created volumes are supported; a local workspace linked to protected host metadata is not independent.
- Native verification failures trigger restoration of the operation captured in the same workspace before the split. If recovery fails, the original failure and `jj op restore <operation>` guidance remain on stderr. Inspect the operation before further history edits.
- Protected repositories use the wrapper's structured proxy split, which resolves the active agent identity. Proxy failures never retry natively or attempt native operation recovery; inspect repository history before retrying.
- With a sandbox proxy active, `JJ_ROUTE_HELPER` selects the shared routing helper (configured by the image); source checkouts otherwise use `tools/jj-proxy/route.py`. Ordinary non-sandbox hosts need neither the helper nor Linux mount information.
- A successful mechanical split can still be behaviorally incoherent. Include required adjacent/generated changes or choose a different boundary.

## Tests

From the repository root:

```sh
dev/test-environment bb -cp tools/agent-split/src tools/agent-split/tests/run.clj
dev/test-environment python3 -m unittest discover -s tools/agent-split/tests -p 'bb_wrapper_test.py'
```

The Babashka suite includes unit and real-repository integration coverage and therefore requires `bb`, `git`, and `jj`.
The shared [containment fixtures](tests/fixtures/containment-cases.edn) hold the authored text and binary selection expectations.
The full table runs in-process against real Git-produced canonical diffs, without creating a JJ repository or starting a child BB per case.
Representative CLI cases still verify publication and rejection against complete Git trees and blob bytes, filesystem bytes/kinds/modes, and commit/operation identity.
Native file-kind, ancestor, malformed-UTF-8, routing, and recovery tests remain separate from the containment matrix.
The Git oracle reads a tree's blobs in one `git cat-file --batch` process, preserving binary bytes and separate paths/modes for identical contents.
A native regression verifies that increasing blob count does not increase the oracle's process count.
Other regressions check independent parent-tree copying and symlink metadata queries scoped to each materialization.
The tests cover duplicate occurrences, multiplicity, replacement pairing, newline/CRLF state, stored ancestors, and conversion rejection.
Repositories are disposable and outside the source repository; test artifacts remain ignored.
`tests/run.clj` registers these tests and is invoked by `dev/test`.
The Python suite checks wrapper dispatch and executable resolution.

## Design and reference

For the protocol, invariants, worked example, and rationale, read the [design](./design.typ).
See the [tools overview](../README.md).
