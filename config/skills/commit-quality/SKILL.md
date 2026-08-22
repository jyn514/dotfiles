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
