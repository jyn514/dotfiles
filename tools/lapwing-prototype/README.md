# Lapwing rules-plus-vocabulary prototype

This prototype tests whether a Moonlander-sized translator can replace most of
Lapwing's dictionary with compositional rules and a compact vocabulary.

It does not implement Lapwing theory directly. `learn_chunks.py` learns an
optimistic approximation from the official dictionary: it aligns spelling
chunks with strokes, holds out complete words, and tests whether learned stroke
chunks can reconstruct those unseen words. The complete vocabulary is then
used as an oracle to reject generated non-words.

See `SPEC.md` for the implemented firmware design and `EXPERIMENTS.md` for
rejected, superseded, and still-promising optimization directions.

## Data

Clone the official dictionary separately; it is deliberately not vendored.
The measurements below used commit
`4ac5d53cf039a2b1f4c484456663c85e7df4e859` of
`aerickt/plover-lapwing-aio`. Build the US-English JSON benchmark stack in
Plover lookup-priority order. It includes commands, numbers, proper nouns, and
the base dictionary; UK additions are intentionally excluded:

```sh
git clone https://github.com/aerickt/plover-lapwing-aio.git /tmp/plover-lapwing-aio
git -C /tmp/plover-lapwing-aio checkout 4ac5d53cf039a2b1f4c484456663c85e7df4e859
ROOT=/tmp/plover-lapwing-aio/plover_lapwing/dictionaries
python3 merge_dictionaries.py /tmp/lapwing-default-stack.json \
  "$ROOT/lapwing-commands.json" "$ROOT/lapwing-numbers.json" \
  "$ROOT/lapwing-proper-nouns.json" "$ROOT/lapwing-base.json"
DICTIONARY=/tmp/lapwing-default-stack.json
```

The merged stack contains 130,933 outlines and 51,910 unique plain-word
translations. Dynamic Python dictionaries remain runtime facilities rather than
model-generation inputs. The repository has an MIT `LICENSE`, although its package
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

## Flash-resident model

`generate_model.py` builds the model actually consumed by the C firmware. It
uses an exact minimized acyclic word graph rather than the earlier proposed
MPHF. This avoids vocabulary false positives and requires no rank payload.
Exception outlines use packed 29-bit hashes and 11-bit IDs into a lexically
front-coded, five-bit-letter output pool with restart points every 384 words.

The selected model starts from a 6,275-word ranked frontier and rebalances it
to 6,215 exact vocabulary words:

| Data | Bytes |
|---|---:|
| Generated C rule representation | 4,181 |
| Binary vocabulary and exceptions | 36,779 |
| **Total linguistic data** | **40,960** |

The binary contains a 20,518-byte exact vocabulary graph, 2,450 bytes of
grouped exact morphology (77 recipes licensing 957 transformed words), and
1,443 exception outlines. Productive morphology, closed-compound composition, standalone
affixes, and algorithmic fingerspelling of every word through the sixteen-stroke
outline limit supply additional outlines without consuming model records.
Conventional dictionary and rule outlines cover **93.63%** of the 20,000-token
frequency benchmark. This metric deliberately excludes every synthesized
letter-by-letter outline, including one-stroke letter fallbacks absent from the
plain-word dictionary. Authoritative spelling, including a final `AES`
possessive stroke, raises reachable coverage to **99.99%** without admitting phonetic
nonwords. The conventional figure is lower than the earlier 94.97% MPHF
estimate, which
assumed an order-preserving hash representation that was never implemented and
would not have provided exact membership within the claimed size.

Generate the model with:

```sh
python3 generate_model.py \
  "$DICTIONARY" /tmp/wordfreq-en-50000.tsv lapwing_model.bin \
  --vocabulary 6275 --beam 64 --report lapwing_model_report.json
```

Model selection removes up to 100 low-ranked frontier tokens without
conventional outlines, probes the next 200 outlined words against a temporary
exact prefix set, and admits the first 40 that resolve without exceptions. The
reference model uses all 100 permitted removals. It then
builds the final vocabulary graph once and uses a size-only exception path while
searching the budget. On the reference inputs this reduced a
6,275-word-frontier generation run from about 50 seconds to about 14 seconds while
producing a byte-identical model.

## Interpretation

The implemented rules-plus-vocabulary translator is useful for common text,
but is not a complete replacement for desktop Lapwing:

