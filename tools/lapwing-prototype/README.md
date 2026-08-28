# Lapwing rules-plus-vocabulary prototype

This prototype tests whether a Moonlander-sized translator can replace most of
Lapwing's dictionary with compositional rules and a compact vocabulary.

`learn_chunks.py` tests an optimistic compositional approximation rather than
implementing Lapwing theory directly.

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

`generate_model.py` builds the model consumed by the C firmware. It uses an
exact minimized acyclic word graph rather than the earlier proposed MPHF, so
vocabulary lookup has no false positives. `SPEC.md` owns the selected format,
acceptance constraints, resource use, and coverage measurements.

Generate the pinned independent frequency input and model with:

```sh
python3 -m pip install --target /tmp/lapwing-wordfreq wordfreq==3.1.1
PYTHONPATH=/tmp/lapwing-wordfreq \
  python3 generate_wordfreq.py /tmp/wordfreq-en-50000.tsv
python3 generate_model.py \
  "$DICTIONARY" /tmp/wordfreq-en-50000.tsv lapwing_model.bin \
  --vocabulary 7250 --beam 64 --report lapwing_model_report.json
```

The 50,000-row TSV has SHA-256
`831507abd1bf89dce3d60bd19a23629eeb7fc5f926a4d108ba1e8448fafcb4a4` and
contains 49,253 entries after the model's lexical filter.

## Held-out corpus evaluation

`evaluate_coverage.py` measures actual tokens in an independent corpus. The
corpus is narrow, mostly historical English and includes source boilerplate, so
its token coverage must remain separate from
the model-selection frequency metric. `SPEC.md` records the current results;
the JSON report records missing-word categories.

Reproduce the fixed corpus and evaluation with:

```sh
python3 fetch_heldout_corpora.py /tmp/lapwing-heldout
python3 evaluate_coverage.py \
  "$DICTIONARY" /tmp/wordfreq-en-50000.tsv /tmp/lapwing-heldout/*.txt \
  --report held-out-coverage.json
```

`heldout_corpora.json` pins source URLs and SHA-256 digests. Upstream text
changes fail closed rather than silently changing the benchmark.

## Interpretation

The translator is useful for common text but cannot replace desktop Lapwing:
briefs, collisions, irregular spelling, commands, and rare stroke forms still
require exact exceptions. The current design combines a small exact vocabulary
and briefs with hand-coded phonology and morphology; dictionary-equivalent
coverage still requires external flash or a host translator.

## Build and test

The heap-free implementation and deployment checks are specified in `SPEC.md`.
The generated rules and model are checked in; regenerate and test them with:

```sh
python3 generate_c_rules.py lapwing_rules.generated.h
python3 install_qmk.py /path/to/qmk/keyboards/zsa/moonlander/keymaps/KW9E9 \
  lapwing_model.bin
python3 -m unittest discover -p '*_test.py'
```
