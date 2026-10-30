#set document(title: "Agent-safe patch-level jj split")
#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

#let callout(label, body) = block(above: 0.6em, below: 0.6em)[
  #strong(label) #body
]
#let requirement(body) = callout("Requirement.", body)
#let rationale(body) = callout("Rationale.", body)
#let status(body) = callout("Status.", body)
#let invariant(body) = callout("Invariant.", body)
#let open-question(body) = callout("Open question.", body)
#let takeaway(body) = callout("Takeaway.", body)
#let example(body) = block(inset: (left: 1em), body)

#align(center)[
  #v(3cm)
  #text(size: 24pt, weight: "bold")[Agent-safe patch-level `jj split`]
  #v(0.5em)
  #text(size: 14pt, fill: luma(80))[deterministic split selection through a non-interactive diff editor]
  #v(1em)
]

= Overview <agent-jj-split-overview>

`jj split` can split a change by file without interaction, but patch-level selection normally opens an interactive diff editor.
That is a poor fit for agents: terminal UIs require hidden state, keystroke choreography, and a visual feedback loop the agent cannot reliably operate.

This document specifies an agent-safe way to make patch-level `jj split` usable without a TUI.
The design does not add a new Jujutsu command.
It wraps the existing diff-editor protocol with a deterministic tool.

#takeaway[The agent selects changes by writing an ordinary patch.
A diff-editor shim applies that patch to Jujutsu's left tree and replaces Jujutsu's right tree with the result.
Jujutsu then performs the split exactly as if a human had edited the right side by hand.]

#status[The patch-file splitter and its containment, execution, verification, and recovery paths are implemented. Numbered-hunk listing and selection in @agent-jj-split-numbered-hunks are implemented alongside the patch-file interface.
Containment includes the local-rotation retry in @agent-jj-split-repeated-lines.
Unsupported alignment changes can still be rejected.]

= Problem <agent-jj-split-problem>

Today an agent can run:

#example[
```sh
jj split path/to/file.clj -m 'Extract focused change'
```
]

That works when the desired boundary is a whole file or a fileset.
It does not work when one file contains both the selected change and unrelated edits.

The obvious command is:

#example[
```sh
jj split -i
```
]

But `-i` starts an interactive diff editor.
An agent can often launch it, but cannot reliably drive it.
That makes the safest practical workflow coarser than the history the repository wants.

#rationale[Small, behaviorally coherent commits are important here.
File-level splitting forces the agent to choose between oversized commits and fragile terminal automation.
Patch-level splitting should be available to agents, but the selection step must be data, not keystrokes.]

= Design <agent-jj-split-design>

`jj split` already delegates patch selection to a diff editor.
For split, Jujutsu prepares two directory trees:

- the *left* tree, representing the parent/base side,
- the *right* tree, representing the candidate selected side.

The diff editor is expected to edit the right tree until it contains exactly the content wanted in the selected commit.
When the editor exits successfully, Jujutsu computes the selected changes from the difference between left and right, and leaves the rest as the remaining commit.

The implemented tool, `jj-agent-split-editor`, is a non-interactive diff editor.
It accepts the left and right tree paths from Jujutsu, reads a preselected patch path from the environment, constructs `left + patch` in a temporary tree, and then replaces the right tree with that constructed tree.

== Contract <agent-jj-split-contract>

#requirement[The agent supplies one Git-style unified diff patch containing exactly the hunks intended for the first split commit.
The patch is produced from, or normalized against, `jj diff --git` for the revision being split.]

#requirement[The diff-editor shim applies the patch to a temporary copy of the left tree.
It never edits the left tree.]

#requirement[If the patch applies cleanly and the resulting selected diff is a subset of the original `diff(left, right)`, the shim replaces the right tree with the patched temporary tree and exits zero.]

#requirement[If the patch is missing, malformed, does not apply, edits paths outside the selected revision, introduces changes that were not already present in the original right tree, or would leave the right tree inconsistent, the shim exits non-zero.
Jujutsu must then abort the split.]

#requirement[The split command uses `-m` or another non-interactive description path so that no commit-message editor opens after the diff editor finishes.
In current Jujutsu, `jj split -m` sets the selected commit's description;
the remaining commit keeps the original description.]

#invariant[The selected commit is always `diff(left, patched-left)`.
It is never inferred from the agent's current working copy, prose summary, or intended file list.]

== Lower-level diff-editor invocation <agent-jj-split-example>

#example[
```sh
JJ_AGENT_SPLIT_PATCH=/tmp/selected.patch \
  jj split --tool agent-split -m 'Extract focused change'
```
]

An equivalent one-shot invocation can avoid persistent configuration:

#example[
```sh
JJ_AGENT_SPLIT_PATCH=/tmp/selected.patch \
  jj split \
    --config 'merge-tools.agent-split.program="/path/to/jj-agent-split-editor"' \
    --config 'merge-tools.agent-split.edit-args=["$left","$right"]' \
    --tool agent-split \
    -m 'Extract focused change'
```
]

= Tool behavior <agent-jj-split-tool>

The minimal tool shape is:

#example[
```sh
#!/usr/bin/env bash
set -euo pipefail

left="$1"
right="$2"
patch="${JJ_AGENT_SPLIT_PATCH:?set JJ_AGENT_SPLIT_PATCH}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cp -a "$left"/. "$tmp"/
cd "$tmp"
git apply "$patch"

rm -rf "$right"
cp -a "$tmp" "$right"
```
]

This sketch is deliberately small.
A production tool should add validation before and after `git apply`.

#requirement[The production tool must reject absolute paths, parent-directory traversal, and paths outside the Jujutsu-provided tree.]

#requirement[The production tool must perform a dry-run apply before mutating the temporary tree, and report the failing path and hunk when possible.]

#requirement[The production tool must validate parsed patch paths before invoking `git apply`;
it must not rely on `git apply` or shell path normalization as the only traversal check.]

#requirement[The production tool must compare `diff(left, patched-left)` with the original `diff(left, right)`
and reject any selected change that was not present in the revision being split.
For regular UTF-8 text, @agent-jj-split-repeated-lines adds local alignment retries without replacing this validator.
Containment preserves path, removed-line occurrence, multiplicity, addition order, and final-newline state.
When every old line in one replacement is selected for removal, any ordered subset of that region's additions is permitted.
Otherwise, additions retain ordinal correspondence with the removed lines.
Matching line text alone does not authorize another occurrence, additions from another region, or reversed partial replacement pairs.
Structural containment does not establish authorship or authorize selecting unrelated work.
Modes and symlink targets retain their native representation; binary changes require canonical equality.
Lossy decoding cannot establish containment.
Unsupported canonical forms fail before mutation.]

#requirement[The production tool must replace the right tree atomically enough that a failed copy cannot be mistaken for a successful editor run.
If the platform cannot make the replacement atomic, the tool must exit non-zero on any copy failure.]

#requirement[The production tool must preserve executable bits and symlinks according to the patch format and the copied tree.]

#requirement[The production tool should print a compact summary of selected files and hunk counts before exiting zero.]

== Local retries for repeated-line placement <agent-jj-split-repeated-lines>

A selected diff and the full diff can describe the same surviving base line at different positions among repeated lines.
Comparing their independently chosen insertion coordinates can therefore reject a valid selection.
The problem is not specific to whitespace.

Consider these three versions, aligned by line occurrence:

#example[
```text
Base        Selected    Full
A           A           A
(no line)   (no line)   other
(no line)   token       token
(no line)   mine        mine
token       token       token
B           B           B
```
]

`(no line)` marks absence, not file content; every file line in this example ends with LF.
The original `token` survives after `mine` in this correspondence.
The selected change inserts `token` and `mine`; the full change inserts those lines plus `other`.
An independent diff may instead match the original `token` to the earlier occurrence in one comparison.
That changes the reported insertion position without changing the selected file.
Replacing `token` with an empty line gives the same shape as the motivating paragraph-selection failure.
Before the local retry, the containment checker rejected both forms of this minimal example.
It reported the selected insertion at the base gap before line 3, while the full insertion was anchored before line 2.
This reproduction invokes containment directly; no split is needed.
Moving the selected text elsewhere avoids the rejection but is not an acceptable requirement on authored content.

The selected diff inserts `mine` and `token` after the original `token`.
Moving that insertion block left across the original `token` rotates its contents to `token`, then `mine`.
This is a different diff for exactly the same selected bytes, now at the full change's insertion gap.

#requirement[Run the existing containment validator first.
For rejected regular-text selections, retry local rotations of pure insertion or pure deletion blocks across identical neighboring base lines.
A left shift requires the block's last line to equal the preceding unchanged base line;
move that last line to the front of the block and shift its base position left by one line.
A right shift requires the block's first line to equal the following unchanged base line;
move that first line to the back and shift its base position right by one line.
Use exact line bytes, including line endings and missing final newlines.
The rule applies to repeated nonempty lines as well as empty lines; it does not normalize whitespace.]

#requirement[Each candidate diff must reconstruct the exact selected bytes from the original base.
Only the diff representation changes: never move authored text, rewrite the supplied patch, or change the selected tree.
Use the unchanged neighboring base lines carried in the parsed selected diff.
Walk equivalent positions locally, stopping at an unequal or unavailable neighbor, another selected edit, or a file boundary.
Make one source-order pass over the selected blocks.
For each pure block, try its current placement, then leftward placements, then rightward placements.
Keep the first placement that passes the existing validator for that fragment; leave the block unchanged if none passes.
Retries terminate without cycling or enumerating combinations across fragments.]

