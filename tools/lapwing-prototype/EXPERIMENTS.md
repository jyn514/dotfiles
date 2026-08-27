# Lapwing optimization experiments

Last updated: 2026-08-27.

This log records rejected and superseded experiments so future work does not
repeat them without a materially different premise. Coverage figures are
frequency-weighted over the 20,000-token reference list. Unless noted, trials
used the exact 40,960-byte linguistic-data budget and a 64-candidate frontier.

The current conventional-coverage baseline is **93.37%**. Authoritative
letter-by-letter fallback is reported separately and is not counted here.

## Rejected experiments

| Experiment | Result | Why it was rejected |
|---|---:|---|
| Reorder all phonetic alternatives by corpus frequency | Coverage decreased and valid candidates such as `snake` were displaced. | Global ordering damaged deterministic Lapwing-specific priorities. |
| Increase the frontier from 64 to 96 | Approximately 92.12% on the older pre-repair model, versus 92.08% at 64. | The small gain did not justify the additional persistent workspace and stack pressure. Prefix pruning made 64 the better firmware tradeoff. |
| Encode DAWG edges with 14-bit targets | 6,400 words: 92.04%; 6,600: 92.09%; 7,000: 92.09%; 8,000: 91.83%; 9,000: 91.01% on the then-current metric. | Expanding every edge from 20 to 21 bits consumed more exception space than the larger vocabulary recovered. |
| Path-compress single-child DAWG chains | Rough estimate for 6,230 words: 6,014 radix arcs and 12,897 label characters; even three-byte arc records totaled about 26,103 bytes, versus about 20,448 bytes for packed DAWG edges. | Label storage and arc metadata outweighed removed states. |
| Split the DAWG by first letter | 6,230 words required about 26,775 bytes; 8,000 required about 33,094 bytes. | Lost cross-initial suffix sharing made the graph much larger. |
| Select only words that already have dictionary or productive outlines | Best tested point: 6,200 selected words, 92.41% under the then-current metric and a 20,498-byte graph, versus 92.82% for the ranked-prefix vocabulary under that same metric. | Lower-ranked rule-resolvable words displaced more valuable high-frequency vocabulary and exception interactions. Both figures predate the one-letter fallback correction. |
| Disable final-stroke prefix pruning without a separate exact pass | Conventional coverage fell from 92.06% to 91.95%. | Raw final alternatives displaced exact candidates in the 64-entry result buffer. The accepted design preserves the exact pass and retries unpruned final analyses only after it fails. |
| Broaden exception local search from 512 candidates/32 victims to 1,024/64 | 92.817391%, versus 92.817075% at the default, while generation rose to about 36 seconds. A 2,048/128 trial took about 44 seconds for similarly negligible gain. | The improvement was too small for the repeated generation cost. |
| Use hash-order exception outputs to eliminate output IDs | For 1,701 exceptions, random hash order needed about 11,079 output bytes plus 6,804 four-byte records, versus about 7,698 output bytes plus 8,505 five-byte records in lexical order. | Lost front-coding locality made the representation about 1.7 KiB larger. |
| Use a first-character-partitioned or larger vocabulary solely to admit more rule words | Larger graphs displaced high-value exceptions before they recovered equivalent frequency mass. | Vocabulary and exceptions must be optimized together, not by vocabulary count alone. |
| Promote 30 high-frequency one-stroke briefs to whole-stroke rules | Rule data grew from 4,181 to 4,629 bytes, exceptions fell from 1,701 to 1,647, and corrected conventional coverage decreased from 92.3610% to 92.3538%. | Generated rule records and unshared output strings cost more than the lexically compressed exceptions they replaced. Revisit only with a denser whole-stroke representation or shared output storage. |
| Enumerate apostrophe insertion plus one extra `e/i/d/t` insertion | Coverage decreased slightly from 92.3630% to 92.3621%, and generation rose to about 33 seconds. | The expanded repair ordering found competing exact words before intended contractions, while the combinatorial search cost was high. Revisit only with outline-specific contraction semantics or ranking evidence. |
| Expand vocabulary rebalancing to 150/60, 200/80, or 300/120 removals/additions after productive composition | All three configurations exceeded the packed DAWG's 13-bit target-offset limit. | Lower-ranked derived and compound words have longer graph paths; adding them requires substantially more removals, a wider edge format, or a separate exact derived-word representation. |
| Add a second exact DAWG for rule-generated tail words | A 1,500-word secondary graph cost 9,051 bytes and reduced available exceptions from 1,704 to about 742. Estimated conventional coverage reached only 93.57%, versus 93.37% without it. Smaller 100–1,000-word graphs ranged from 93.27% to 93.50%; 2,000 words fell to 93.44%. | The second graph spends too much of the fixed 40-KiB budget duplicating suffix paths already represented by productive rules, while evicting valuable irregular exceptions. The estimate also used target-specific prefix pruning and is optimistic. Revisit only with a substantially denser exact representation or shared graph states. |
| Remove two additional outlined frontier words to admit a forty-first probed tail word | The graph fit at 20,545 bytes, but conventional coverage decreased from 92.4324% to 92.4298%. Removing only one extra word did not fit the 13-bit target limit. | The displaced ranked words were worth more than the next tail addition. Further swaps need exact value-and-size scoring rather than extending the fixed counts. |

