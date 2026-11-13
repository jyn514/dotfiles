---
name: observability-instrumentation
license: MIT
description: Add or review logging, metrics, tracing, alerts, or other observability instrumentation. Use when asked to make runtime behavior inspectable or assess whether telemetry answers operators' questions. Not for every feature, diagnosing a current failure, or profiling measured slowness alone.
---

# Observability and instrumentation

Work within the requested scope: a review produces findings, not changes.
For a current failure or measured slowness, use the applicable debugging or performance investigation procedure instead; instrumenting for future diagnosis is a separate task.

## Choose signals from questions

Identify the operator and the concrete questions they need to answer, such as whether a job failed, why it failed, or where a request stalled.
Trace the relevant execution and existing telemetry through to where that operator can inspect it.
For each question, map the signal and inspection path: event and log query, metric and dashboard/query, or trace and viewer.
Identify what existing instrumentation already answers before adding anything.
Reuse the project's logger, metrics, tracing, alerting, and collection paths where they fit; assess a new dependency only when existing owners cannot meet the need.

Choose the smallest combination that answers the questions.
Logs can explain individual events; metrics can show rates or distributions across events; traces can connect work across hops when existing evidence cannot locate a delay or failure.
For a single-process batch task, a completion or failure log with a reason and a way to find that run may answer the operator's question without metrics or tracing.
For a request crossing services, if logs cannot show which hop stalls, propagated trace context and spans around those hops may justify tracing; verify that the operator can actually inspect the resulting trace.
Do not add correlation fields, structured formats, or telemetry types merely because the example uses them.
For human-facing CLI output, follow the [logging guidance](../references/change-with-evidence.md#logging); operational telemetry need not replace readable output.

## Make the chosen signals usable

- Select fields that answer the question, using the project's conventions and stable event names where useful.
  Minimize recorded data, exclude secrets, and redact sensitive values before emission; inspect actual output, including error paths.
- Bound metric labels to small known sets, such as route templates or status classes.
  IDs, raw URLs, and free-form error messages create unbounded series; keep any needed case-specific detail in appropriately protected logs or traces instead.
- Where material, choose sampling, retention, and collection volume against the questions, privacy, cost, and runtime overhead.
  Sampling can omit the incident an operator seeks; retention must cover the period in which it needs investigation.
- Add alerts only when someone can take a useful action.
  Choose the condition, threshold, duration, recipient, and severity for the actual service and its operating expectations; include a usable first response or runbook and an owner.
  A symptom may warrant paging, while a resource condition may matter when it gives actionable warning before harm.
  Do not add an alert simply because a metric exists.

## Verify what the operator receives

Exercise representative success and failure paths, then inspect the emitted telemetry through the intended consumer.
Check that each question can be answered, fields and values are correct and appropriately redacted, and chosen labels remain bounded.
For traces, follow a representative operation across the intended boundaries; for metrics, inspect actual series and values.
For each new or changed alert, trigger its condition and verify delivery to the intended recipient and access to its response guidance.

Use disposable authorized resources for tests, including alert destinations and induced failures.
Do not mutate staging, production, shared services, or real user state without authorization for that exact effect.
If safe delivery testing is unavailable, report the missing evidence and what access or disposable destination would resolve it; do not claim delivery is verified from a configuration check.
Report questions still unanswered, sampling or retention limits, and the owner of any recurring alert maintenance when those affect operation.

## Attribution

Adapted from `observability-instrumentation` in `@blackbelt-technology/pi-dashboard-eng-disciplines`, itself derived from Addy Osmani's `agent-skills/skills/observability-and-instrumentation`.
See [LICENSE](LICENSE) for the upstream copyright and MIT terms.
