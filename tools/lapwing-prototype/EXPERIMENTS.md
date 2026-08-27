# Lapwing optimization experiments

Last updated: 2026-08-27.

This log records rejected and superseded experiments so future work does not
repeat them without a materially different premise. Coverage figures are
frequency-weighted over the 20,000-token reference list. Unless noted, trials
used the exact 40,960-byte linguistic-data budget and a 64-candidate frontier.

The current conventional-coverage baseline is **92.82%**. Authoritative
letter-by-letter fallback is reported separately and is not counted here.

## Rejected experiments

| Experiment | Result | Why it was rejected |
|---|---:|---|
| Reorder all phonetic alternatives by corpus frequency | Coverage decreased and valid candidates such as `snake` were displaced. | Global ordering damaged deterministic Lapwing-specific priorities. |
| Increase the frontier from 64 to 96 | Approximately 92.12% on the older pre-repair model, versus 92.08% at 64. | The small gain did not justify the additional persistent workspace and stack pressure. Prefix pruning made 64 the better firmware tradeoff. |
| Encode DAWG edges with 14-bit targets | 6,400 words: 92.04%; 6,600: 92.09%; 7,000: 92.09%; 8,000: 91.83%; 9,000: 91.01% on the then-current metric. | Expanding every edge from 20 to 21 bits consumed more exception space than the larger vocabulary recovered. |
| Path-compress single-child DAWG chains | Rough estimate for 6,230 words: 6,014 radix arcs and 12,897 label characters; even three-byte arc records totaled about 26,103 bytes, versus about 20,448 bytes for packed DAWG edges. | Label storage and arc metadata outweighed removed states. |
| Split the DAWG by first letter | 6,230 words required about 26,775 bytes; 8,000 required about 33,094 bytes. | Lost cross-initial suffix sharing made the graph much larger. |
| Select only words that already have dictionary or productive outlines | Best tested point: 6,200 selected words, 92.41% conventional coverage and a 20,498-byte graph, versus 92.82% for the ranked-prefix vocabulary. | Lower-ranked rule-resolvable words displaced more valuable high-frequency vocabulary and exception interactions. |
| Disable final-stroke prefix pruning without a separate exact pass | Conventional coverage fell from 92.06% to 91.95%. | Raw final alternatives displaced exact candidates in the 64-entry result buffer. The accepted design preserves the exact pass and retries unpruned final analyses only after it fails. |
| Broaden exception local search from 512 candidates/32 victims to 1,024/64 | 92.817391%, versus 92.817075% at the default, while generation rose to about 36 seconds. A 2,048/128 trial took about 44 seconds for similarly negligible gain. | The improvement was too small for the repeated generation cost. |
| Use hash-order exception outputs to eliminate output IDs | For 1,701 exceptions, random hash order needed about 11,079 output bytes plus 6,804 four-byte records, versus about 7,698 output bytes plus 8,505 five-byte records in lexical order. | Lost front-coding locality made the representation about 1.7 KiB larger. |
| Use a first-character-partitioned or larger vocabulary solely to admit more rule words | Larger graphs displaced high-value exceptions before they recovered equivalent frequency mass. | Vocabulary and exceptions must be optimized together, not by vocabulary count alone. |

## Superseded estimates

- The original 96.74% MPHF estimate omitted exception output text.
- The corrected hypothetical MPHF estimate was 94.97%, but assumed an
  order-preserving representation that was not implemented and was not exact.
- Conventional coverage figures above 94% produced during the fingerspelling
  work counted synthesized letter-by-letter outlines. The metric was corrected
  in commit `68c9db28`; fallback spelling is now reported separately.
- A plain unpruned final-stroke implementation briefly measured 92.75% only
  when paired with orthographic repair, but it could lose existing exact
  candidates. The accepted two-pass design reached 92.78% before expanded
  repairs and 92.82% afterward without that regression.

## Productive directions not yet exhausted

- Size-aware vocabulary swaps that evaluate the complete graph, exception set,
  and conventional coverage together rather than filtering by outline presence.
- DAWG-guided bounded edit search that can support carefully constrained
  two-edit repairs without enumerating the whole vocabulary or exploding the
  candidate frontier.
- More compact exact exception indexing that retains lexical output ordering.
- Additional hand-written Lapwing joins and orthographic transformations derived
  from high-frequency unresolved outlines.

When revisiting a rejected experiment, record the changed assumption, new
measurement, and reason the earlier result no longer applies.
