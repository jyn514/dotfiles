---
name: commit-quality
description: Write or review commit messages and prepare a finished change for commit. Use whenever creating a commit, proposing its message, or judging commit-message quality.
---

# Commit Quality

Write commit messages for the next person debugging or reviewing the change, not merely to label the diff. Use a concise imperative subject naming the affected behavior.

When the diff does not make the reason, failure mode, constraints, or verification obvious, add a body explaining:

- the user-visible or operational problem;
- why the previous behavior was wrong;
- the important design choice or constraint behind the fix;
- how the change was verified, especially for regressions or security boundaries.

Record what a reader would otherwise have to reconstruct; do not narrate files or repeat the subject.

For bug fixes, describe the causal chain, not just the symptom. For tests, say what regression they would have caught. For security changes, state which authority is granted or restricted and why the boundary remains safe.

Before committing, inspect the complete diff and write the message from the finished change.

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
