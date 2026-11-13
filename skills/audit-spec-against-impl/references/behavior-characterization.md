# Recover a descriptive specification

Use when asked to extract existing behavior or business rules, reverse-spec code, or characterize a system for reimplementation.
Produce an account of what the inspected implementation does, not a newly approved normative contract or a replacement design.
A findings-only request remains findings-only; write maintained documentation only when that output is requested.

## Bound the implementation and evidence

Establish the target capability or subsystem, its intended reader, and what that reader needs to reproduce or understand.
If the requested boundary is unclear, inspect the documented entrypoints and ask only when materially different scopes remain.
Record the inspected revision, relevant local changes, and configuration or dependency versions that affect the recovered behavior.
Distinguish source inspection from runtime observations and existing test assertions.
Tests may repeat an implementation defect; agreement alone does not establish intent.

Enumerate the public entrypoints in scope: commands, API routes, messages, jobs, or supported library calls.
Use that inventory to account for coverage; include shared behavior outside the target directory when it changes an entrypoint's result.
Do not require a whole-repository inventory for a bounded capability.
Use existing capability names and requirement labels rather than introducing a numbering or tracking system by default.

## Trace caller-visible behavior

Follow each entrypoint through its producers, transformations, effect owners, and final consumer.
Read the relevant implementation and tests in context, including adapters that hide, substitute, or discard results.
Recover the applicable:

- inputs, data shapes, identity rules, accepted and rejected cases;
- defaults, configuration precedence, and omitted-value behavior;
- business decisions and the conditions that select each outcome;
- state transitions, ordering, persistence, and externally visible effects;
- error mappings, fallback results, cancellation, and cleanup behavior.

Describe behavior in terms a replacement's caller can observe rather than merely listing functions or copying code.
Keep an algorithmic detail when changing it would change caller-visible output, ordering, resource limits, or another relevant observable property.
Check shared rules across entrypoints so separate descriptions do not conceal conflicting defaults or failure behavior.

For example, a service produces a detailed failure but its CLI adapter returns a generic message and one nonzero exit code.
Record the CLI-visible mapping as well as any separately supported service result.
Do not promise the service's detail to CLI callers merely because it exists upstream.
If a fallback accepts an invalid identifier, record the quirk and its trigger without declaring that a rewrite must retain it.

## Separate behavior, intent, and uncertainty

For each material rule, retain its trigger, outcome, source location, and applicable configuration.
Use file-and-line or stable symbol references tied to the inspected revision.
Label what the evidence establishes: source-supported behavior, runtime-observed behavior under named inputs, inference, or an unresolved gap.
Do not assign numerical confidence without a basis or collapse several uncertain paths into a confirmed rule.

Keep these distinctions explicit:

- **Observed behavior:** what the implementation does, including surprising quirks and apparent defects.
- **Intended requirement:** behavior supported by an authoritative contract or project decision.
- **Preservation decision:** what an authorized decision actually requires a replacement to retain or change.
- **Unknown:** a missing path, ambiguous intent, conflicting evidence, or unavailable environment that prevents a conclusion.

An existing test can document a quirk without establishing that it is intentional or worth preserving.
Retain conflicts with existing documentation instead of silently choosing code or prose as the authority.
Use project decisions or relevant history when they can resolve intent; otherwise leave the preservation question open.
Do not silently turn recovered descriptions into normative specification edits.

## Check coverage and deliver

Compare the recovered account with the entrypoint inventory.
Each entrypoint needs traced behavior or an explicit gap, including relevant failures and cross-entrypoint effects.
A list of source files or passing helper tests does not establish complete consumer behavior.
Use the cheapest safe check that can resolve a material uncertainty, following the [shared testing guidance](../../references/testing.md).
A characterization request does not itself authorize implementation changes, new regression suites, or mutations of real user state and shared services.

Deliver the recovered data model, behavioral rules, quirks, and gaps at the requested destination or in the findings report.
Group them by capability or caller task; use separate files only when their size or consumers justify it.
Include enough conditions, outcomes, examples, and provenance for the intended reader to use the account without reopening every source file.
State inspected coverage, unexamined paths, unavailable runtime checks, and unresolved preservation decisions.
Do not claim rebuild completeness while required entrypoints or behavior remain unexplained.
If documentation is requested, use the [editorial pass](../../holistic-writing/references/editorial-pass.md) and its format-specific validation.
Stop at characterization unless reconciliation, planning, implementation, or issue filing is separately authorized.
