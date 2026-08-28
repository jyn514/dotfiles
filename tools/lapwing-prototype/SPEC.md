# Lapwing embedded translator specification

Status: software-complete, hardware-unverified, August 28, 2026

## Purpose

This subsystem is a QMK-compatible Lapwing stenography translator for the ZSA
Moonlander Mark 1. It replaces most dictionary entries with explicit Lapwing
spelling rules, then uses a compact ranked vocabulary and exact exceptions to
resolve ambiguity and irregular outlines.

The revA application-data budget is 50,960 bytes. The translator must fit
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
prefix, while the first mismatch closes the mode and is retried normally. The
same forty suffix strokes are also accepted directly as semi-modal movement;
direct actions do not open a continuation mode. Movement actions share the
modifier action's pending-text and undo boundary.

Words receive one leading space after existing text. The first alphabetic word
and the first word after `.`, `?`, or `!` are capitalized. Punctuation strokes
are `TP-PL` for period, `KW-BG` for comma, `STPH-FPLT` for question mark, and
`SKWR-RBGS` for exclamation mark. Punctuation is attached without a leading
space. Undo history retains eight emitted items and restores the prior spacing
and capitalization state.

## Model format

The implemented linguistic data occupies 50,959 bytes of the 50,960-byte tier:

| Component | Bytes |
|---|---:|
| Generated C rules | 4,228 |
| Binary vocabulary and exceptions | 46,731 |
| Total | 50,959 |

Model generation uses the US-English benchmark stack prepared in `README.md`.
The number bar is retained as `#` for exact lookup, omitted from phonetic
segmentation, and used to capitalize accepted proper-noun output. Dynamic
Python dictionaries remain runtime facilities and are not serialized.

The binary model begins with a versioned 48-byte little-endian header. Its
14,200-word ranked frontier is rebalanced to a 14,140-word exact succinct LOUDS
trie. Up to 100 low-ranked tokens without conventional outlines are removed;
the reference frontier uses all 100 removals. The next 200 outlined words are
probed against a temporary exact prefix set, and the first forty that resolve
conventionally are admitted.

Trie nodes use breadth-first numbering. Three packed streams store five-bit
edge labels, LOUDS topology (`degree` one-bits followed by a zero per node), and
one terminal bit per node. Twenty-four-bit `select0` checkpoints every 64 nodes
bound topology scans; a child node is its incoming edge ordinal plus one. The
trie occupies 35,394 bytes for 33,806 nodes and 33,805 edges and cannot produce
membership false positives.

Grouped morphology stores 33 exact spelling recipes and 1,716 licensed roots in
3,823 bytes. Each recipe contains literal root/output tails followed by sorted,
delta-varint-coded primary-root IDs. An ID is the root's terminal trie node and
length; trie nodes are unique word-path identities.
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
Atomic `fl`, `cl`, and `pl` initial clusters and doubled initial/final `s`
spellings cover ordinary cluster and `-ss-` families under the same exact gate.

The 1,633 exception fingerprints are strictly sorted and Elias–Fano encoded in
7,466 bytes. Eighteen low bits are packed directly; quotient buckets use a unary
high stream with 16-bit `select0` checkpoints every 64 buckets. Each matching
fingerprint references a 16-bit-width terminal LOUDS node, so exception output
spelling is reconstructed from the authoritative primary trie rather than
stored again. Generation rejects fingerprints that collide across any known
candidate outline. Lookup scans at most 63 quotient terminators before a bounded
binary search within one bucket.

The model is immutable, self-contained, heap-free, and validated for magic,
version, offsets, counts, and bounds before use.

## Measured resource use

Measurements used ZSA `firmware25` commit
`c9fe0e2960cd96db31c627ab7215d93436305fed`, Oryx revision `XbQoDo` of the
complete eight-layer `KW9E9` layout, and Arm GNU Toolchain 13.2.1. Baseline and
Lapwing images were compiled from identical downloaded source for both
`zsa/moonlander/reva` and `zsa/moonlander/revb`.

### Complete firmware build

| Target | Baseline flash | Lapwing flash | Lapwing cost | Result | BSS | Linker heap |
|---|---:|---:|---:|---:|---:|---:|
| revA | 60,016 | 127,340 | 67,324 | 3,732 bytes free | 17,828 | 9,180 |
| revB | 62,216 | — | — | linker overflow by 6,692 bytes | — | — |

Flash figures are linked `text + data`. RevA has a 131,072-byte application
region. RevB's linker region is smaller; the 50,959-byte linguistic tier does
not fit it. The embedded format-v10 binary occupies 46,731 bytes and generated
rules add 4,228 bytes. These are prototype measurements; the repository's
normal Moonlander flashing workflow does not install the translator.

### Coverage and equivalence

Using the pinned frequency input prepared in `README.md`, conventional
dictionary and rule outlines cover 97.9571% after Zipf weighting over the first
20,000 valid types. This is an in-sample metric: the cutoff is arbitrary, the
model was tuned against the same list, and the entries are types rather than
prose tokens.

The conventional metric excludes synthesized letter-by-letter outlines.
Productive morphology, closed compounds, and standalone affixes require no
additional exception records. Authoritative starred-letter spelling through
sixteen letters, plus a final `AES` possessive stroke, raises reachable coverage
to 99.99% and bypasses membership only for explicit spelling paths.

Phonetic paths use exact LOUDS-trie membership and inter-stroke prefix pruning. If no
exact final candidate survives, a second final-stroke pass applies bounded
orthographic and steno-specific repairs; every result must still be an exact
trie word. This exact design replaces the discarded 94.97% MPHF estimate, which
could not provide exact membership within its claimed representation.

A frozen-model evaluation over 793,338 normalized tokens from five Project
Gutenberg works and RFC 9110 measured 91.61% conventional coverage, ranging
from 87.75% to 94.43% by corpus. The same model scores 99.39%, 99.26%, 97.96%,
and 95.45% over the first 5,000, 10,000, 20,000, and all 49,253 valid frequency
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
