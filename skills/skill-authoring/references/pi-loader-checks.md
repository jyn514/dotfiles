# Pi loader checks

Read this reference when a discovery change requires a Pi loader check, or when investigating Pi skill loading.

Prefer `validate_skill` when available.
Confirm the expected name loaded and inspect all diagnostics.
This checks the explicit file, not normal discovery precedence or interactive startup.
Otherwise, check the installed CLI options and load the skill from a discoverable location in a normal Pi session;
inspect startup diagnostics and `/skill:<name>`.
Run `/reload` after edits in an active session.
If that session is unavailable, report the missing check.