#requirement[Pass complete candidate diffs to the existing validator against the unchanged canonical base-to-full diff.
After the placement pass, accept only when that validator accepts the complete candidate.
Fragment checks guide placement choices but never authorize acceptance by themselves.
Keep its replacement ownership, ordinal pairing, occurrence counts, addition order, and newline checks.
Rotations cannot merge original replacement owners or borrow another region's additions.
The existing `long-insertion-cross-pair` rejection and whole-replacement boundary-deletion allowance remain unchanged.]

#requirement[Use the same validator and rotation retry for split preflight, changed-input revalidation, and advisory `--check-file` comparisons.
Patch application, advisory reply schemas, mode and binary checks, split transport, and exact-tree verification do not change.]

#status[This is a limited retry around the existing validator, not a general shared-alignment solver.
A valid selection requiring unsupported alignment changes may still be rejected.
If none of the tried placements validates, retain the rejection; no completeness guarantee is required.]

= Advisory file checks <agent-jj-split-advisory>

The same wrapper also provides `--check-file` for the Pi commit-boundary
adapter, independently of patch selection and splitting.
The #link("README.md")[operator guide] owns its minimal JSON request and reply
schemas; the #link("../../config/pi-agent/pi-extensions/commit-boundary/design.typ")[commit-boundary design]
owns the adapter's warning, retirement, and write-finalization behavior.

The request contains only an immutable `revision`, a literal workspace-relative
`path`, retained `actual` bytes and executable mode (or null for absence), and
base64 `proposed` bytes. The workspace comes from command cwd, and the single
parent is derived from the revision. The harness owns ordinary JJ snapshot and
immutable ID capture; this producer has no capture mode or persistent record.

`--check-file` performs no snapshot or history mutation. It validates that the
working-copy parent still matches, then reads only the affected path's contents
from the immutable parent and revision through the existing inspection backend.
Per-file reads use an escaped `root-file:` literal pattern; `--` alone does not
disable JJ fileset parsing. This keeps glob and operator characters in filenames
from selecting unrelated contents. It uses the caller's retained actual bytes
and exact proposed bytes, not a newly snapshotted working-copy tree. Temporary
materialization, canonical diff production, and per-file containment reuse the
split preflight implementation.

The current baseline must contain the revision before a proposal can produce a
`would-lose` reply with a concrete rejection reason; an already-lost baseline is
`unusable`. A path without revision changes is `preserved` without containment
comparisons. These are the only semantic statuses: `preserved` permits and keeps,
`would-lose` warns/blocks and forgets, and `unusable` permits and forgets.

This interface supports regular lossless UTF-8 files without NUL bytes and
ordinary creation, preserving absence and executable modes. Unsupported kinds,
binary content, missing revisions, and changed parents are `unusable` comparisons.
Malformed requests and unexpected checker failures instead exit nonzero without
a semantic reply. The producer retains no retry state and writes no checkout
file or shared state; the adapter owns cancellation, target verification,
boundary retirement, and the actual write.

= Agent workflow <agent-jj-split-workflow>

For the normal agent workflow, use the repository wrapper described here; the diff-editor invocation above is the lower-level primitive it drives.

The patch-file agent workflow is a controlled sequence.
Each step is mechanical except the judgment of which hunks belong together.
@agent-jj-split-numbered-hunks specifies an additional way to construct that patch by selecting complete numbered hunks; it does not replace this workflow or change its execution and verification contracts.

#requirement[Before splitting, the agent inspects `jj diff --git -r <revision>` and identifies the behavioral boundary of the desired selected commit.]

#requirement[The selected patch is an ordinary Git-style unified diff containing exactly the hunks for the selected commit.
The agent writes it outside visible source, normally under the repository's ignored `target/jj-split/` workflow area.
The patch is an artifact, not an implicit prompt: it must be possible to inspect it before the split and compare against it after the split.]

#requirement[The normal agent entry point is `bb agent-split target/jj-split/<name>.patch -m 'message' [revision]`.
Agents should use the wrapper instead of interactive `jj split` for patch-level selection.
Automation may pass `--json` to receive only the full selected and remaining change IDs as a JSON object.
The wrapper requests the complete 32-character change-ID representation explicitly.
It discovers the selected commit by matching the original parents, selected tree, and message within the possibly divergent change ID, then discovers the remainder from that unique commit; it does not parse human `jj split` output.]

#example[
```sh
bb agent-split target/jj-split/selected.patch -m 'Extract focused change' @
```
]

