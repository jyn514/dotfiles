# agent-split operator guide

## Purpose

`agent-split` selects patch-level changes for `jj split` without an interactive diff editor. The operator selects numbered whole hunks or supplies a Git-style patch; the wrapper preflights it, runs the repository-supported editor, and verifies both resulting trees.

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

For whole modified-text hunks, use the [numbered workflow](#numbered-hunk-workflow) below. For finer selections and file operations, keep the patch-file interface.

From the revision's current Git-format diff, create each patch at a fresh path under `target/jj-split/`:

```sh
mkdir -p target/jj-split
jj diff --git -r @
# Write only the selected hunks to target/jj-split/my-change.patch.
```

Hunk line counts are recalculated automatically, so removing lines from a hunk does not require updating its counts. Context must still apply, and selected changes must belong to the revision.

### Patch selection and supported formats

Containment identifies removed lines by base occurrence and associates additions with their edit region, preserving repeats and terminal-newline state.
Pure insertions accept any ordered subsequence at the same base anchor, including non-prefix selections.
A selection removing every old line in one replacement may select any ordered subset of that region's additions.
This permits selecting a changed entry without adjacent inserted entries that Git groups into the same replacement.
Selections removing only some old lines retain ordinal correspondence.
Neither case permits borrowing additions from another region, reordering them, exceeding duplicate counts, or changing newline bytes.
These checks establish structural containment, not authorship; the operator must still select only authorized changes.
It does not compare sets of line strings.

Separated edits remain selectable when earlier unselected edits change line counts.
When repeated lines put a selected insertion or deletion at a different base position, containment retries equivalent local placements.
These retries change only the diff representation, not the patch or selected file bytes.
They use the unchanged neighboring lines available in the parsed diff and stop at another selected edit or unavailable context.
A source-order pass chooses placements, then the existing validator checks the complete candidate against the original edit regions.
The retry does not search every combination of placements; unsupported alignments may still be rejected.
Adjacent one-for-one replacements can also be selected independently.
A pure deletion of complete replacement regions can include their immediately adjacent empty context lines.
This permits deleting an old section while leaving its replacement unselected when Git retains the section's blank separators as context.
It does not permit deleting space-only lines, unrelated anchors, or extra consecutive blank lines.
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

## Numbered-hunk workflow

List complete hunks, inspect their content, then select their IDs from the immutable source commit printed by that listing:

```sh
bb agent-split list @
bb agent-split list --json --path src/example.clj @
bb agent-split --from <full-source-commit-id> --hunks 2,5-8,12 \
  -m 'Extract focused change' --json @
```

Both revision operands default to `@`. `--from` requires the full commit ID, not a change ID, abbreviation, or moving selector.
`--hunks` accepts comma-separated positive IDs and inclusive ranges. Unknown IDs, empty elements, reversed ranges, and duplicate or overlapping selections fail before splitting.
Selections run in catalog order, regardless of argument order; there is no implicit select-all.
Do not combine a patch-file operand with `--from`/`--hunks`.
The existing message options and success JSON (`selected` and `remaining` change IDs) apply to either selection mode.
A legacy patch file named `list` is addressed as `./list`.

Listing shows every displayed hunk's ranges, context, additions, removals, and terminal-newline markers without truncation.
Repeatable `--path` filters are literal workspace-relative paths, not filesets or globs. They reduce output without renumbering global IDs.
An absent or outside-workspace path is an error. The JSON catalog contains `version`, `source_commit`, `source_change`, active `paths`, `hunks`, and `unsupported`.
Each hunk has `id`, `path`, `parent_range`, `source_range`, and full `text`; each range has `start` and `count`. The parent is derived internally, not printed separately.
An empty catalog is valid but cannot produce a split.

The first version selects whole hunks in modified regular UTF-8 text files with unchanged mode and kind. Nearby edits grouped into one hunk are selected together.
Creations, deletions, mode/kind changes, binary/non-UTF-8 changes, and unsupported path encodings appear by path and kind without hunk IDs.
Renames are shown as deletion and creation, following the canonical producer's no-renames representation.
The shared parser does not handle Git-quoted path headers (for example, filenames containing a literal double quote); these are reported as `path-encoding` rather than offered as selectable text.
Spaces, Unicode, and glob/operator characters are literal supported paths.
Use the legacy patch-file interface for unsupported operations where its existing format support permits them.

A moving listing takes one authoritative workspace snapshot; listing a full immutable commit uses inspection reads only. Neither listing form edits files or splits history, and neither stores a persistent catalog.
Selection reconstructs the inspected catalog before its one preflight snapshot and uses the originally selected bytes.
New unselected edits can proceed if dry-run and containment succeed, but a different target change or parent requires a new listing.
Selected-source races retain the existing native rejection and protected post-split verification behavior; failures do not silently retry against a new catalog or roll back history.
Producer options that affect hunk boundaries are fixed independently of user diff configuration. After changing the diff engine version, list again before selecting IDs.
Generated patches use fresh ignored `target/jj-split/` directories and are cleaned up after success or failure.

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
Preflight and selected-tree verification fetch file contents only for paths named in the patch, not every changed file in the revision.
Revision-wide checks still reject unexpected selected paths and require the complete remainder tree to match the actual split input.
Verification uses immutable commit IDs from the split operation; the reported change IDs can acquire newer edits afterward.
Jujutsu's evolution entries identify the actual split input and original remainder, including when split snapshots edits made after preflight.
Unselected edits made before or after the split are preserved and reported on stderr without corrupting the success JSON.
Repeat `-m` to join message paragraphs with a blank line, in argument order.
Each `-m` consumes the next argument as literal text, even when it looks like an option.

A sandbox can set `BB_SOURCE_ROOT` to a frozen startup copy, even when invoking the checkout's wrapper.
To use this checkout's implementation, select its source explicitly:

```sh
BB_SOURCE_ROOT="$PWD" libexec/agent-wrappers/bb agent-split \
  target/jj-split/my-change.patch -m 'Extract focused change'
```

This selects tool source only; it does not change the repository's Jujutsu backend or protected transport.

After success, inspect the IDs reported by the wrapper:

```sh
jj diff --git -r <selected>
jj diff --git -r <remaining>
jj status
```

Run tests or lint appropriate to each newly separated change.

## Advisory commit-boundary API

The standalone `--check-file` mode supports the Pi commit-boundary adapter. It
never splits, snapshots, commits, or writes the checkout. It needs the prerequisites
above, but not a patch file or an ignored `target/jj-split/` directory.

```sh
bb agent-split --check-file < request.json
```

Send exactly one JSON request on stdin:

```json
{
  "revision": "<full immutable commit ID>",
  "path": "relative/path.txt",
  "actual": {"content":"<base64 bytes>","executable":false},
  "proposed": "<base64 exact native-tool UTF-8 bytes>"
}
```

For an absent target use `"actual":null`. The caller skips unsupported target
types and retains the actual state observed by its native tool; the checker does
not reread the checkout file. The workspace is resolved from the command's cwd,
including repository subdirectories. `path` is always a literal path relative to
the workspace root, not a JJ fileset expression. Glob and operator characters do
not select other files. The revision's parent is derived, not supplied.

The three semantic replies have exit status zero:

- `{"status":"preserved"}`: permit the write and keep the boundary.
- `{"status":"would-lose","reason":"<concrete containment rejection>"}`:
  warn/block this write and forget the boundary.
- `{"status":"unusable","reason":"<expected skip reason>"}`:
  permit the write and forget the boundary.

Malformed JSON, request schema, immutable-ID syntax, base64, or noncanonical paths
are process failures, as are unexpected checker/subprocess errors: nonzero exit,
no semantic JSON reply. Cancellation likewise is not a semantic reply. There are
no diagnostic or retirement fields; the caller owns failure handling.

The checker validates the immutable revision and its unchanged single parent.
It materializes only the affected path from that parent and revision. If the path
has no revision diff, it returns `preserved` without either containment comparison.
Otherwise it first checks the revision against the retained actual state; an
already-lost boundary is `unusable`, not a warning blaming the proposal. Only a
proposal that loses containment from a valid current baseline returns `would-lose`,
with the splitter's concrete rejection reason. This uses the same canonical Git
diff producer and per-file containment engine as split preflight.

Regular lossless UTF-8 files without NUL bytes and ordinary creation are supported.
Absence and executable modes are preserved; symlinks, malformed UTF-8, binary data,
file-kind conversions, and unsupported canonical path encodings are `unusable`.
Missing revisions, changed parents, and unavailable workspaces are also expected
`unusable` results. Revision reads use the existing native or protected inspection
backend without snapshots during checks.

There is no capture mode or persistent record in this producer. The harness owns
ordinary JJ snapshot plus immutable `@` ID capture, any ignored `target/jj-split/`
state, boundary retirement, cancellation of the checker process and its children,
target-state verification, warning presentation, and the final write. See the
[commit-boundary design](../../config/pi-agent/pi-extensions/commit-boundary/design.typ)
for the adapter's lifecycle and finalization contract.

## Safety and recovery

- The patch must contain only changes already present in `jj diff --git -r <revision>`. Never use the tool to introduce new content.
- Keep patches and helper artifacts outside visible source or under ignored `target/jj-split/`; `jj split` snapshots the working copy before invoking its editor.
- The wrapper resolves its route once and takes one initial snapshot. Native revision-only preflight and verification queries use `--ignore-working-copy`; protected proxy queries instead use child-scoped `JJ_PROXY_INSPECT=1` without that forbidden caller option. The trusted proxy executor injects its own working-copy-ignore flag after validation. Snapshot, structured split, and description requests remain mutations; inspection mode is not globally exported.
- Always provide `-m`; interactive patch and description editors are outside this workflow.
- Do not continue after a failure. Exit `1` means preflight failed before mutation, `2` means `jj split` failed, and `3` means post-split verification failed.
- Once the target resolves, preflight errors include the requested revision and the commit and parent IDs resolved before the checks.
  Compare those IDs with the current target when another writer may have committed; they do not guarantee the target stayed unchanged during preflight.
  Failures before target resolution cannot include these IDs.
  Containment errors name the selected parent/base line range or insertion gap and the failed comparison.
  When the selection fits an original edit region, the diagnostic names that region too.
  These coordinates refer to the parent file, not the current working copy; binary and file-mode errors do not invent text coordinates.
- For exit `1`, regenerate selected hunks from `jj diff --git -r <revision>` and retain unchanged context from the revision's parent.
  When the normal dry-run fails but Git's diagnostic `--unidiff-zero --check` succeeds, the error identifies missing context.
  This extra check never applies the patch or enables zero-context matching for a split.
  If both checks fail, the error retains the normal Git failure without attributing it to zero-context matching.
  For exit `2`, inspect `jj status` and `jj op log` before retrying.
- Independent container-local repositories use native `jj split`, even with a sandbox proxy mounted. The shared JJ router resolves the workspace and backing metadata against effective mounts, not socket presence. Rootfs, private tmpfs, and guest-created volumes are supported; a local workspace linked to protected host metadata is not independent.
- Post-split errors report the known selected and remaining change and commit IDs, plus the split input commit when available.
  If an identity query fails, the diagnostic marks the unavailable ID instead of guessing.
  Selected patch mismatches, remainder mismatches, and observed concurrent edits have distinct diagnostics.
- Verification failures leave the split intact; the wrapper never automatically restores an older operation.
  A writer can commit or snapshot edits after any freshness check, so operation-wide rollback could erase unrelated work.
  Inspect the reported revisions before retrying or making a scoped repair.
  Native failures also report the preflight operation for investigation, not as an instruction to restore it.
- Protected repositories use the wrapper's structured proxy split, which resolves the active agent identity.
  Proxy failures never retry natively; inspect repository history before retrying.
  The protected shell editor applies the patch without containment validation, so changed split inputs are revalidated afterward.
  A selected-source change detected there exits `3` with the completed split IDs; native editors reject it during the split.
- With a sandbox proxy active, `JJ_ROUTE_HELPER` selects the shared routing helper (configured by the image); source checkouts otherwise use `tools/jj-proxy/route.py`. Ordinary non-sandbox hosts need neither the helper nor Linux mount information.
- A successful mechanical split can still be behaviorally incoherent. Include required adjacent/generated changes or choose a different boundary.

## Tests

From the repository root:

```sh
dev/test-environment bb -cp tools/agent-split/src tools/agent-split/tests/run.clj
dev/test-environment python3 -m unittest discover -s tools/agent-split/tests -p '*_test.py'
```

The Babashka suite includes unit and real-repository integration coverage and therefore requires `bb`, `git`, and `jj`.
The shared [containment fixtures](tests/fixtures/containment-cases.edn) hold the authored text and binary selection expectations.
The full table runs in-process against real Git-produced canonical diffs, without creating a JJ repository or starting a child BB per case.
Representative CLI cases still verify publication and rejection against complete Git trees and blob bytes, filesystem bytes/kinds/modes, and commit/operation identity.
Native file-kind, ancestor, malformed-UTF-8, routing, and failure-reporting tests remain separate from the containment matrix.
Concurrent-writer cases snapshot changes to another file and an unselected hunk before and after the split, and reject changed selected source.
Failure cases retain those edits even when discovery fails or a writer starts during verification.
Protected-path cases use the real shell editor with relocated executable and patch paths.
Boundary cases distinguish whole-section deletion across empty separators from unrelated or excess blank-line deletion.
The Git oracle reads a tree's blobs in one `git cat-file --batch` process, preserving binary bytes and separate paths/modes for identical contents.
A native regression verifies that increasing blob count does not increase the oracle's process count.
Other regressions check independent parent-tree copying and symlink metadata queries scoped to each materialization.
A real-repository regression adds unrelated new and modified files, verifies unchanged per-file read counts, and checks that the split preserves the complete input tree.
The tests cover duplicate occurrences, multiplicity, replacement pairing, newline/CRLF state, stored ancestors, and conversion rejection.
Repositories are disposable and outside the source repository; test artifacts remain ignored.
`tests/run.clj` registers these tests and is invoked by `dev/test`.
The numbered CLI suite starts with two files/four hunks and checks exact selected and remainder trees for nonadjacent IDs. It also covers filtered IDs, configuration independence, ranges, invalid input modes, literal paths, repeated lines, grouped context, terminal-newline markers, changed target identity/parents, stale selected source, unsupported operations, and snapshot/artifact counts. Native and protected concurrency fixtures exercise both patch-file and numbered selections.
The Python suites check wrapper dispatch and executable resolution, plus the
advisory check through the real CLI in disposable JJ repositories. Advisory
cases cover reorganization/extraction warnings, already-lost baselines, repeated
independent requests, successive preserved proposals, unrelated dirty hunks,
read-only command counts, modes, absence, unsupported kinds, malformed UTF-8, changed
bases, missing IDs, and nonzero malformed-input/infrastructure failures. They are discovered by the default
pytest suite under `tools/`. Pi retirement, retries, and final writes belong to
the adapter integration tests, not these producer tests.

## Design and reference

For the protocol, invariants, worked example, and rationale, read the [design](./design.typ).
See the [tools overview](../README.md).
