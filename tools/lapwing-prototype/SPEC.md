# Lapwing embedded translator specification

Status: software-complete, hardware-unverified, August 28, 2026

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
Otherwise, the first and last vowel keys delimit the vowel region. A standalone
initial number-bar stroke is normalized into the following stroke, so
`#/SKWRO*PB` and `#SKWRO*PB` perform the same proper-noun lookup. The QMK
adapter converts Gemini packet bits into this representation and keeps that
packed protocol behind the adapter boundary.

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
current size appears in the model table below; it supersedes the earlier
2,555-byte estimate, which omitted lookup metadata.

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

- direct and exact-vocabulary-gated hyphenated concatenation;
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

Emily modifier strokes ending in `LGTS` are handled before lexical translation.
They compositionally cover letters, digits, function keys, common US-keyboard
symbols, navigation, media keys, and any nonempty combination of Shift, Control,
Alt, and Super. Modifier actions commit pending text, attach on both sides, and
form an undo barrier because arbitrary host key actions cannot be reversed by
translator backspaces. Non-US symbolic variants and `F0` are rejected.

The `STPH` and `#TPH` movement families implement the forty actions from
`lapwing-movement.modal`. A matching entry stroke executes its action and opens
a modal continuation; matching suffix strokes repeat movement without the
prefix, while the first mismatch closes the mode and is retried normally.
Movement actions share the modifier action's pending-text and undo boundary.

Words receive one leading space after existing text. The first alphabetic word
and the first word after `.`, `?`, or `!` are capitalized. Punctuation strokes
are `TP-PL` for period, `KW-BG` for comma, `STPH-FPLT` for question mark, and
`SKWR-RBGS` for exclamation mark. Punctuation is attached without a leading
space. Undo history retains eight emitted items and restores the prior spacing
and capitalization state.

## Model format

The implemented linguistic data occupies 40,959 bytes of the 40,960-byte
budget:

| Component | Bytes |
|---|---:|
| Generated C rules | 4,181 |
| Binary vocabulary and exceptions | 36,778 |
| Total | 40,959 |

Model generation uses the US-English benchmark stack prepared in `README.md`.
The number bar is retained as `#` for exact lookup, omitted from phonetic
segmentation, and used to capitalize accepted proper-noun output. Dynamic
Python dictionaries remain runtime facilities and are not serialized.

The binary model begins with a versioned 48-byte little-endian header. Its
7,250-word ranked frontier is rebalanced to a 7,190-word exact minimized acyclic
word graph. Up to 100 low-ranked tokens without conventional outlines are
removed; the reference frontier uses all 100 removals. The next 200 outlined words are
probed against a temporary exact prefix set, and the first forty that resolve
conventionally are admitted. Each graph edge uses 20 packed bits containing a five-bit alphabet symbol, a
13-bit target edge offset, a target-terminal bit, and an end-of-edge-list bit.
Target value `0x1ffe` escapes to a sorted table of four-byte `(edge index,
16-bit target)` records; `0x1fff` remains the leaf sentinel. Only out-of-range
targets pay for widening. The graph occupies 25,273 bytes, including 537
overflow records, and cannot produce membership false positives.

Grouped morphology stores 62 exact spelling recipes and 1,709 licensed roots in
3,817 bytes. Each recipe contains literal root/output tails followed by sorted,
delta-varint-coded primary-root IDs. An ID is the root's terminal DAWG edge and
length and is admitted only when that pair identifies exactly one primary word.
The C decoder reverses the recipe, verifies that exact root identity, and never
admits an unlicensed transformed spelling.

Before selection, the generator may synthesize conventional outlines by
composing exact hyphenated components or spelling chunks decoded from
non-starred strokes observed in the source dictionaries. Write-out chunks must
contain at least two letters and the complete synthesized outline must reproduce
the target under the bounded decoder with exact target-prefix pruning. Newly
synthesized roots then participate in ordinary inflection and possessive rules.
Regular `-or/-our`, `-ize/-ise`, `-er/-re`, and doubled-`l` spelling variants
reuse source outlines and remain exact-vocabulary gated in both Python and C.

Exception records pack a 29-bit outline hash and an 11-bit output-word ID into
five bytes. Generation rejects hash collisions between distinct selected
outlines. The 787 output words are lexically front-coded in 384-word blocks,
use a five-bit letter alphabet, and have 16-bit restart offsets. Runtime lookup
binary-searches the records and decodes at most 384 words from the selected
restart point.

The model is immutable, self-contained, heap-free, and validated for magic,
version, offsets, counts, and bounds before use.

## Measured resource use

Measurements used ZSA `firmware25` commit
`c9fe0e2960cd96db31c627ab7215d93436305fed`, the complete `KW9E9` Oryx keymap,
and both `zsa/moonlander/reva` and `zsa/moonlander/revb`.

### Complete firmware build

| Target | Firmware flash | Remaining flash | BSS | Linker heap |
|---|---:|---:|---:|---:|
| revA | 107,872 | 23,200 | 17,772 | 9,244 |
| revB | 110,116 | 20,956 | comparable | comparable |

The official revA image without Lapwing occupies 57,956 bytes. The complete revA
translator therefore adds 49,916 bytes of linked flash, including all 40,959
bytes of linguistic data.

### Coverage and equivalence

Using the pinned frequency input prepared in `README.md`, conventional
dictionary and rule outlines cover 94.1539% after Zipf weighting over the first
20,000 valid types. This is an in-sample metric: the cutoff is arbitrary, the
model was tuned against the same list, and the entries are types rather than
prose tokens.

The conventional metric excludes synthesized letter-by-letter outlines.
Productive morphology, closed compounds, and standalone affixes require no
additional exception records. Authoritative starred-letter spelling through
sixteen letters, plus a final `AES` possessive stroke, raises reachable coverage
to 99.99% and bypasses membership only for explicit spelling paths.

Phonetic paths use exact DAWG membership and inter-stroke prefix pruning. If no
exact final candidate survives, a second final-stroke pass applies bounded
orthographic and steno-specific repairs; every result must still be an exact
DAWG word. This exact design replaces the discarded 94.97% MPHF estimate, which
could not provide exact membership within its claimed representation.

A frozen-model evaluation over 793,338 normalized tokens from five Project
Gutenberg works and RFC 9110 measured 87.45% conventional coverage, ranging
from 82.67% to 91.30% by corpus. The same model scores 99.39%, 97.25%, 94.15%,
and 91.74% over the first 5,000, 10,000, 20,000, and all 49,253 valid frequency
entries. Corpus token coverage and weighted frequency-list coverage are
separate measurements.

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

Hardware deployment still requires information or actions that cannot be
established by the repository alone:

1. Confirm whether the physical Moonlander flasher selects the `reva` or `revb`
   image.
2. Flash the matching image through the normal ZSA/QMK DFU workflow.
3. Exercise real chord rollover, the 240 ms commit delay, host keyboard layout,
   punctuation, and undo on the target computer.
4. Retain the stock Oryx firmware image so the keyboard can be restored if the
   hardware test exposes an adapter or timing defect.

The generated firmware must not be presented as hardware-verified until those
checks have been performed on the user's keyboard.