#requirement[The wrapper preflights the patch before invoking `jj split`: it parses patch paths, rejects absolute paths and parent-directory traversal, materializes the revision's left and right trees only for paths named in the patch, and dry-runs and applies the patch to an independent left-tree copy.
It checks containment with the local retries in @agent-jj-split-repeated-lines and retains the existing mode and binary checks.
A patch that does not apply cleanly, or whose selected diff is not contained in the original `diff(left, right)`, never reaches Jujutsu.
Containment errors identify the selected parent/base line range or insertion gap and the failed comparison.
They identify the original edit region when applicable; binary and file-mode errors have no invented text coordinates.]

#requirement[The wrapper snapshots the working copy once before preflight.
Native revision-only preflight and verification queries pass `--ignore-working-copy`.
Protected queries use the proxy's inspection request mode without that forbidden caller option;
the trusted executor injects its own working-copy-ignore flag after validation.
Inspection mode remains local to each query; snapshots, structured splits, and descriptions retain mutation authority.
The mutating `jj split` command still snapshots normally, so the working-copy revision uses current workspace bytes.
Preflight reads use one immutable commit, not repeated resolutions of the requested revision.
Stored revisions retain their trees without rescanning unrelated files for every metadata or tree query.]

#requirement[Before invoking `jj split`, the agent and wrapper must ensure no split helper files, selected-patch files, or other workflow artifacts are visible to Jujutsu's working-copy snapshot.
`target/jj-split/` must be ignored, and any patch or helper path inside the repository must be contained there.
Artifacts in visible source are a workflow bug because `jj split` snapshots the working copy before it invokes the diff editor.]

#requirement[The wrapper runs `jj split --tool agent-split -m 'message' -r <revision>` with `JJ_AGENT_SPLIT_PATCH` pointing at the selected patch.
The `-m` argument is mandatory for this workflow because it prevents a selected-commit message editor from opening.]

#requirement[If the remaining commit needs a description, the agent passes `--remaining-message 'Keep unrelated cleanup'` to the wrapper.
The wrapper describes the discovered remainder before post-split verification completes, without opening a commit-message editor.]

#requirement[After the split, the wrapper verifies resulting trees rather than comparing textual diff fragments.
The selected tree must equal the left tree with the supplied patch applied, and the original remainder's tree must equal the actual split input.
Selected-tree verification materializes only paths named in the patch and rejects any selected changes outside those paths with a revision-wide changed-path check.
Remainder verification compares the complete trees, including all unselected paths.
Jujutsu's selected-commit evolution entry identifies the exact input predecessor and split operation.
The remainder's evolution entry from that same operation identifies its immutable output, even after later working-copy snapshots.
If the input tree changed after preflight, containment is rechecked against that input; changed selected source fails verification even when a protected editor applied the patch.
This preserves concurrent unselected edits, duplicate lines, and changes whose textual hunks are normalized differently by Jujutsu or Git.
The agent should then inspect `jj status` and the relevant `jj diff --git -r <selected>` and `jj diff --git -r <remaining>` output before committing or continuing.]

#requirement[Preflight, split execution, and post-split verification failures use distinct exit statuses 1, 2, and 3.
Verification failures leave the split intact; the wrapper never automatically restores an earlier operation.
An operation-wide restore can erase another writer's work even when the last freshness check saw no concurrent edits.
Native failures report the preflight operation for investigation, not as an instruction to restore it.
Post-split failures include all known selected and remaining change and commit IDs, and the actual input commit when available.
Unavailable identities are marked explicitly.
Selected patch mismatches, remainder mismatches, and observed concurrent edits have distinct diagnostics.
It must not silently continue with a bad history boundary.]

#requirement[If the requested patch and message already describe the selected revision, the wrapper rejects the duplicate split before mutation.
When that revision has exactly one child, the diagnostic names it as the possible continuation without assuming that the child is semantically the original remainder.]

== Numbered-hunk listing and selection <agent-jj-split-numbered-hunks>

This interface lets an agent inspect complete numbered diff hunks and select them by ID, without hand-editing a patch or writing a selection script.
Selection constructs an ordinary patch and then enters the existing preflight, split, verification, routing, and recovery workflow.
It does not determine authorship or whether selected edits are behaviorally coherent.

#status[Numbered-hunk listing and selection are implemented and exercised in disposable native repositories and the structured protected-backend fixture.
The existing patch-file command and `--check-file` API remain available.
Canonical path encodings unsupported by the shared patch parser are reported without selectable IDs.]

=== Listing

```sh
bb agent-split list [--json] [--path <literal-path>]... [revision]
```

The revision defaults to `@` and must resolve to one revision supported by the existing splitter.
Resolve it through the existing native/protected router.
For a moving selector such as `@`, take the existing authoritative workspace snapshot once before resolving the source commit.
An explicit full immutable commit ID uses inspection reads without a workspace snapshot.
Listing may update recorded working-copy state, but does not edit source files or split a change.

