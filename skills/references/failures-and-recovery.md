# Failures and recovery

Read when catching errors, choosing defaults or fallback, cleaning up, retrying, publishing, or recovering interrupted work.
For optional configuration, also check [absence semantics](data-and-effects.md#represent-shared-data-precisely).

## Catch and fall back narrowly

Branch or catch only for the failure the contract permits to fall back.
Missing configuration may use a default; malformed configuration or permission denial must not silently become “missing.”
Use the narrowest exception type or structured error condition that represents that case and propagate unrelated failures.
Use structured error fields, parser metadata, or diagnostics when available; do not parse human-readable messages to recover those values.
When writing user-facing errors, follow [diagnostic design](diagnostic-design.md#state-the-known-failure) for naming the violated rule and separating diagnosis from repair.

Prefer scoped resource cleanup or a `finally`-style construct over cleanup that runs only in a catch path.
Preserve the original failure if best-effort cleanup also fails, while reporting material cleanup status.
When suppressing a failure or using an exceptional mechanism, make the reason and preserved contract discoverable beside the choice.
A comment cannot justify an unnecessarily broad catch or a clamp that hides invalid input.

## Substitute only equivalent behavior

When a requested or selected mechanism proves unavailable, compare the fallback with the required observable behavior before implementing it.
State which guarantees it preserves, changes, or leaves unverified, including applicable precedence, persistence, ownership, and failure behavior.
Apply the [shared scope rule](~/.agents/shared.md#before-changing-behavior-or-scope) to any changed guarantee outside existing authorization.
Pause dependent implementation until that decision is resolved; continue independent investigation.
An equivalent implementation within the authorized behavior does not need renewed approval.

For example, loading a configuration profile and passing its values as overrides can both select the expected approval reviewer.
If overrides also change precedence over project configuration, passing reviewer tests does not establish equivalence or authorize that change.
During review, check the precedence requirement even when those tests pass.

## Partial failure and recovery

Trace failures between effects and acknowledgments, including remote success with a lost response.
Establish the applicable outcomes, retry conditions, cleanup, and recovery authority in the owning contract.
The recovery owner needs evidence distinguishing failure from unknown outcome; a caller error alone cannot justify retry, transactions, or compensation.

For queued work, locate each occurrence's recoverable payload through selection, processing, persistence, and handoff.
Include selected-but-uncommitted batches and failure between transfer and notification.
Preserve the payload until commit, transfer, or explicit consumption/discard; an error report is not a discard.

For reconstruction, follow required distinctions through serialization and restoration.
Rebuilding titles and bodies can reset comment dates or omit relationships despite successful import and matching counts.
Compare supported recovery with reconstruction through a narrower model.
Verify restoration without the original store or caches supplying missing data.
An intentionally lossy import need preserve only what its contract promises, not byte identity.

## Diagnosability

Identify who must understand an unsuccessful operation and their safe next action.
Trace required evidence from effect owner to recovery owner without exposing sensitive data.
Distinguish pending work, failure, committed effects, and unknown outcomes so “request failed” cannot imply that repeating an effect is safe.
Use existing errors, status queries, or records when sufficient.

When presenting these outcomes in a command-line interface, follow [CLI output guidance](cli-design.md#human-output-and-automation).
