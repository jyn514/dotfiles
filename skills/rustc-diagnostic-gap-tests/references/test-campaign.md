# Add and verify diagnostic gap tests

Read when test additions are authorized, after the [survey and difficulty assessment](../SKILL.md).
This procedure does not authorize compiler fixes or turn a read-only lookup into a test campaign.

## Add a test

Create a narrowly named `.rs` file in the most specific directory. Keep one diagnostic idea per test unless grouping is the idea.

Place this analysis near the failing construct:

```rust
// Detection difficulty: easy|medium|hard; cite existing or missing analysis and why.
// Fix difficulty: easy|medium|hard; state what must be proved and whether intent is ambiguous.
// Generalization: name other consumers or input shapes that can reuse the analysis.
```

Omit `Generalization` only when no honest reusable form exists. Also state what the current diagnostic lacks.

Put compiletest annotations at the actual primary span, including macro-definition spans. Do not force an invocation-span expectation because relocation would be a better diagnostic.

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
- for a broad survey continued until diminishing returns, plausible remaining subsystems now yield duplicates or lower-value cases.

Report exact pass counts.
