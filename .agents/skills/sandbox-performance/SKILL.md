---
name: sandbox-performance
description: Diagnose and reduce startup, interactive-readiness, or cleanup latency in this repository's Codex sandbox and Pi launcher. Use for sandbox timing breakdowns, repeated startup benchmarks, proxy or TicGit latency, post-preparation delay, and proposals to remove or consolidate sandbox runtime work. Do not use for ordinary sandbox correctness bugs without a performance symptom.
---

# Sandbox performance

Find the user-visible critical path, remove unnecessary work from it, and prove the improvement with comparable runs.
Preserve required sandbox behavior; a faster internal span is not enough.

## Establish the measured outcome

Before changing code, name the boundary that matters:

- **Launcher preparation:** command entry through `Sandbox preparation`.
- **Interactive startup:** command entry to the first usable Pi frame.
- **Cleanup:** final Pi output to shell control.
- **Component regression:** a named service span.

Use command entry to the first usable Pi frame unless the user names another boundary.
Do not optimize a nested phase as a proxy for the user-visible outcome without measuring both.

Read [the startup measurement guide](../../../tools/codex-sandbox/development.md#measure-interactive-startup) before benchmarking.
Read [startup terminal ownership](../../../tools/codex-sandbox/development.md#startup-terminal-ownership) before changing launcher stdio, attach behavior, or process ownership.

## Measure before selecting a change

For phase attribution, run `env CODEX_SANDBOX_TIMING=1 pi`.
For comparable first-frame measurements, use the repository's interactive startup probe.

Do not wrap that probe in `dev/test-environment`.
It intentionally uses installed configuration, caches, authentication, and the host container runtime.

Set the temporary directory for the probe by platform:

- Linux: `TMPDIR=/tmp`.
- macOS: `TMPDIR=/private/tmp`.

Do not copy the macOS path to Linux.
A nonexistent propagated temp path can make extensions fail before readiness.

When comparing an uninstalled extension checkout, use Pi's explicit one-run loading contract:
`pi --no-extensions -e /absolute/path/to/index.ts`.
Explicit `-e` extensions still load with discovery disabled, so this does not require changing settings, editing an installed package checkout, or publishing the source revision.
Use this isolated result only for the named extension; configured-startup claims still require the normal probe with the full extension set.

When variance could change the conclusion, collect at least three sequential warm runs.
Record the revision, runtime, warm or cold state, host and VM load, and retained raw-log path.
Separate cold image work from warm steady-state startup.

Do not clear caches, stop unrelated sessions, or replace real configuration merely to produce cleaner numbers.

Parent spans include their child spans, and concurrently started services overlap.
For example, do not add `proxy startup` and `TicGit startup` when preparation waits for both in parallel.
Use the longest critical path to explain elapsed wall time.
When a gap remains, add one boundary marker at each side before adding detailed instrumentation.

Use `performance-investigation` for profiling, syscall traces, contention, or unexplained variance.
Use `jj-workflow` before reversing a deliberate pause, compatibility behavior, or unexplained lifecycle constraint.

## Choose the cheapest effective change

After measuring the target boundary and locating the candidate on its critical path, compare changes in this order.

First ask whether the operation, process, container, network, socket round trip, or validation can be removed.
If it cannot, consider reusing an existing owner, consolidating interactions, moving work off the critical path, or making it demand-driven.
Cache only after elimination and reuse are insufficient.

For each candidate, identify:

- **Cost:** the measured critical-path cost it can remove.
- **Guarantee:** the behavior or isolation guarantee currently provided.
- **Owner:** the existing component that could own the work.
- **Invalidation:** the signal needed if proposing reuse or caching.
- **Rejection:** the experiment result that would reject the candidate.

Prefer one host-to-VM transaction over repeated CLI or socket round trips when it preserves failure reporting and terminal semantics.
Prefer readiness publication from the producing process over polling through `docker exec` or another control-plane command.
Prefer lazy initialization when the first visible interaction does not require the initialized feature.
Keep concurrent independent startup work concurrent when consolidating orchestration.

Do not preserve a separate container, network, daemon, or preflight merely because it already exists.
Trace its current consumer and guarantee, then reuse or remove it when the same behavior has another owner.
Let optional preflight checks fail at first use only when the runtime error remains timely, specific, and recoverable.
Keep startup checks that prevent partial effects or replace an obscure runtime failure with an actionable one.

Before another substantial prerequisite or diagnostic round, use `work-selection` and compare it with implementing the best-supported change now.

## Run bounded experiments

State the decision the experiment can change and the outcomes that select each next action.
Use a disposable `jj workspace` under the repository's `target/` directory when the active session cannot observe launcher changes or Lima shares only the repository tree.
Keep benchmark-only configuration changes out of production commits.
Preserve raw timings and source revision metadata under `target/`; do not commit benchmark output.

Compare baseline and candidate under the same runtime, configuration, cache state, run count, and readiness marker.
Use medians for small repeated samples and show the individual values so variance stays visible.
Reject changes whose improvement is smaller than ordinary run-to-run variation unless they also remove meaningful complexity.

## Implement and verify

Follow the repository change guidelines and `change-with-evidence`.
Preserve startup cancellation, partial-failure cleanup, shared-session ownership, endpoint isolation, and terminal ownership unless the user explicitly changes those requirements.
Do not infer a security or lifecycle requirement from architecture alone; find its documented owner or history.

Add timing only around a decision-changing unknown.
Timing output remains opt-in, goes to stderr, excludes secrets and machine-specific identities, and reports failed spans.
Remove temporary instrumentation that no longer helps future diagnosis.

Run focused tests through `dev/test-environment`.
When socket creation is denied, rerun the same isolated command outside the sandbox through the approval mechanism.
Run a real warm interactive benchmark after unit tests when the host runtime is available.

The change is complete when comparable runs improve the target user-visible boundary and direct regression coverage preserves required behavior.
Attribute the remaining time to measured operations rather than guesses based on nested spans.
Report benchmark distributions, the retained evidence path, behavior preserved, and any host-runtime check that could not run.