Each listing identifies the full immutable source commit ID and its change ID, then displays numbered hunks with complete unified-diff content: ranges, unchanged context, additions, and removals.
Global IDs follow canonical path order and source hunk order.
Repeatable `--path` filters take literal workspace-relative paths; they filter displayed output, not numbering or source identity.
A path outside the workspace or absent from the source diff is an error.
An empty revision yields an empty catalog and cannot produce a split.
Listing creates no persistent catalog file.

`--json` emits a structured catalog with `version`, `source_commit`, `source_change`, `hunks`, and `unsupported`.
Hunk records include global `id`, literal `path`, parent and source ranges, and full hunk text; top-level fields identify active display filters.
The parent is derived from the source commit and is not a separate listing or JSON field.
Use stderr for progress and diagnostics, with no ANSI or prose mixed into JSON.

=== Complete interaction

The following illustrative excerpt shows two complete hunks from a filtered listing; other hunks are omitted, so the IDs may have gaps.

```text
source commit: <full immutable commit ID>
change: <full change ID>

[hunk 12] config/agents/shared-agents.md
@@ -125,6 +125,13 @@ Before selecting a substantial approach
 An agent choice in a spec is not new approval.
 Ask only about unresolved trade-offs or context that could change the approach; routine choices within the authorized task do not require a discovery interview.
 
+### Before expanding repeated work
+
+Before repeating an uncertain approach across many items, complete a small representative case and check its result against the intended outcome.
+Choose a case that can expose weaknesses in the approach, not merely the easiest case.
+Use that feedback to decide whether to expand, revise, or stop.
+Reuse applicable evidence when the approach is already established; do not add a pilot or human approval step by default.
+
 ### Before changing behavior or scope
 
 Check for additional missing context when a decision changes behavior, scope, ownership, or preservation requirements.

[hunk 37] skills/work-selection/SKILL.md
@@ -42,6 +42,17 @@ Keep feedback fast
 Aim for actionable development feedback within about two minutes unless the user or task establishes another budget.
 This is a threshold for reconsidering the approach, not a universal command timeout or permission to weaken acceptance.
 
+### Test an uncertain approach before expanding
+
+When an uncertain approach will be repeated across many items, identify the assumption that could make repeating it wasteful or wrong.
+Choose the smallest representative case whose result can challenge that assumption.
+Before starting, state which results would justify expanding, revising, or stopping the approach.
+Check the result against the intended outcome, not merely whether the prescribed steps completed.
+Use existing applicable evidence instead of repeating an established check.
+
+For example, before migrating many callers, try one that exercises the uncertain compatibility behavior and check it through its intended consumer.
+For a prose rewrite, have a fresh reader follow one complete workflow; easier scanning alone does not establish that the explanation works.
+
 ### Reassess choices in flight
 
 Apply this reassessment to work already underway, not only proposed work.
```

Select both hunks from the immutable source commit shown by the listing.

```sh
bb agent-split --from <full-source-commit-id> --hunks 12,37 \
  -m 'Check uncertain approaches before expanding repeated work' --json @
```

The illustrative result retains the existing selected/remaining JSON shape.

```json
{"selected":"<selected change ID>","remaining":"<remaining change ID>"}
```

=== Selection

```sh
bb agent-split --from <full-source-commit-id> --hunks <ids> \
  -m <message> [-m <message> ...] [revision]
```

`--from` is the full immutable source commit ID printed by the listing, not a view token, catalog digest, change ID, abbreviation, bookmark, or moving revision expression.
It binds the inspected tree and its parent; derive the parent internally.
The final optional revision is the target to split now and defaults to `@`.

`--hunks` accepts comma-separated positive decimal IDs and inclusive ranges, such as `2,5-8,12`.
Reject zero, unknown IDs, empty elements, reversed ranges, and duplicate or overlapping selections.
Normalize valid selections to catalog order.
Require both `--from` and `--hunks`; do not combine them with a patch-file operand.
Preserve `--json`, `--remaining-message`, repeated message paragraphs, the revision default, and `--` termination.
Validate arguments and resolve the source before invoking a split.
There is no implicit select-all, automatic retry against a newer source, or ownership inference.

Dispatch `list` only as that exact command token; a legacy patch file named `list` remains addressable as `./list`.
Successful selection retains the current success JSON (`selected` and `remaining` change IDs); existing consumers need no migration.

=== Supported selection and source changes

The first version selects complete hunks in ordinary modified UTF-8 regular files with unchanged file mode and kind.
Nearby edits grouped into one hunk are selected together, and the full hunk shown in the listing makes that boundary visible.
List creations, deletions, mode changes, binary changes, renames, and other unsupported file operations explicitly by path and kind, without selectable hunk IDs.
Do not silently omit them or partially select their text; direct callers to the existing patch-file interface.
Sub-hunk IDs, whole-file operation IDs, and automatic ownership selection are not first-version requirements.

