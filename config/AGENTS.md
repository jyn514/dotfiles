# Guidelines

## File patch editing

- An interrupt in the middle of an edit does not roll back changes already written; those changes remain saved on disk.
- Hand-write small patches.
- Default to one file per `apply_patch` call; combine files only for trivial related edits.
- For large mechanical moves, such as splitting a file or moving unchanged sections, do not hand-write a long patch.
  Instead, generate it programmatically:
  1. Read the source file.
  2. Use an in-memory script to construct the `apply_patch` text.
     Do not let the generator write files directly.
  3. Send the generated text to apply_patch.
  4. Inspect the final diff to verify that no content was lost or changed unintentionally.

Programmatically generated patches are allowed to have multiple files per `apply_patch` call.

## Subagents

When using subagents:
- `wait_agent` waits for final agent status; it is not a general message poll.
- Do not treat a `wait_agent` timeout as proof that the subagent ignored a message.
- When only final status is needed, use one long `wait_agent` call.
  If periodic polling is necessary, use a minimum of 60 seconds -- 120 seconds is better. Do *not* poll every few seconds, it burns context tokens.
- If you need a status report before the subagent is done, ask her to pause, stop editing, return a final status report, and wait for further instructions.
- Prefer that pause-and-report pattern before interrupting or reclaiming work, unless the subagent is outside scope, blocking coordination, or leaving the workspace in a dangerous state.

## Commands and permissions

`$''` bash strings always require sandbox approval due to a harness limitation. Prefer simpler syntax, or writing temporary files.
