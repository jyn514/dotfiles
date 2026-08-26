# Lapwing rules-plus-vocabulary prototype

This prototype tests whether a Moonlander-sized translator can replace most of
Lapwing's dictionary with compositional rules and a compact vocabulary.

It does not implement Lapwing theory directly. `learn_chunks.py` learns an
optimistic approximation from the official dictionary: it aligns spelling
chunks with strokes, holds out complete words, and tests whether learned stroke
chunks can reconstruct those unseen words. The complete vocabulary is then
used as an oracle to reject generated non-words.

## Data

Clone the official dictionary separately; it is deliberately not vendored.
The measurements below used commit
`4ac5d53cf039a2b1f4c484456663c85e7df4e859` of
`aerickt/plover-lapwing-aio` and its `lapwing-base.json`:

```sh
git clone https://github.com/aerickt/plover-lapwing-aio.git /tmp/plover-lapwing-aio
DICTIONARY=/tmp/plover-lapwing-aio/plover_lapwing/dictionaries/lapwing-base.json
```

The inspected dictionary contains 114,885 entries and 45,161 unique plain-word
translations. The repository has an MIT `LICENSE`, although its package
metadata still names GPLv2-or-later; verify that inconsistency before
redistributing dictionary data.

## Measure vocabulary storage

```sh
python3 analyze_storage.py "$DICTIONARY"
```

Results for all 45,161 plain words:

| Representation | Size |
|---|---:|
| Newline-separated words | 396.2 KiB |
| XZ-compressed stream | 103.5 KiB |
| Exact front coding, 32-word blocks | 211.1 KiB |
| Compact trie estimate | 352.0 KiB |
| Bloom membership, 6 bits/word | 33.1 KiB |
| Bloom membership, 10 bits/word | 55.1 KiB |
| One-byte rank per word | 44.1 KiB |

XZ is not directly searchable: it normally requires decompressing a large
stream. Bloom filters are searchable and small, but cannot recover words and
produce false positives. They are useful here only because the rule engine
already generated the candidate spelling.

## Learn and evaluate compositional chunks

```sh
python3 learn_chunks.py "$DICTIONARY" \
  --iterations 2 --top-k 5 --chunks-per-stroke 4 --beam 1000
```

The split is deterministic and grouped by translation, so no spelling appears
in both training and test sets. Only multi-stroke entries teach chunk rules.
A test outline is eligible only when every constituent stroke was observed in
training. The vocabulary oracle includes held-out words; this intentionally
measures rule reconstruction rather than vocabulary discovery.

### Storage/accuracy trade-off

The packed-size estimate encodes each stroke key in four bytes and each chunk
with a length, packed five-bit letters, and a quantized score. It excludes
lookup code and the vocabulary filter.

| Retained stroke rules | Chunks/stroke | Packed model | Eligible test entries | Overall top-1 | Overall recall@5 |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 4 | 21.7 KiB | 30.1% | 23.3% | 23.6% |
| 2,000 | 2 | 26.2 KiB | 44.8% | 26.2% | 26.3% |
| 2,000 | 4 | 41.4 KiB | 44.8% | 33.8% | 34.2% |
| 4,000 | 4 | 73.0 KiB | 61.5% | 44.5% | 45.1% |
| 13,598 | 4 | 174.0 KiB | 84.4% | 52.9% | 53.6% |

The learned model is not a compact encoding of Lapwing theory: rare strokes
become individual rules. This is useful evidence nevertheless. A mechanical
chunk system shows substantial compositionality, but its long tail grows into
another dictionary.

On held-out entries restricted to approximately the 10,000 most frequent
English words, the same models reached about 31% overall top-1 at 42 KiB and
49% at 178 KiB. Common-word restriction did not remove the long-tail stroke
problem.

## Hand-written theory rules

`hand_rules.py` implements explicit onset, vowel, coda, prefix, suffix,
syllable-linker, and English boundary rules from Lapwing chapters 5-15. It
contains no learned mappings or outline-conditioned statistics.

```sh
python3 hand_rules.py "$DICTIONARY" --beam 5000 --top-k 10
```

The expanded hand-written tables serialize to an estimated **2,555 bytes**.
Across 112,752 plain lexical entries they produce at least one vocabulary word
for 50.2%, reach **47.1% recall@10**, and **45.3% top-1**. This remains a harsh
entry-level score that includes briefs, alternate outlines, and shortened forms.
The rules correctly reconstruct examples such as `PAOEU/THOPB` → “python”,
`PRAOE/SRAOU` → “preview”, and `HEL/-P/-FL` → “helpful”.

This is substantially more space-efficient than the learned chunk model. Its
main misses are briefs, vowel deletion, folding, ambiguous sound-to-spelling,
and theory families not yet encoded. Expanding general rules by several
kilobytes is therefore plausible; reaching dictionary-equivalent behavior is
not demonstrated.

## Frequency-weighted 40 KiB experiment

