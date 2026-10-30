---
name: commit-quality
description: Write or review commit messages, split work into atomic commits, and prepare a finished change for commit. Use whenever creating commits, deciding commit boundaries, proposing messages, or judging commit quality.
---

# Commit Quality

Write for the next person who will debug or review the change. Use a concise, imperative subject that names the affected behavior; do not merely label the diff.

If the diff does not make the reason, failure mode, constraints, or verification obvious, explain the relevant points in the body:

- the user-visible or operational problem;
- why the previous behavior was wrong;
- the important design choice or constraint behind the fix;
- verification only when it records non-obvious evidence, an unusual test boundary, or a material limitation.

Record only what a reader would otherwise have to reconstruct. Do not narrate files or repeat the subject. Do not append a routine `Verification:` section or command list. Ordinary test, lint, and formatting results belong in the review report or CI record, not the commit message.

For bug fixes, describe the causal chain, not just the symptom. For tests, say what regression they would have caught. For security changes, state which authority is granted or restricted and why the boundary remains safe. Mention verification when it establishes something durable and non-obvious, such as a production reproduction, migration result, compatibility limit, or test environment that future readers might otherwise assume was covered.

Before committing, inspect the complete diff. Then write the message to describe the finished change.

## Atomic commits

Partition the owned diff by purpose before committing. Each commit should be independently coherent: it establishes one behavior, invariant, migration step, or policy change and includes the tests and documentation needed to make that result complete.

Do not confuse atomic with small. Keep inseparable behavior, tests, generated artifacts, and user-facing documentation together. Separate changes that can be reviewed, reverted, or explained independently; never absorb unrelated pre-existing work merely to leave a clean working tree.

For files with pre-existing edits, use [jj-workflow's split procedure](../jj-workflow/SKILL.md#split-or-restore) to commit only your changes.

Order commits so every intermediate revision is valid under the repository's required checks. Preparatory refactors must be useful and behavior-preserving on their own, not incomplete pieces whose only justification appears in a later commit.

## Paragraph breaks

Pass each paragraph as a separate `-m` argument so Jujutsu inserts real blank lines:

```bash
jj commit path/to/file \
  -m 'Fix clipboard publication' \
  -m 'Explain the failure mode and design choice.' \
  -m 'Record any verification that matters later.'
```

Do not write `-m 'First paragraph.\n\nSecond paragraph.'`; ordinary shell quotes preserve `\n` literally. When constructing one message dynamically, generate actual newline bytes and pass the result as one quoted argument:

```bash
message=$(printf '%s\n' 'Subject' '' 'First paragraph.' '' 'Second paragraph.')
jj commit path/to/file -m "$message"
```

After committing, inspect `description.escape_json()` when exact whitespace matters; real paragraph breaks appear as `\n\n`, while accidental literal backslashes appear as `\\n\\n`.
