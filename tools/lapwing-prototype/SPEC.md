# Lapwing embedded translator specification

Status: software-complete, hardware-unverified, August 27, 2026

## Purpose

This subsystem is a QMK-compatible Lapwing stenography translator for the ZSA
Moonlander Mark 1. It replaces most dictionary entries with explicit Lapwing
spelling rules, then uses a compact ranked vocabulary and exact exceptions to
resolve ambiguity and irregular outlines.

The intended application-data budget is 40,960 bytes. The translator must fit
beside the complete eight-layer `KW9E9` Oryx layout and its existing ZSA/QMK
features on `zsa/moonlander/reva`.

A complete replacement for desktop Plover or Javelin is not a goal. In
particular, this design does not attempt to retain the full Lapwing dictionary
or every alternate outline.

## Authority and generated artifacts

`hand_rules.py` is the authoritative editable definition of the linguistic
rules. It contains hand-written onset, vowel, coda, affix, folding, and
morphology behavior derived from Lapwing documentation.

`generate_c_rules.py` converts those definitions into
`lapwing_rules.generated.h`. The generated header is checked in so firmware
builds do not require Python. It must not be edited directly.

The C decoder is authoritative for embedded execution. The Python decoder is
both the rule authoring environment and a behavioral reference, but differences
caused by explicit firmware bounds are permitted when documented and tested.

## Ownership and side-effect boundaries

- `lapwing_decoder.c` owns its bounded internal workspace. It is non-reentrant
  and intended to run only from QMK's main processing thread.
- The rule core performs no HID, QMK, filesystem, allocation, or persistent
  storage operations.
- Callers own input outline strings and returned result storage.
- Vocabulary acceptance is supplied through `lw_word_accept_fn`; the rule core
  does not know the vocabulary representation.
- `lapwing_model.c` is the sole reader of the immutable generated model image.
- `lapwing_engine.c` owns pending outlines, commit timing, spacing,
  capitalization, and bounded undo history.
- `lapwing_qmk.c` is the only layer permitted to inspect QMK chord packets or
  emit HID key events.
- Python generators are the only writers of generated rule and model data.

## Public C interface

The decoder exposes these operations in `lapwing_decoder.h`:

```c
void lw_decode_outline(const char *outline, lw_candidates_t *result);
void lw_decode_outline_pruned(
    const char *outline,
    lw_prefix_accept_fn accept_prefix,
    void *context,
    lw_candidates_t *result
);
void lw_decode_outline_final_unpruned(
    const char *outline,
    lw_prefix_accept_fn accept_prefix,
    void *context,
    lw_candidates_t *result
);

size_t lw_translate_outline(
    const char *outline,
    lw_word_accept_fn accept,
    void *context,
    char output[][LW_MAX_WORD + 1],
    size_t output_capacity
);
```

`lw_decode_outline` returns generated spellings in deterministic rule order.
`lw_decode_outline_pruned` rejects combined spellings that cannot prefix an
exact vocabulary word, including on the final stroke. The model-only
`lw_decode_outline_final_unpruned` preserves inter-stroke pruning but retains raw
final analyses for exact orthographic repair. `lw_translate_outline` additionally applies a
caller-provided membership test.
A null acceptance callback accepts every generated spelling.

Current compile-time limits are:

| Limit | Firmware default |
|---|---:|
| Maximum word length | 32 characters |
| Maximum outline length | 16 strokes |
| Candidate frontier | 64 words |
| Onset or coda segmentations | 48 |

The host golden test raises the candidate frontier to 128. Firmware is expected
to check exact exceptions before bounded rule generation, preventing frequent
briefs and irregular spellings from consuming the frontier.

## Stroke representation

The implemented API currently accepts canonical steno strings, for example
`PAOEU/THOPB`. Each stroke is parsed into:

- left-hand consonant keys;
- vowel keys;
- right-hand consonant keys;
- star presence.

A dash explicitly separates left and right consonants when no vowel is present.
Otherwise, the first and last vowel keys delimit the vowel region. The QMK adapter converts Gemini packet bits into this representation and keeps
that packed protocol behind the adapter boundary.

Malformed, empty, oversized, or overlong outlines produce no candidates.

## Rule data format

Generated strings are deduplicated into one NUL-terminated byte pool. Rule
values are represented by 16-bit offsets into that pool. Each rule entry stores:

```c
typedef struct {
    uint16_t key_offset;
    uint16_t first_value;
    uint8_t value_count;
} lw_rule_entry_t;
```

The naturally aligned ARM representation occupies six bytes per entry. The
complete packed generated C rule representation currently occupies 4,181 bytes before
linker optimization. This supersedes the earlier 2,555-byte estimate based only
on NUL-terminated keys and values, which did not include lookup metadata.

Rule tables preserve Python declaration order. Segmentation prefers longer key
matches and uses table order to resolve equal-length alternatives.

## Decoding behavior

For each stroke, the decoder performs the following operations:

1. Add any whole-stroke spelling.
2. Segment left and right key sequences through their ordered rule tables.
3. Add starred onset or coda alternatives.
4. Add silent `KWR`, `y`, and `i` linker interpretations where applicable.
5. Combine onset, vowel, and coda spellings.
6. Add silent-e alternatives for configured long-vowel families.
7. Expand folded `G`, `D`, `S`, and `Z` suffixes.
8. Expand folded `L`, `T`, and final-position `R` endings.
9. Expand final vowel `E` as a folded `y` ending.

Across strokes, first-position prefix rules and later-position suffix rules are
considered before ordinary stroke decoding. Joining implements:

- direct concatenation;
- duplicate boundary-letter removal;
- optional `l` to `el` expansion;
- silent-e removal before vowel-leading affixes;
- `y` to `i` conversion;
- `s`, `es`, and `ies` plurals;
- `ed`, `d`, and `ied` past forms;
- final-e removal before `ing`;
- consonant doubling for eligible CVC roots.

All candidate collections preserve first occurrence and discard duplicates.
Overflow truncates later candidates rather than allocating memory.

## Translation-state behavior

The engine waits 240 milliseconds after the latest stroke before committing a
pending translation. Additional strokes within that window extend the outline.
If an extension cannot translate while the previous outline could, the previous
word commits and the new stroke starts another outline. `PWR` commits
immediately; a star-only stroke cancels pending input or undoes the latest
committed item.

Words receive one leading space after existing text. The first alphabetic word
and the first word after `.`, `?`, or `!` are capitalized. Punctuation strokes
are `TP-PL` for period, `KW-BG` for comma, `STPH-FPLT` for question mark, and
`SKWR-RBGS` for exclamation mark. Punctuation is attached without a leading
space. Undo history retains eight emitted items and restores the prior spacing
and capitalization state.

## Model format

The implemented linguistic data occupies 40,960 bytes:

| Component | Bytes |
|---|---:|
| Generated C rules | 4,181 |
| Binary vocabulary and exceptions | 36,779 |
| Total | 40,960 |

The binary model begins with a versioned 36-byte little-endian header. Its
6,275-word vocabulary is an exact minimized acyclic word graph. Each graph edge
uses 20 packed bits containing a five-bit alphabet symbol, a 13-bit target edge
offset, a target-terminal bit, and an end-of-edge-list bit. The graph occupies
20,540 bytes and cannot produce membership false positives.

Exception records pack a 29-bit outline hash and an 11-bit output-word ID into
five bytes. Generation rejects hash collisions between distinct selected
outlines. The 1,701 output words are lexically front-coded in 128-word blocks,
use a five-bit letter alphabet, and have 16-bit restart offsets. Runtime lookup
binary-searches the records and decodes at most 32 words from the selected
restart point.

Exact exceptions are checked before rule generation. The model is immutable,
self-contained, heap-free, and validated for magic, version, offsets, counts,
and bounds before use.

## Measured resource use

Measurements used ZSA `firmware25` commit
`c9fe0e2960cd96db31c627ab7215d93436305fed`, the complete `KW9E9` Oryx keymap,
and both `zsa/moonlander/reva` and `zsa/moonlander/revb`.

### Complete firmware build

The build includes the exact generated model, rule decoder, translation engine,
QMK chord adapter, delayed commit, punctuation, capitalization, and undo.

| Target | Firmware flash | Remaining flash | BSS | Linker heap |
|---|---:|---:|---:|---:|
| revA | 106,348 | 24,724 | 17,772 | 9,244 |
| revB | 108,588 | 22,484 | comparable | comparable |

The revA baseline without Lapwing occupies 57,908 bytes. The complete revA
translator therefore adds 48,440 bytes of linked flash, including all 40,960
bytes of linguistic data.

### Coverage and equivalence

Using the 20,000 highest-frequency benchmark tokens, conventional dictionary
and rule outlines cover 92.82% at the exact 40,960-byte budget. This metric
excludes every synthesized letter-by-letter outline. Productive morphology,
closed-compound composition, and standalone affixes contribute without
additional exception records. Authoritative starred-letter spelling of words
through sixteen letters, plus a final `AES` possessive stroke, raises reachable
coverage to 99.99%. It bypasses vocabulary membership only for these
explicit spelling paths. Phonetic paths use exact DAWG membership and prefix
pruning between strokes. When no exact final candidate survives, a second final-
stroke pass tests bounded insertion, deletion, transposition, vowel change,
consonant doubling, and common steno letter substitutions; repaired candidates
must still be exact DAWG words. The
conventional figure is lower than the discarded
94.97% MPHF estimate but has exact vocabulary membership and recoverable output.

With identical vocabulary-prefix pruning, the C decoder's ordered 64-candidate
output exactly matched the Python reference for the first 20,000 dictionary
outlines tested.

## Verification

Run all host tests from this directory:

```sh
python3 -m unittest discover -p '*_test.py'
```

The suite verifies Python rules and storage calculations, generated-file
freshness, strict C compilation, and representative C translations including:

| Outline | Required candidate |
|---|---|
| `KAT` | `cat` |
| `STPHAEUBG` | `snake` |
| `PAOEU/THOPB` | `python` |
| `PRAOE/SRAOU` | `preview` |
| `STKPWAPG` | `zapping` |
| `EURPBT/STAEUT` | `interstate` |
| `PHAOEURBG/TPO*EPB` | `microphone` |
| `HEL/-P/-FL` | `helpful` |

The C test is compiled with `-Wall -Wextra -Werror -pedantic`.

## Remaining deployment checks

The software implementation and complete revA/revB links are finished. Hardware
deployment still requires information or actions that cannot be established by
the repository alone:

1. Confirm whether the physical Moonlander flasher selects the `reva` or `revb`
   image.
2. Flash the matching image through the normal ZSA/QMK DFU workflow.
3. Exercise real chord rollover, the 240 ms commit delay, host keyboard layout,
   punctuation, and undo on the target computer.
4. Retain the stock Oryx firmware image so the keyboard can be restored if the
   hardware test exposes an adapter or timing defect.

The generated firmware must not be presented as hardware-verified until those
checks have been performed on the user's keyboard.