`common_text_budget.py` evaluates a hybrid intended for ordinary text rather
than dictionary reproduction. It combines hand-written rules, a ranked common
vocabulary, algorithmic inflections and fingerspelling, and exact exceptions
selected by token frequency.

The benchmark used the 20,000 highest-frequency English tokens from `wordfreq`
and the base, proper-noun, and UK Lapwing dictionaries. Its best estimated
40 KiB layout was:

| Data | Bytes |
|---|---:|
| Hand-written rules | 2,555 |
| 14,000-word membership/rank index | 17,500 |
| 1,853 exact exceptions, including output words | 20,905 |
| **Total** | **40,960** |

Estimated frequency-weighted coverage was **94.97%**. The added rules cover
long-vowel silent-e spellings, broader vowel graphemes, the complete documented
onset/coda tables, starred alternatives, and productive folded affix families.

The exception budget includes a lexically front-coded output-word pool with a
restart every 32 words. This corrects an earlier 96.74% estimate that counted
exception IDs but omitted the storage needed to recover their output text.

This remains a storage-model result. It assumes an immutable minimal-perfect-
hash vocabulary using about 10 bits per word and a six-byte exception record
containing MPHF overhead, a 24-bit fingerprint, and a 16-bit output-pool ID. It
still excludes a real MPHF generator, false-positive measurements, commands,
and complete translator behavior.

A representative QMK sizing build used the official ZSA `firmware25` tree at
commit `c9fe0e2960cd96db31c627ab7215d93436305fed`, the complete `KW9E9` Oryx
keymap, a 40,953-byte structured model image, bounded 24-candidate decoding,
morphology, lookup, front-coded exception recovery, and `send_string()` output.
For `zsa/moonlander/reva`, the baseline occupied 57,908 bytes of flash; the
probe occupied 99,984 bytes, a 42,076-byte increase. Of that increase, 40,953
bytes were model data and 1,123 bytes were linked code. The probe also added
920 bytes of static RAM, leaving a 22,492-byte linker heap and 31,088 bytes of
application flash. This establishes credible size headroom, but the probe is
not yet a behaviorally equivalent Lapwing decoder.

## Interpretation

A rules-plus-vocabulary translator is feasible for common text, but not as a
complete replacement for Lapwing on the stock Moonlander:

- A hand-written Lapwing grammar should be smaller and better than this learned
  table for regular phonetic outlines.
- A 5,000-10,000-word probabilistic vocabulary costs roughly 4-12 KiB, before
  ranking data.
- Briefs, collisions, irregular spelling, commands, and rare stroke forms still
  require exact exceptions.
- The useful 40-75 KiB rule models measured here leave little room for QMK,
  Javelin, ranking, and exceptions, while delivering only 34-45% overall top-1.

The next credible design is a small exact dictionary for frequent words and
briefs, a hand-coded Lapwing phonology/morphology fallback, and host-assisted or
external-flash storage for the remaining vocabulary. A stock-Moonlander-only
implementation should first establish an actual firmware byte budget; without
that measurement, selecting a linguistic representation is premature.

## C decoder

`lapwing_decoder.c` is the first heap-free C port of the hand-written rule
engine. `hand_rules.py` remains the authoritative editable rule source;
`generate_c_rules.py` produces `lapwing_rules.generated.h`. The C core has no
QMK or HID side effects: callers supply outlines and optionally a vocabulary
acceptance callback.

The current port includes canonical-stroke parsing, ordered onset/coda
segmentation, whole strokes, prefixes and suffixes, starred alternatives,
silent-e variants, folded endings, English affix joins, bounded candidate
storage, and deduplication. Its generated C representation occupies 4,413 bytes
before linker optimization. Host golden tests recover representative words such
as “snake”, “python”, “preview”, “zapping”, “interstate”, “microphone”, and
“helpful”. It does not yet include the generated MPHF model, QMK chord capture,
translation history, spacing, capitalization, punctuation, or undo.

The decoder also compiles in the real Moonlander revA firmware. With the full
40,960-byte model placeholder linked, the complete image occupies 107,160 bytes
of flash, leaving **23,912 bytes**. Relative to the 57,908-byte baseline, the
model plus C decoder costs 49,252 bytes: 40,960 bytes of model and 8,292 bytes
of linked decoder/rule code and data. The bounded workspace adds 7,144 bytes of
BSS and leaves a 16,268-byte linker heap. This is the current implementation
baseline; MPHF lookup and the QMK adapter must remain within the residual flash
and RAM budgets.

Regenerate and test it with:

```sh
python3 generate_c_rules.py lapwing_rules.generated.h
python3 -m unittest discover -p '*_test.py'
```

`LW_MAX_CANDIDATES` is compile-time bounded. The host golden test uses 128 to
exercise rule ordering; firmware builds should start at 24 and rely on exact
exceptions before rule generation for common irregular outlines.

## Tests

```sh
python3 -m unittest discover -p '*_test.py'
```