Build numbering from the same materialized parent/source data and canonical Git diff producer used by containment, with producer options that affect hunk boundaries fixed rather than inherited from user diff configuration.
Retain exact parsed headers and payloads; listing and selection use the same producer and numbering rules.
Numbering compatibility across arbitrary future diff-engine versions is not promised: after changing the diff-producing tool version, list the source commit again before selecting IDs.

Reconstruct the source catalog without rereading moving selectors, then take the existing preflight snapshot and resolve the requested target.
Require its change ID and parent commit to match the source commit's change and parent.
If the target has been committed or rebased, refuse and request a new listing.
The target commit ID need not equal the source commit ID: new unselected edits may proceed if generated selection passes existing dry-run and containment checks.
Always use the originally selected bytes, never similarly numbered latest hunks.

The preflight check does not make the operation atomic.
Preserve existing native-editor and protected-proxy behavior: validate the actual split input, verify the selected tree and complete remainder, and report concurrent changes.
A protected execution may detect a selected-source race only after splitting, return exit 3, and leave the split intact.
This extension adds no lock, polling, automatic rollback, or stronger concurrency guarantee.

=== Diagnostics and implementation boundary

Listing and preflight errors use exit 1; split and verification failures retain exits 2 and 3.
Preserve existing known-revision and recovery diagnostics.
Errors identify the failed decision and next action—for example, unknown IDs refer to selectable IDs in the source catalog, and an invalid `--from` directs the caller to the full source commit ID printed by `list`.
A changed target parent directs the caller to list the target again.
A failed reconstruction or mismatch must not fall back to a fresh moving diff.

Add a catalog producer and whole-hunk selector alongside the existing `execute-main` → `preflight!` → `run-split!` → split discovery and `verify!` path in `tools/agent-split/src/scripts/agent-split.clj`.
The producer returns source identities and exact diff records; the selector emits an ordinary patch with each selected file header once and selected hunks in order, retaining context and newline markers needed by existing checks.
Do not copy unselected hunk payloads, stale whole-blob index metadata, or file-operation headers that imply unsupported selection.

Refactor only enough orchestration to accept either an existing patch path or a generated patch.
Generated artifacts use a fresh ignored path under `target/jj-split/` and existing snapshot-safety and artifact lifecycle behavior.
Do not recursively invoke the public wrapper and take a second snapshot.
No new daemon, proxy protocol, dependency, persistent selection registry, or change to the edit-boundary adapter is required.
Listing may read every changed path for global IDs; path filters initially reduce output only.
Do not add a cache before measuring that cost against a simpler scoped-catalog design.

First delivery should establish the interface in a disposable repository with two text files and four hunks: list once, select two nonadjacent IDs, and verify the selected tree contains exactly those hunks while the complete remainder preserves everything else.
Then test repeated lines, overlapping context, missing terminal newlines, earlier unselected edits changing line counts, literal paths, stable filtered IDs, invalid selectors and input modes, consistent numbering under different user diff configuration, unrelated versus selected concurrent edits, committed/rebased targets, native and protected post-preflight races, visible unsupported operations, and unchanged legacy patch, message, JSON, and `--check-file` behavior.
Use existing unit, real-repository integration, structured proxy, and containment fixtures under `tools/agent-split/tests/`.

== Worked two-hunk example <agent-jj-split-worked-example>

This example splits two unrelated hunks in one file without opening a TUI.
The original working-copy commit contains both a helper rename and an unrelated diagnostic text change in `src/flower/example.clj`.
The selected commit should contain only the helper rename.

#example[
```sh
jj diff --git -r @ src/flower/example.clj
```
]

The diff shows two hunks in the same file:

#example[
```diff
diff --git a/src/flower/example.clj b/src/flower/example.clj
--- a/src/flower/example.clj
+++ b/src/flower/example.clj
@@ -3,2 +3,2 @@
-(defn render-item [item]
+(defn render-entry [item]
   [:li (:title item)])
 
@@ -18 +18 @@
-(throw (ex-info "Bad item" {:item item}))
+(throw (ex-info "Invalid item" {:item item}))
```
]

The agent writes only the first hunk to an ignored patch artifact:

#example[
```sh
mkdir -p target/jj-split
cat > target/jj-split/render-entry.patch <<'PATCH'
diff --git a/src/flower/example.clj b/src/flower/example.clj
--- a/src/flower/example.clj
+++ b/src/flower/example.clj
@@ -3,2 +3,2 @@
-(defn render-item [item]
+(defn render-entry [item]
   [:li (:title item)])
PATCH
```
]

Before splitting, the agent checks snapshot safety:

#example[
```sh
git check-ignore -q target/jj-split/render-entry.patch
jj status
```
]

`jj status` must not show `target/jj-split/render-entry.patch` or any helper artifact.
If it does, the agent stops and moves the artifact under an ignored workflow path before splitting.

