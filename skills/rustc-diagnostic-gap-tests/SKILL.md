---
name: rustc-diagnostic-gap-tests
description: Survey Rust compiler and rustdoc diagnostics for weak or missing beginner-facing guidance, investigate helpers and implementation difficulty, or add non-duplicated compiletest UI cases and snapshots. Use in a rust-lang/rust checkout when asked to find diagnostic gaps, expand tests/ui or tests/rustdoc-ui coverage, estimate implementation difficulty, cross-reference existing diagnostic helpers, or continue a diagnostic-quality survey until diminishing returns.
---

# Rustc Diagnostic Gap Tests

## Select the requested activity

Inspect the worktree and preserve unrelated changes.
Distinguish a read-only survey, helper lookup, or difficulty estimate from authorized test additions.
A diagnostic investigation does not authorize creating tests, blessing snapshots, or implementing compiler fixes.
For a bounded lookup or estimate, inspect the named diagnostic and relevant nearby tests; do not expand it into a compiler-wide survey.
For a broad gap survey, use the coverage procedure below.
When test additions are authorized, assess the candidate first, then read [test construction and verification](references/test-campaign.md) before creating or blessing files.

## Survey

1. Search the relevant test suites before proposing a case. Reject a case when both
   its input shape and diagnostic limitation already exist. Sharing an error code
   alone does not make it a duplicate.
2. Prefer mistakes likely from new Rust users and diagnostics that expose compiler internals without actionable context.
3. Find the owning diagnostic and nearby helpers under `compiler/`. Search emitted wording, diagnostic structs, trait diagnostic items, and suggestion text.
4. When a subsystem mostly yields duplicates, switch compiler phases or suites.

Consider parser/macro expansion, resolution/imports, type checking, trait selection, borrow checking, const evaluation, async lowering, attributes/cfg, coherence, unsafe checking, lints/FFI, command-line parsing, and rustdoc.

### Before concluding a broad survey

Ask: “Are there any other parts of the compiler with gaps?” Survey at least one
plausible remaining area before answering no.

## Rate difficulty

Name helpers when they materially lower difficulty, such as `suggest_ref_or_clone`, `suggest_await_on_expect_found`, `get_impl_future_output_ty`, `suggest_option_to_bool`, `cannot_return_reference_to_local`, and `suggest_capturing_closure`. Verify names in the current checkout.

- **Easy detection:** the diagnostic already owns the decisive types, spans, or DefIds, or an existing helper recognizes the shape.
- **Medium detection:** extend a local HIR/MIR pattern, connect existing paths, group expanded errors, or carry short-range provenance.
- **Hard detection:** add visible-name enumeration, whole-body or inter-procedural reasoning, or intent-sensitive dataflow.
- **Easy fix:** add static help or an unambiguous local edit using recovered spans.
- **Medium fix:** make a bounded multipart edit or offer several valid alternatives without selecting one.
- **Hard fix:** change API, ownership, control flow, synchronization, error handling, or ABI, or prove another body or caller remains valid.

Rate detection and fix independently. Borrowck may easily identify a by-value `self` move while changing the method to `&self` remains hard because the method body and API must be analyzed.

## Read-only result

Report the diagnostic owner and verified helper names with source locations, what guidance is missing or already supplied, and duplicate-test evidence for any proposed gap.
For an estimate, rate detection and fix independently using the rubric above; state the required analysis, reusable consumers, ambiguous intent, and remaining uncertainty.
For a broad survey, report inspected areas and remaining or lower-value areas, including the final coverage check above.
Stop here for investigation-only work; sources, snapshots, blessing, forced-batch runs, and pass counts are completion requirements only for authorized test additions.
