#import "style.typ": apply-settings, requirement, rationale, status, invariant, open-question, takeaway, example
#show: apply-settings

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

#status[design only.
No implementation is defined in this repository yet.
The intended implementation is a small executable plus workflow documentation for agents.]

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

The proposed tool, `jj-agent-split-editor`, is a non-interactive diff editor.
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

== Example invocation <agent-jj-split-example>

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

rsync -a --delete "$tmp"/ "$right"/
```
]

This sketch is deliberately small.
A production tool should add validation before and after `git apply`.

#requirement[The production tool must reject absolute paths, parent-directory traversal, and paths outside the Jujutsu-provided tree.]

#requirement[The production tool must perform a dry-run apply before mutating the temporary tree, and report the failing path and hunk when possible.]

#requirement[The production tool must validate parsed patch paths before invoking `git apply`;
it must not rely on `git apply` or shell path normalization as the only traversal check.]

#requirement[The production tool must compare `diff(left, patched-left)` with the original `diff(left, right)` and reject any selected change that was not present in the revision being split.]

#requirement[The production tool must replace the right tree atomically enough that a failed copy cannot be mistaken for a successful editor run.
If the platform cannot make the replacement atomic, the tool must exit non-zero on any copy failure.]

#requirement[The production tool must preserve executable bits and symlinks according to the patch format and the copied tree.]

#requirement[The production tool should print a compact summary of selected files and hunk counts before exiting zero.]

= Agent workflow <agent-jj-split-workflow>

The agent workflow is a controlled sequence.
Each step is mechanical except the judgment of which hunks belong together.

#requirement[Before splitting, the agent inspects `jj diff` for the revision being split and identifies the behavioral boundary of the desired selected commit.]

#requirement[The agent writes the selected patch to a temporary file outside the repository being split.
The patch is an artifact, not an implicit prompt.
It can be reviewed, stored, or discarded.]

#requirement[The agent checks the patch against a copy of the left tree before invoking `jj split`.
A patch that does not apply cleanly, or whose selected diff is not contained in the original `diff(left, right)`, never reaches Jujutsu.]

#requirement[Before invoking `jj split`, the agent ensures no split helper files, selected-patch files, or other workflow artifacts are visible to Jujutsu's working-copy snapshot.]

#requirement[The agent runs `jj split --tool agent-split -m 'message'` with `JJ_AGENT_SPLIT_PATCH` pointing at the selected patch.]

#requirement[After the split, the agent verifies both resulting commits with `jj diff` or `jj show`: the selected commit contains only the intended hunks, and the remaining commit still contains the rest.]

#requirement[If verification fails, the agent restores the Jujutsu operation or performs another explicit corrective split.
It must not silently continue with a bad history boundary.]

= Validation <agent-jj-split-validation>

The shim can only be trusted if it makes the selected state observable.

#requirement[Before invoking `jj split`, the workflow must be able to show the exact selected patch.]

#requirement[After `jj split`, the workflow must compare the selected commit's diff against the selected patch or an equivalent normalized representation.]

#requirement[The workflow must run the relevant tests or lint gates after history is rearranged when the split changes what will be committed or reviewed separately.]

#rationale[Patch application success proves only that the selected tree can be constructed.
It does not prove the right change was selected.
The post-split comparison catches wrong hunks, missing adjacent lines, and accidental path inclusion.]

== Materialized expected revision <agent-jj-split-expected-revision>

A wrapper may make validation easier by materializing the selected patch as a temporary Jujutsu revision before the real split.
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
The wrapper must still reject selected changes that are not present in the original revision being split.]

#requirement[`jj interdiff` is appropriate for equality checks between two materialized revisions that are both addressable in the same Jujutsu operation.
A wrapper that keeps an expected selected revision alive until after the real split may compare it with the actual selected commit using `jj interdiff --from expected --to actual-selected --git`, and require no patch difference.
A wrapper that restores or undoes the temporary revision before the real split must instead compare the actual selected commit against a saved normalized diff or recreate the expected revision before running `jj interdiff`.]

#rationale[`jj interdiff` compares what two revisions do as patches, which avoids brittle byte-for-byte comparison of raw patch text.
It is useful once the selected patch has been turned into a revision.
It does not, by itself, prove that the selected patch is contained in the original revision: an interdiff between the selected revision and the full original revision also includes the unselected remainder, and can mix that with corrections for invented selected content.
Containment remains a separate check.]

= Failure modes <agent-jj-split-failure-modes>

== Patch does not apply

The tool exits non-zero.
Jujutsu aborts the split.
The agent rewrites the patch from the current diff and tries again.

== Patch introduces changes not in the revision

The tool exits non-zero.
A patch that applies to the left tree but produces content not present in the original right tree is stale or wrong;
accepting it would create a selected commit Jujutsu can only compensate for in the remaining commit.
The agent rewrites the patch from the current `jj diff --git` output and tries again.

== Split artifact enters the working copy

This is a workflow bug.
`jj split` snapshots the working copy before it invokes the diff editor, so repository-local patch files or helper scripts can become part of the revision being split.
The workflow must keep those artifacts outside the repository or otherwise invisible to the snapshot.

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

= Open questions <agent-jj-split-open-questions>

#open-question[Should selected patches be stored in a predictable external path, or always in an arbitrary temporary path named by `JJ_AGENT_SPLIT_PATCH`?
A predictable path improves debuggability;
an explicit environment variable reduces accidental reuse.]

#open-question[Should the shim accept a patch on stdin?
That would make one-shot use convenient, but it complicates retries and post-split verification because the selected patch is less naturally preserved.]

#open-question[Should the repository provide a blessed `bb jj-split-patch` wrapper that performs patch validation, invokes `jj split`, and verifies the result?
That would reduce agent mistakes, but it introduces a maintained workflow tool rather than only a diff-editor shim.]

= Acceptance criteria <agent-jj-split-acceptance>

A first implementation is acceptable when:

- an agent can split two unrelated hunks in the same file into separate commits without opening an interactive editor,
- malformed, stale, or out-of-revision selected patches abort before changing history,
- the selected commit after split matches the supplied patch,
- the remaining commit retains the unselected changes,
- the selected commit description can be supplied without opening an editor, and any remaining-commit description fixup is handled non-interactively,
- the workflow is documented well enough that an agent can follow it without visual terminal interaction.
