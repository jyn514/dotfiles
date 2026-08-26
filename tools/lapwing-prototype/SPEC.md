# Lapwing embedded translator specification

Status: prototype implementation, August 27, 2026

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
- QMK chord capture, translation history, spacing, capitalization, commands,
  and HID output belong in a separate adapter.
- Python generators are the only writers of generated rule and model data.

## Public C interface

The decoder exposes two operations in `lapwing_decoder.h`:

```c
void lw_decode_outline(const char *outline, lw_candidates_t *result);

size_t lw_translate_outline(
    const char *outline,
    lw_word_accept_fn accept,
    void *context,
    char output[][LW_MAX_WORD + 1],
    size_t output_capacity
);
```

`lw_decode_outline` returns generated spellings in deterministic rule order.
`lw_translate_outline` additionally applies a caller-provided membership test.
A null acceptance callback accepts every generated spelling.

Current compile-time limits are:

| Limit | Firmware default |
|---|---:|
| Maximum word length | 32 characters |
| Maximum outline length | 8 strokes |
| Candidate frontier | 24 words |
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
Otherwise, the first and last vowel keys delimit the vowel region. The QMK
adapter may later parse a packed chord mask directly, but that representation
must remain behind the adapter boundary.

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
complete generated C rule representation currently occupies 4,413 bytes before
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

## Planned model format

The 40,960-byte application model is currently specified as:

| Component | Bytes |
|---|---:|
| Hand-written rules | 2,555 estimate used by coverage model |
| 14,000-word membership/rank index | 17,500 |
| 1,853 exception records and output words | 20,905 |
| Total | 40,960 |

The rule estimate and compiled rule representation currently differ by 1,858
bytes. The final generator must account for the actual compiled representation
or recover those bytes elsewhere; the firmware linker measurement includes the
larger real representation.

The vocabulary index is intended to use an immutable minimal perfect hash with
an 8-bit membership fingerprint. Its resulting ID is the frequency rank.

Each exception record budgets six bytes for MPHF metadata, a 24-bit fingerprint,
and a 16-bit output-word ID. Exception output words are lexically front-coded in
32-word blocks with 16-bit restart offsets. Lookup must verify the fingerprint
before returning text. No probabilistic match may bypass that verification.

The MPHF structures have not yet been implemented. Their generator must emit a
self-contained binary and prove its exact byte count rather than relying on the
current estimate.

## Measured resource use

Measurements used ZSA `firmware25` commit
`c9fe0e2960cd96db31c627ab7215d93436305fed`, the complete `KW9E9` Oryx keymap,
and target `zsa/moonlander/reva`.

### Decoder sizing build

A real C decoder build with the complete generated rule tables and a 40,960-byte
model placeholder produced:

| Measurement | Bytes |
|---|---:|
| Existing ZSA firmware and layout | 57,908 flash |
| Firmware with decoder and model | 107,160 flash |
| Model placeholder | 40,960 flash |
| Linked decoder and rule delta | 8,292 flash |
| Remaining application flash | 23,912 |
| Decoder workspace increase | 7,144 BSS |
| Remaining linker heap | 16,268 |

The result demonstrates that the current decoder architecture links on revA.
It does not establish revB feasibility or reserve space for every remaining
adapter and model operation.

### Coverage model

Using the 20,000 highest-frequency benchmark tokens, the corrected 40,960-byte
model estimates 94.97% frequency-weighted coverage. This includes storage for
exception output words. It is not an end-to-end firmware measurement and still
assumes the proposed MPHF footprint.

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

## Remaining work

1. Generate and verify the immutable vocabulary MPHF and fingerprints.
2. Generate exception outline lookup and front-coded output recovery.
3. Make exact exception lookup precede bounded rule generation.
4. Add packed QMK steno-chord parsing and outline-boundary handling.
5. Add HID text publication, spacing, capitalization, punctuation, replacement,
   history, and undo according to an explicit translation-state specification.
6. Compare C and Python outputs over a broad corpus and quantify losses from the
   24-candidate firmware bound.
7. Rebuild the actual model into the complete revA firmware and remeasure flash,
   BSS, stack use, and false-positive behavior.
8. Confirm the physical keyboard revision before producing flashable firmware.

No firmware should be flashed until exception lookup, translation-state tests,
and complete-link measurements pass.
