---
name: rustc-diagnostic-gap-tests
description: Survey Rust compiler and rustdoc diagnostics for weak or missing beginner-facing guidance, then add non-duplicated compiletest UI cases and snapshots. Use in a rust-lang/rust checkout when asked to find diagnostic gaps, expand tests/ui or tests/rustdoc-ui coverage, estimate implementation difficulty, cross-reference existing diagnostic helpers, or continue a diagnostic-quality survey until diminishing returns.
---

# Rustc Diagnostic Gap Tests

## Survey

1. Inspect the worktree. Preserve unrelated changes.
2. Search the relevant test suites before proposing a case. Reject the same input shape and diagnostic limitation; sharing an error code is not duplication.
3. Prefer mistakes likely from new Rust users and diagnostics that expose compiler internals without actionable context.
4. Find the owning diagnostic and nearby helpers under `compiler/`. Search emitted wording, diagnostic structs, trait diagnostic items, and suggestion text.
5. When a subsystem mostly yields duplicates, switch compiler phases or suites. Before concluding, ask: “Are there any other parts of the compiler with gaps?” Survey at least one plausible remaining area before answering no.

Consider parser/macro expansion, resolution/imports, type checking, trait selection, borrow checking, const evaluation, async lowering, attributes/cfg, coherence, unsafe checking, lints/FFI, command-line parsing, and rustdoc.

## Add a test

Create a narrowly named `.rs` file in the most specific directory. Keep one diagnostic idea per test unless grouping is the idea.

Place this analysis near the failing construct:

```rust
// Detection difficulty: easy|medium|hard; cite existing or missing analysis and why.
// Fix difficulty: easy|medium|hard; state what must be proved and whether intent is ambiguous.
// Generalization: name other consumers or input shapes that can reuse the analysis.
```

Omit `Generalization` only when no honest reusable form exists. Also state what the current diagnostic lacks.

Name helpers when they materially lower difficulty, such as `suggest_ref_or_clone`, `suggest_await_on_expect_found`, `get_impl_future_output_ty`, `suggest_option_to_bool`, `cannot_return_reference_to_local`, and `suggest_capturing_closure`. Verify names in the current checkout.

Put compiletest annotations at the actual primary span, including macro-definition spans. Do not force an invocation-span expectation because relocation would be a better diagnostic.

## Rate difficulty

- **Easy detection:** the diagnostic already owns the decisive types, spans, or DefIds, or an existing helper recognizes the shape.
- **Medium detection:** extend a local HIR/MIR pattern, connect existing paths, group expanded errors, or carry short-range provenance.
- **Hard detection:** add visible-name enumeration, whole-body or inter-procedural reasoning, or intent-sensitive dataflow.
- **Easy fix:** add static help or an unambiguous local edit using recovered spans.
- **Medium fix:** make a bounded multipart edit or offer several valid alternatives without selecting one.
- **Hard fix:** change API, ownership, control flow, synchronization, error handling, or ABI, or prove another body or caller remains valid.

Rate detection and fix independently. Borrowck may easily identify a by-value `self` move while changing the method to `&self` remains hard because the method body and API must be analyzed.

## Bless and verify

Run the narrow test first:

```text
./x test tests/ui/path/test.rs --bless --test-args=--force-rerun
```

Use the corresponding specialized suite for rustdoc. Inspect `.stderr` and any `.fixed` file. Revise or delete a test if rustc already supplies the proposed guidance. Rebless after line-changing comments because snapshots contain source locations.

Force-run the complete batch without `--bless`, then verify:

- every source has separate detection and fix annotations;
- every failing source has a snapshot, and every `run-rustfix` source has reviewed `.fixed` output;
- annotations cite current implementation rather than assumed architecture;
- generalizations reuse analysis rather than guessed intent;
- no unrelated files changed;
- plausible remaining subsystems now yield duplicates or lower-value cases.

Report exact pass counts.