The split uses the repo-supported wrapper:

#example[
```sh
bb agent-split target/jj-split/render-entry.patch -m 'Rename render item helper' @
```
]

The wrapper preflights the patch, invokes `jj split --tool agent-split -m 'Rename render item helper' -r @` with `JJ_AGENT_SPLIT_PATCH` set to the patch file, and verifies that the selected commit matches the patch while the remaining commit keeps the diagnostic text change.
If the remaining commit description should change, the fixup is also non-interactive:

#example[
```sh
jj describe -r <remaining> -m 'Clarify invalid item diagnostic'
```
]

The agent then verifies both sides explicitly:

#example[
```sh
jj diff --git -r <selected>
jj diff --git -r <remaining>
jj status
```
]

= Validation <agent-jj-split-validation>

The shim can only be trusted if it makes the selected state observable.

#requirement[Before invoking `jj split`, the workflow must be able to show the exact selected patch.]

#requirement[After `jj split`, the workflow must compare the selected commit's diff against the selected patch or an equivalent normalized representation.]

#requirement[The workflow must run the relevant tests or lint gates after history is rearranged when the split changes what will be committed or reviewed separately.]

#rationale[Patch application success proves only that the selected tree can be constructed.
It does not prove the right change was selected.
The post-split comparison catches wrong hunks, missing adjacent lines, and accidental path inclusion.]

== Materialized expected revision <agent-jj-split-expected-revision>

The implemented wrapper materializes the expected selection in independent temporary filesystem trees, without creating or restoring repository revisions.
The following alternative requires an isolated disposable repository; it is unsafe in a shared checkout.
A wrapper could materialize the selected patch as a temporary Jujutsu revision before the real split.
It records the current operation, creates a new revision from the split base, applies the selected patch there, validates that revision, and then restores the original operation before invoking `jj split`.
This is useful for preflight validation even if the temporary revision is discarded before the real split.

#example[
```sh
op="$(jj op log --limit 1 --no-graph -T 'id.short()')"
jj new "$base" -m 'expected selected split'
git apply "$JJ_AGENT_SPLIT_PATCH"

# validate expected against the original revision here
jj op restore "$op"
```
]

#requirement[A materialized expected revision is an implementation aid, not a substitute for containment validation.
The wrapper must still reject selected changes that are not present in the original revision being split.
A pure deletion covering whole replacement regions may include their immediately adjacent empty context lines, including empty CRLF lines.
This accounts for Git retaining section separators as context while a selected section deletion removes them.
It does not authorize deleting space-only lines, unrelated anchors, excess consecutive blank lines, or borrowing another region's additions.]

#requirement[`jj interdiff` is appropriate for equality checks between two materialized revisions that are both addressable in the same Jujutsu operation.
A wrapper that keeps an expected selected revision alive until after the real split may compare it with the actual selected commit using `jj interdiff --from expected --to actual-selected --git`, and require no patch difference.
A wrapper that restores or undoes the temporary revision before the real split must instead compare the actual selected commit against a saved normalized diff or recreate the expected revision before running `jj interdiff`.]

#rationale[`jj interdiff` compares what two revisions do as patches, which avoids brittle byte-for-byte comparison of raw patch text.
It is useful once the selected patch has been turned into a revision.
It does not, by itself, prove that the selected patch is contained in the original revision: an interdiff between the selected revision and the full original revision also includes the unselected remainder, and can mix that with corrections for invented selected content.
Containment remains a separate check.]

= Failure modes <agent-jj-split-failure-modes>

== Patch does not apply

The wrapper rejects an apply failure during preflight with exit status 1, before invoking Jujutsu's split command.
The initial working-copy snapshot can still occur, but no split revisions are created.
The agent regenerates selected hunks from the target revision's Git-format diff, preserving unchanged context from its parent.

If apply fails inside the diff editor instead, Jujutsu aborts that split attempt and the wrapper exits with status 2.
The agent inspects repository state before retrying.

== Patch introduces changes not in the revision

The wrapper rejects this during preflight with exit status 1, before invoking Jujutsu's split command.
The same initial-snapshot caveat described above applies.
A patch that applies to the left tree but introduces an edit not contained in the full revision is stale or wrong;
accepting it would create a selected commit Jujutsu can only compensate for in the remaining commit.
This is a claim about selected edits, not a requirement that every selected-file line appear in the full version: unselected removals can leave old base lines in the selected file.
The agent rewrites the patch from the current `jj diff --git` output and tries again.

== Split artifact enters the working copy

This is a workflow bug.
`jj split` snapshots the working copy before it invokes the diff editor, so repository-local patch files or helper scripts can become part of the revision being split.
The workflow must keep those artifacts under the ignored `target/jj-split/` directory or otherwise invisible to the snapshot.