## Superseded estimates

- Coverage runs before the default-stack correction used only
  `lapwing-base.json`. Lapwing stores proper nouns separately, and proper-noun
  strokes carry a `#` number-bar marker. The corrected US benchmark includes
  the proper-noun dictionary but intentionally excludes UK additions.
  Those runs understated conventional coverage and incorrectly classified names
  such as `John`, `London`, and `Massachusetts` as having no outlines. The
  corrected 40 KiB baseline merges the default JSON stack and preserves `#`.
- The earlier 60,960-byte projections and their example miss lists were also
  based on the incomplete base-only input. They are not evidence for the
  corrected stack and must be rerun before use.

- The original 96.74% MPHF estimate omitted exception output text.
- The corrected hypothetical MPHF estimate was 94.97%, but assumed an
  order-preserving representation that was not implemented and was not exact.
- Conventional coverage figures above 94% produced during the fingerspelling
  work counted synthesized letter-by-letter outlines. The metric was first
  separated in commit `68c9db28`; a later audit also removed assumed one-letter
  fallbacks absent from the plain-word dictionary, establishing the 92.36%
  baseline. Fallback spelling is now reported separately.
- A plain unpruned final-stroke implementation briefly measured 92.75% only
  when paired with orthographic repair, but it could lose existing exact
  candidates. The accepted two-pass design reached 92.78% before expanded
  repairs and 92.82% afterward without that regression under the pre-audit
  one-letter metric.

## Adopted experiments

- Productive derivations are now appended even when the source dictionary
  already supplies an outline. This gives unresolved spellings a structured
  root-plus-affix fallback, raising corrected US-stack coverage from 92.95% to
  93.26% without changing the 40,960-byte data budget.
- Exact compound alternatives are now appended even when a source outline
  exists. This recovers words such as `battlefield` through known component
  outlines and raises coverage from 93.26% to 93.37% at the same budget.

## Promising experiments not yet adopted

- Component certificates using a primary-DAWG terminal-edge identity avoid a
  second word graph. Restricting components to words uniquely identified by
  their final edge index and length preserves exactness. The initial optimistic
  1,000-certificate estimate reached 93.61%. Re-evaluation using the firmware's
  actual primary-prefix pruning and final-stroke-unpruned behavior peaked at
  93.60% with 900 certificates (about 3,823 bytes and roughly 1,306 retained
  exceptions), versus 93.37% for the current model. A two-edge identity retained
  more components but its wider records peaked near 93.46%. This does not yet
  justify a format and decoder implementation: the gain is 0.23 percentage
  points and common compounds such as `smartphone` still fail before final
  certificate validation because composition is not represented in decoder
  state. A subsequent complete format-v5 implementation added packed records,
  shared front-coded root-to-output recipes, heap-free C validation, and 33
  passing tests. On the real US-stack model it stored 834 certificates in 3,831
  bytes, retained 1,304 exceptions, and reached only 93.34%. This failed the
  93.55% adoption threshold, so the implementation was reverted. The earlier
  estimate understated the value of exceptions displaced by certificates and
  overestimated the usable high-ranked certificate set.
- Structured compound decoding was then modeled by splitting each outline at
  every stroke boundary, decoding both halves independently as exact primary
  words, and approving only a stored pair of unique terminal-edge identities.
  It found 674 valid compounds, but the best allocation used only 250 records:
  1,258 bytes, roughly 1,576 retained exceptions, and 93.41% conventional
  coverage. Larger sets fell below the current baseline. `smartphone` could not
  participate because at least one component lacked a unique one-edge identity;
  `battlefield`, `butterfly`, `underwater`, and `offshore` were outside the
  rule-capable certificate candidate set. The 0.04-point gain does not justify
  adding split decoding and a new packed record format.

## Productive directions not yet exhausted

- Replace the accepted bounded vocabulary rebalance heuristic with exact
  per-swap graph-size deltas and complete model scoring. Forty additions are the
  maximum tested before the current 13-bit target-offset limit fails.
- DAWG-guided bounded edit search that can support carefully constrained
  two-edit repairs without enumerating the whole vocabulary or exploding the
  candidate frontier.
- More compact exact exception indexing that retains lexical output ordering.
- Additional hand-written Lapwing joins and orthographic transformations derived
  from high-frequency unresolved outlines.

When revisiting a rejected experiment, record the changed assumption, new
measurement, and reason the earlier result no longer applies.