- A hand-written Lapwing grammar should be smaller and better than this learned
  table for regular phonetic outlines.
- The exact rebalanced 6,215-word vocabulary graph costs about 20 KiB and cannot admit
  generated nonwords.
- Briefs, collisions, irregular spelling, commands, and rare stroke forms still
  require exact exceptions.
- The useful 40-75 KiB rule models measured here leave little room for QMK,
  Javelin, ranking, and exceptions, while delivering only 34-45% overall top-1.

The current design therefore keeps a small exact common vocabulary and briefs,
then applies hand-coded Lapwing phonology and morphology. External flash or a
host translator remains the appropriate route to dictionary-equivalent
coverage.

## C decoder

`lapwing_decoder.c` is the first heap-free C port of the hand-written rule
engine. `hand_rules.py` remains the authoritative editable rule source;
`generate_c_rules.py` produces `lapwing_rules.generated.h`. The C core has no
QMK or HID side effects: callers supply outlines and optionally a vocabulary
acceptance callback.

The current port includes canonical-stroke parsing, ordered onset/coda
segmentation, whole strokes, prefixes and suffixes, starred alternatives,
silent-e variants, folded endings, English affix joins, bounded candidate
storage, and deduplication. Its packed generated C representation occupies 4,181 bytes
before linker optimization. Host golden tests recover representative words such
as “snake”, “python”, “preview”, “zapping”, “interstate”, “microphone”, and
“helpful”. Across 20,000 dictionary outlines, its 64-candidate output exactly
matched the Python reference.

The decoder recognizes all-starred letter sequences directly, bypassing
phonetic ambiguity, frontier ordering, and vocabulary membership for explicitly
spelled words. A final `AES` produces possessive `'s`; ordinary phonetic paths
remain subject to exact vocabulary membership.

`lapwing_model.c` provides exact vocabulary membership, prefix lookup,
exception lookup, and front-coded output recovery. During rule generation,
DAWG-prefix pruning prevents impossible partial spellings from consuming the
64-candidate inter-stroke frontier. If no exact final candidate survives, the
model retries the final stroke without prefix pruning and tests bounded
consonant-doubling, insertion, deletion, transposition, vowel-change, and
steno-confusion repairs against exact DAWG membership. A narrow `selbr` to
`celebr` repair covers Lapwing's compressed celebration family without enabling
general two-edit search. Exact folded-liquid and broad-vowel rewrites recover
families such as `clean`, `college`, `talk`, and `called`. Exact terminal
rewrites recover voiced silent-e, soft-c, and plural spellings such as `love`,
`placed`, and `makes`. Bounded `gh` and `in` insertion recovers silent-letter
and folded-`ing` families such as `light` and `doing`. `lapwing_engine.c`
adds delayed multi-stroke
commit, automatic spacing and sentence capitalization, punctuation strokes,
explicit commit, cancellation, and eight-entry undo history.
`lapwing_qmk.c` intercepts completed QMK steno chords, converts Gemini chord bits
to canonical strokes, suppresses serial steno output, and publishes translated
text through normal keyboard HID reports.

The complete generated model and adapter compile in both Moonlander targets:

| Target | Firmware | Flash remaining | BSS | Linker heap |
|---|---:|---:|---:|---:|
| `reva` | 107,872 B | **23,200 B** | 17,772 B | 9,244 B |
| `revb` | 110,116 B | **20,956 B** | comparable | comparable |

These builds use the complete `KW9E9` Oryx keymap and ZSA `firmware25` commit
`c9fe0e2960cd96db31c627ab7215d93436305fed`.

Regenerate and test it with:

```sh
python3 generate_c_rules.py lapwing_rules.generated.h
python3 generate_model.py "$DICTIONARY" frequencies.tsv lapwing_model.bin \
  --vocabulary 6275 --beam 64
python3 install_qmk.py /path/to/qmk/keyboards/zsa/moonlander/keymaps/KW9E9 \
  lapwing_model.bin
python3 -m unittest discover -p '*_test.py'
```

`LW_MAX_CANDIDATES` is compile-time bounded. The host golden test uses 128 to
exercise rule ordering; firmware uses 64 and relies on exact exceptions before
rule generation for common irregular outlines.

## Tests

```sh
python3 -m unittest discover -p '*_test.py'
```