== Patch selects part of an inseparable hunk

The tool may apply, but post-split verification or tests may reveal that the selected commit is not coherent.
The agent should either include the necessary adjacent edits or choose a different commit boundary.

== Patch overlaps generated files

Generated files should usually be split with the source change that produces them, or regenerated after the split.
If generated output cannot be reconstructed deterministically, the agent should avoid patch-level splitting that separates source and generated output.

== Description editor opens

This is a workflow bug.
The command must pass `-m` or otherwise configure a non-interactive editor for the selected commit description.
If the remaining commit needs a different description from the original revision, the workflow must run a separate non-interactive `jj describe` after the split.
The diff-editor shim solves patch selection, not commit-message editing.

== Right tree replacement fails

The tool exits non-zero.
Partial right-tree writes must not be accepted as a successful split.

= Non-goals <agent-jj-split-non-goals>

#requirement[The tool does not decide which hunks belong together.
That remains the agent's judgment.]

#requirement[The tool does not replace `jj split` or reimplement Jujutsu history rewriting.]

#requirement[The tool does not provide a general patch queue, staging area, or commit planner.]

#requirement[The tool does not make arbitrary TUI tools safe for agents.]

= Interface decisions <agent-jj-split-open-questions>

These three questions are now decided.

#requirement[The selected patch always lives under `target/jj-split/` at a fresh invocation-specific path named by `JJ_AGENT_SPLIT_PATCH`.
There is no blessed predictable filename.]

#rationale[A fixed predictable filename is the same artifact across successive splits, so a stale patch from an earlier split can be silently reused.
An explicit per-invocation environment variable makes the patch's identity and lifetime obvious and forces the caller to name a fresh artifact each time.
Debuggability is preserved because the path is a real file the workflow can show before and after the split (@agent-jj-split-validation);
it is just scoped under the repository's ignored split-artifact directory.]

#requirement[The shim does not accept a patch on stdin.
The selected patch is always a file referenced by `JJ_AGENT_SPLIT_PATCH`.]

#rationale[Post-split verification compares the selected commit against the selected patch (@agent-jj-split-validation).
A stdin patch is consumed once and is not naturally preserved for that comparison or for retries after a failed apply.
Requiring a file keeps the patch re-readable for the entire workflow.]

#requirement[The repository provides a blessed `bb agent-split` wrapper on top of the diff-editor shim.
The wrapper validates the patch (clean apply against the left tree and containment in `diff(left, right)`), checks that no workflow artifacts are visible to the working-copy snapshot, invokes `jj split --tool agent-split -m ...`, and verifies both resulting commits.
The lower-level `jj-agent-split-editor` shim remains the primitive the wrapper drives;
callers may still invoke the shim directly for one-shot use.]

#rationale[The validation and verification steps in @agent-jj-split-workflow and @agent-jj-split-validation are mechanical and easy to skip under time pressure.
Folding them into one command removes the most likely agent mistakes — forgetting containment validation, leaking the patch file into the snapshot, or skipping the post-split diff comparison — while leaving the shim usable on its own.]

= Acceptance criteria <agent-jj-split-acceptance>

A first implementation is acceptable when:

- an agent can split two unrelated hunks in the same file into separate commits without opening an interactive editor,
- malformed, stale, or out-of-revision selected patches abort before changing history,
- the selected commit after split matches the supplied patch,
- the remaining commit retains the unselected changes,
- the selected commit description can be supplied without opening an editor, and any remaining-commit description fixup is handled non-interactively,
- the workflow is documented well enough that an agent can follow it without visual terminal interaction.

== Repeated-line rotation retry <agent-jj-split-rotation-acceptance>

The retry in @agent-jj-split-repeated-lines is acceptable when:

- the blank-line form of the minimal example above is accepted without moving or changing the selected text;
- the repeated nonempty-line example above is accepted, so support is not restricted to blank separators;
- left and right rotations of insertion and deletion blocks reconstruct the same selected bytes and stop at the stated boundaries;
- retries terminate on repeated-line runs without requiring an exhaustive search of placement combinations;
- multiple selected fragments share one occurrence accounting, rejecting reused additions, extra duplicates, reordering, unrelated-occurrence deletion, and cross-paired replacements;
- CRLF, space-only lines, terminal empty lines, and missing final newlines retain their exact bytes rather than receiving whitespace-specific equivalence;
- the existing containment decision-table expectations remain intact, including the explicitly supported whole-replacement boundary deletions;
- native split preflight and advisory `--check-file` cover both valid alignment changes and invalid cross-region selections, and post-split revalidation uses the same decision owner;
- a successful split still produces the exact supplied selected tree and preserves the complete actual split-input tree in the remainder.

The shared decision table and native split and advisory tests cover this retry.
Compiling the specification alone does not establish containment behavior.
