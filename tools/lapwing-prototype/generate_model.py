#!/usr/bin/env python3
"""Generate the exact flash-resident Lapwing vocabulary and exception model."""

from __future__ import annotations

import argparse
import json
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path

import hand_rules
from analyze_storage import common_prefix_length, encode_varint
from common_text_budget import load_frequencies

MAGIC = b"LWMD"
VERSION = 8
HEADER = struct.Struct("<4sBBHIIIIIIIIII")
EXCEPTION_HASH_BITS = 29
EXCEPTION_ID_BITS = 11
EXCEPTION_HASH_MASK = (1 << EXCEPTION_HASH_BITS) - 1
BLOCK_WORDS = 384
VOCABULARY_REBALANCE_REMOVALS = 100
VOCABULARY_REBALANCE_ADDITIONS = 40
RULE_BYTES = 4228
DEFAULT_TOTAL_DATA_BUDGET = 40 * 1024
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
ALPHABET = "abcdefghijklmnopqrstuvwxyz'-"
LEAF_OFFSET = 0x1FFF
OVERFLOW_OFFSET = 0x1FFE
OVERFLOW_BLOCK_RECORDS = 32
OVERFLOW_CHECKPOINT = struct.Struct("<HHH")
STANDALONE_OUTLINES = {
    "co": "KOE",
    "non": "TPHOPB",
    "anti": "APB/TEU",
    "un": "UPB",
    "im": "EUPL",
    "em": "EPL",
    "en": "EPB",
    "ii": "EU/EU",
    "iii": "EU/EU/EU",
    "ll": "HR/HR",
}


def hash32(data: bytes, seed: int = 2166136261) -> int:
    value = seed
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    return value


@dataclass(frozen=True)
class DawgState:
    terminal: bool
    edges: tuple[tuple[str, int], ...]


def build_dawg(words: list[str]) -> tuple[bytes, int, int]:
    root: dict[str, dict] = {}
    terminal = ""
    for word in words:
        node = root
        for character in word:
            if character not in ALPHABET:
                raise ValueError(f"unsupported vocabulary character: {character!r}")
            node = node.setdefault(character, {})
        node[terminal] = {}

    registry: dict[tuple[bool, tuple[tuple[str, int], ...]], int] = {}
    states: list[DawgState] = []

    def intern(node: dict[str, dict]) -> int:
        edges = tuple(sorted((character, intern(child))
                             for character, child in node.items() if character))
        signature = (terminal in node, edges)
        if signature not in registry:
            registry[signature] = len(states)
            states.append(DawgState(*signature))
        return registry[signature]

    root_id = intern(root)
    incoming = [0] * len(states)
    for state in states:
        for _, target_id in state.edges:
            incoming[target_id] += 1
    nonleaf_ids = [state_id for state_id, state in enumerate(states) if state.edges]
    def compare_density(left: int, right: int) -> int:
        left_score = incoming[left] * len(states[right].edges)
        right_score = incoming[right] * len(states[left].edges)
        if left_score != right_score:
            return -1 if left_score > right_score else 1
        if incoming[left] != incoming[right]:
            return -1 if incoming[left] > incoming[right] else 1
        return left - right

    density_order = sorted(nonleaf_ids, key=cmp_to_key(compare_density))
    inline_ids = []
    inline_edges = 0
    for state_id in density_order:
        state_edges = len(states[state_id].edges)
        if inline_edges + state_edges <= OVERFLOW_OFFSET:
            inline_ids.append(state_id)
            inline_edges += state_edges
    inline_set = set(inline_ids)
    ordered_ids = inline_ids + [
        state_id for state_id in nonleaf_ids if state_id not in inline_set
    ]
    offsets: list[int] = [LEAF_OFFSET] * len(states)
    edge_count = 0
    for state_id in ordered_ids:
        offsets[state_id] = edge_count
        edge_count += len(states[state_id].edges)
    if edge_count > 0xFFFF:
        raise ValueError("vocabulary DAWG exceeds 16-bit edge indexes")
    target_ids = {target_id for state in states for _, target_id in state.edges}
    if any(states[target_id].edges and offsets[target_id] > 0xFFFF
           for target_id in target_ids):
        raise ValueError("vocabulary DAWG exceeds 16-bit overflow targets")

    values = []
    overflows = []
    edge_index = 0
    for state_id in ordered_ids:
        state = states[state_id]
        for index, (character, target_id) in enumerate(state.edges):
            target = states[target_id]
            target_offset = offsets[target_id]
            if target.edges and target_offset >= OVERFLOW_OFFSET:
                overflows.append((edge_index, target_offset))
                target_offset = OVERFLOW_OFFSET
            value = ALPHABET.index(character)
            value |= target_offset << 5
            value |= int(target.terminal) << 18
            value |= int(index + 1 == len(state.edges)) << 19
            values.append(value)
            edge_index += 1
    encoded = bytearray((len(values) * 20 + 7) // 8)
    accumulator = 0
    bits = 0
    output = 0
    for value in values:
        accumulator |= value << bits
        bits += 20
        while bits >= 8:
            encoded[output] = accumulator & 0xff
            output += 1
            accumulator >>= 8
            bits -= 8
    if bits:
        encoded[output] = accumulator & 0xff
    checkpoints = bytearray()
    overflow_stream = bytearray()
    for block_start in range(0, len(overflows), OVERFLOW_BLOCK_RECORDS):
        block = overflows[block_start:block_start + OVERFLOW_BLOCK_RECORDS]
        first_edge, first_target = block[0]
        if len(overflow_stream) > 0xFFFF:
            raise ValueError("DAWG overflow stream exceeds 16-bit offsets")
        checkpoints += OVERFLOW_CHECKPOINT.pack(
            len(overflow_stream), first_edge, first_target - OVERFLOW_OFFSET,
        )
        previous_edge, previous_target = first_edge, first_target
        for edge_index, target_offset in block[1:]:
            overflow_stream += encode_varint(edge_index - previous_edge)
            target_delta = target_offset - previous_target
            zigzag_delta = target_delta * 2 if target_delta >= 0 else -target_delta * 2 - 1
            overflow_stream += encode_varint(zigzag_delta)
            previous_edge, previous_target = edge_index, target_offset
    encoded += checkpoints + overflow_stream
    return bytes(encoded), offsets[root_id], edge_count


def decode_varint_bytes(data: bytes | memoryview, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 32:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("invalid overflow varint")


def varint_size(value: int) -> int:
    size = 1
    while value >= 0x80:
        value >>= 7
        size += 1
    return size


def packed_letters_size(length: int) -> int:
    return (length * 5 + 7) // 8


def pack_letters(text: str) -> bytes:
    output = bytearray(packed_letters_size(len(text)))
    accumulator = 0
    bits = 0
    index = 0
    for character in text:
        accumulator |= ALPHABET.index(character) << bits
        bits += 5
        while bits >= 8:
            output[index] = accumulator & 0xff
            index += 1
            accumulator >>= 8
            bits -= 8
    if bits:
        output[index] = accumulator & 0xff
    return bytes(output)


def word_delta_size(prefix: int, suffix: int) -> int:
    if prefix < 15 and suffix < 15:
        return 1
    return 1 + varint_size(prefix) + varint_size(suffix)


def encode_word_delta(prefix: int, suffix: int) -> bytes:
    if prefix < 15 and suffix < 15:
        return bytes((prefix << 4 | suffix,))
    return b"\xff" + encode_varint(prefix) + encode_varint(suffix)


def exception_storage_size(exceptions: list[ExceptionEntry]) -> int:
    words = sorted(entry.word for entry in exceptions)
    size = len(exceptions) * 5 + 2 * ((len(words) + BLOCK_WORDS - 1) // BLOCK_WORDS)
    previous = ""
    for index, word in enumerate(words):
        if index % BLOCK_WORDS == 0:
            size += varint_size(len(word)) + packed_letters_size(len(word))
        else:
            prefix = common_prefix_length(previous, word)
            suffix = len(word) - prefix
            size += word_delta_size(prefix, suffix) + packed_letters_size(suffix)
        previous = word
    return size


def encode_word_blocks(words: list[str]) -> tuple[bytes, bytes]:
    offsets = bytearray()
    encoded = bytearray()
    for block_start in range(0, len(words), BLOCK_WORDS):
        if len(encoded) > 0xFFFF:
            raise ValueError("exception output pool exceeds 16-bit offsets")
        offsets += struct.pack("<H", len(encoded))
        previous = ""
        for index, word in enumerate(words[block_start:block_start + BLOCK_WORDS]):
            raw = word.encode("ascii")
            if index == 0:
                encoded += encode_varint(len(raw)) + pack_letters(word)
            else:
                prefix = common_prefix_length(previous, word)
                suffix = word[prefix:]
                encoded += encode_word_delta(prefix, len(suffix)) + pack_letters(suffix)
            previous = word
    return bytes(offsets), bytes(encoded)


@dataclass(frozen=True)
class ExceptionEntry:
    outline: str
    word: str


@dataclass(frozen=True)
class MorphologyGroup:
    """An exact spelling transformation licensed for primary-root IDs."""
    root_tail: str
    output_tail: str
    root_ids: tuple[int, ...]


def primary_root_ids(vocabulary: list[str], dawg_info: tuple[bytes, int, int]) -> dict[str, int]:
    """Return only (terminal edge, length) identities unique in the primary DAWG."""
    dawg, root, edges = dawg_info

    base_size = (edges * 20 + 7) // 8
    overflow_count = sum(
        1 for index in range(edges)
        if ((int.from_bytes(dawg[index * 20 // 8:index * 20 // 8 + 4], "little")
             >> (index * 20 % 8 + 5)) & LEAF_OFFSET) == OVERFLOW_OFFSET
    )
    checkpoint_count = (overflow_count + OVERFLOW_BLOCK_RECORDS - 1) // OVERFLOW_BLOCK_RECORDS
    checkpoint_start = base_size
    stream = memoryview(dawg)[checkpoint_start + checkpoint_count * OVERFLOW_CHECKPOINT.size:]
    overflow_records: dict[int, int] = {}
    for checkpoint_index in range(checkpoint_count):
        stream_offset, edge_index, target_residual = OVERFLOW_CHECKPOINT.unpack_from(
            dawg, checkpoint_start + checkpoint_index * OVERFLOW_CHECKPOINT.size,
        )
        cursor = stream_offset
        target = OVERFLOW_OFFSET + target_residual
        overflow_records[edge_index] = target
        block_records = min(
            OVERFLOW_BLOCK_RECORDS,
            overflow_count - checkpoint_index * OVERFLOW_BLOCK_RECORDS,
        )
        for _ in range(1, block_records):
            edge_delta, cursor = decode_varint_bytes(stream, cursor)
            target_delta, cursor = decode_varint_bytes(stream, cursor)
            edge_index += edge_delta
            signed_target_delta = -(target_delta // 2) - 1 if target_delta & 1 else target_delta // 2
            target += signed_target_delta
            overflow_records[edge_index] = target

    def read_edge(index: int) -> tuple[int, int, bool]:
        bit = index * 20
        value = int.from_bytes(dawg[bit // 8:bit // 8 + 4], "little")
        edge = (value >> (bit % 8)) & 0xfffff
        target = (edge >> 5) & LEAF_OFFSET
        if target == OVERFLOW_OFFSET:
            target = overflow_records[index]
        return edge & 31, target, bool(edge & (1 << 19))

    identities: dict[int, list[str]] = defaultdict(list)
    for word in vocabulary:
        state = root
        final_edge = -1
        for character in word:
            wanted = ALPHABET.index(character)
            for index in range(state, edges):
                letter, target, last = read_edge(index)
                if letter == wanted:
                    final_edge = index
                    state = target
                    break
                if last:
                    raise AssertionError(word)
        identity = (final_edge << 5) | len(word)
        identities[identity].append(word)
    return {words[0]: identity for identity, words in identities.items() if len(words) == 1}


def encode_morphology(groups: list[MorphologyGroup]) -> bytes:
    encoded = bytearray()
    for group in sorted(groups, key=lambda item: (item.output_tail, item.root_tail)):
        if not group.root_ids or len(group.root_tail) > 31 or len(group.output_tail) > 31:
            raise ValueError("invalid morphology group")
        encoded += bytes((len(group.root_tail), len(group.output_tail)))
        encoded += pack_letters(group.root_tail) + pack_letters(group.output_tail)
        encoded += encode_varint(len(group.root_ids))
        previous = 0
        for root_id in sorted(group.root_ids):
            encoded += encode_varint(root_id - previous)
            previous = root_id
    return bytes(encoded)


def derivations_for_word(word: str) -> list[tuple[str, str]]:
    derivations: list[tuple[str, str]] = []
    if word.endswith("'s"):
        derivations.append((word[:-2], "AES"))
    if word.endswith("ies"):
        derivations.append((word[:-3] + "y", "-Z"))
    if word.endswith("es"):
        derivations.extend(((word[:-2], "-Z"), (word[:-1], "-Z")))
    if word.endswith("s"):
        derivations.append((word[:-1], "-Z"))
    if word.endswith("ied"):
        derivations.append((word[:-3] + "y", "-D"))
    if word.endswith("ed"):
        stem = word[:-2]
        derivations.extend(((stem, "-D"), (stem + "e", "-D")))
        if len(stem) > 2 and stem[-1:] == stem[-2:-1]:
            derivations.append((stem[:-1], "-D"))
    if word.endswith("ing"):
        stem = word[:-3]
        derivations.extend(((stem, "-G"), (stem + "e", "-G")))
        if len(stem) > 2 and stem[-1:] == stem[-2:-1]:
            derivations.append((stem[:-1], "-G"))
    if word.endswith("ly"):
        derivations.append((word[:-2], "HREU"))
    for outline, additions in hand_rules.SUFFIXES.items():
        for addition in additions:
            if addition in {"s", "ed", "ing", "ly", "'s"}:
                continue
            if word.endswith(addition) and len(word) > len(addition):
                derivations.append((word[:-len(addition)], outline))
    return list(dict.fromkeys(derivations))


def add_derivative_outlines(outlines_by_word: dict[str, list[str]],
                            words: list[str], rounds: int = 4) -> None:
    """Apply productive morphology to every currently known root outline."""
    for _ in range(rounds):
        changed = False
        for word in words:
            for root, suffix in derivations_for_word(word):
                for outline in outlines_by_word.get(root, ())[:4]:
                    candidate = outline + "/" + suffix
                    values = outlines_by_word.setdefault(word, [])
                    if candidate not in values:
                        values.append(candidate)
                        changed = True
        if not changed:
            break


def add_closed_compound_outlines(outlines_by_word: dict[str, list[str]],
                                 words: list[str]) -> None:
    """Compose unhyphenated words from known roots at stroke boundaries."""
    for _ in range(2):
        changed = False
        for word in words:
            if not word.isalpha():
                continue
            for split in range(2, len(word) - 1):
                left = outlines_by_word.get(word[:split], ())
                right = outlines_by_word.get(word[split:], ())
                for left_outline in left[:2]:
                    for right_outline in right[:2]:
                        candidate = left_outline + "/" + right_outline
                        if candidate.count("/") >= 8:
                            continue
                        values = outlines_by_word.setdefault(word, [])
                        if candidate not in values:
                            values.append(candidate)
                            changed = True
        if not changed:
            break


def add_hyphenated_outlines(outlines_by_word: dict[str, list[str]],
                            words: list[str]) -> None:
    """Compose exact hyphenated vocabulary from independently known parts."""
    for word in words:
        parts = word.split("-")
        if len(parts) < 2 or any(not part for part in parts):
            continue
        choices = [outlines_by_word.get(part, ())[:2] for part in parts]
        if any(not choice for choice in choices):
            continue
        candidate = "/".join(choice[0] for choice in choices)
        if candidate.count("/") >= 16:
            continue
        values = outlines_by_word.setdefault(word, [])
        if candidate not in values:
            values.append(candidate)


def add_write_out_outlines(outlines_by_word: dict[str, list[str]],
                           words: list[str], beam: int = 64) -> None:
    """Synthesize regular write-out outlines from observed Lapwing strokes.

    Each spelling chunk must contain at least two letters. This admits ordinary
    phonetic write-out while preventing the optimization from relabeling
    letter-by-letter fingerspelling as conventional translation.
    """
    observed_strokes = {
        stroke
        for outlines in outlines_by_word.values()
        for outline in outlines
        for stroke in outline.split("/")
        if "*" not in stroke and not stroke.startswith("#")
    }
    chunks: dict[str, list[str]] = defaultdict(list)
    for stroke in sorted(observed_strokes, key=lambda value: (len(value), value)):
        for final_position in (False, True):
            for spelling in hand_rules.decode_stroke_analyses(stroke, final_position):
                if not spelling.isalpha() or not 2 <= len(spelling) <= 8:
                    continue
                values = chunks[spelling]
                if stroke not in values and len(values) < 3:
                    values.append(stroke)

    for word in words:
        if outlines_by_word.get(word) or not word.isalpha() or len(word) < 4:
            continue
        best: list[list[str] | None] = [None] * (len(word) + 1)
        best[0] = []
        for end in range(2, len(word) + 1):
            for start in range(max(0, end - 8), end - 1):
                if best[start] is None or word[start:end] not in chunks:
                    continue
                candidate = best[start] + [chunks[word[start:end]][0]]
                if len(candidate) <= 8 and (
                    best[end] is None or len(candidate) < len(best[end])
                ):
                    best[end] = candidate
        if best[-1] is None:
            continue
        outline = "/".join(best[-1])
        prefixes = {word[:length] for length in range(1, len(word) + 1)}
        if word in hand_rules.generate_outline(outline, beam, prefixes):
            outlines_by_word.setdefault(word, []).append(outline)


def regular_spelling_roots(word: str) -> list[str]:
    """Return common US spellings for an exact British-spelling target."""
    roots = []
    if "our" in word:
        roots.append(word.replace("our", "or"))
    if "is" in word:
        roots.append(word.replace("is", "iz"))
    if word.endswith("re"):
        roots.append(word[:-2] + "er")
    if word.endswith(("lled", "lling")):
        roots.append(word.replace("ll", "l", 1))
    return list(dict.fromkeys(roots))


def add_productive_outlines(outlines_by_word: dict[str, list[str]],
                            words: list[str]) -> None:
    """Add outlines implied by general spelling and composition rules."""
    for word in words:
        if word in outlines_by_word:
            continue
        spelling_outlines = [
            outline
            for root in regular_spelling_roots(word)
            for outline in outlines_by_word.get(root, ())[:4]
        ]
        if spelling_outlines:
            outlines_by_word.setdefault(word, []).extend(spelling_outlines)
            continue
        if word in STANDALONE_OUTLINES:
            outlines_by_word.setdefault(word, []).append(STANDALONE_OUTLINES[word])
            continue
        for outline, values in hand_rules.PREFIXES.items():
            if word in values:
                outlines_by_word.setdefault(word, []).append(outline)

    add_derivative_outlines(outlines_by_word, words)
    add_closed_compound_outlines(outlines_by_word, words)
    add_write_out_outlines(outlines_by_word, words)
    add_hyphenated_outlines(outlines_by_word, words)
    # Synthesized words become roots for possessives and ordinary inflections.
    add_derivative_outlines(outlines_by_word, words, rounds=3)



def pack_model(vocabulary: list[str], exceptions: list[ExceptionEntry],
               dawg_info: tuple[bytes, int, int] | None = None,
               morphology: list[MorphologyGroup] | None = None) -> bytes:
    dawg, root_offset, edge_count = dawg_info or build_dawg(vocabulary)
    outputs_by_outline: dict[str, str] = {}
    for entry in exceptions:
        previous = outputs_by_outline.setdefault(entry.outline, entry.word)
        if previous != entry.word:
            raise ValueError(
                f"exception outline has multiple outputs: {entry.outline}: {previous}, {entry.word}"
            )
    output_words = sorted({entry.word for entry in exceptions})
    word_ids = {word: index for index, word in enumerate(output_words)}
    if len(output_words) >= 1 << EXCEPTION_ID_BITS:
        raise ValueError("exception output count exceeds packed IDs")
    records = sorted((hash32(entry.outline.encode("ascii")) & EXCEPTION_HASH_MASK,
                      word_ids[entry.word], entry.outline)
                     for entry in exceptions)
    for left, right in zip(records, records[1:]):
        if left[0] == right[0] and left[2] != right[2]:
            raise ValueError(f"exception hash collision: {left[2]} and {right[2]}")
    record_bytes = b"".join(
        ((fingerprint << EXCEPTION_ID_BITS) | word_id).to_bytes(5, "little")
        for fingerprint, word_id, _ in records
    )
    block_offsets, word_data = encode_word_blocks(output_words)
    base_edge_bytes = (edge_count * 20 + 7) // 8
    overflow_count = sum(
        1 for index in range(edge_count)
        if ((int.from_bytes(dawg[index * 20 // 8:index * 20 // 8 + 4], "little")
             >> (index * 20 % 8 + 5)) & LEAF_OFFSET) == OVERFLOW_OFFSET
    )
    morphology = morphology or []
    morph_bytes = encode_morphology(morphology)
    morphology_offset = HEADER.size + len(dawg)
    exceptions_offset = morphology_offset + len(morph_bytes)
    block_offsets_offset = exceptions_offset + len(record_bytes)
    header = HEADER.pack(
        MAGIC, VERSION, 0, BLOCK_WORDS,
        len(vocabulary), edge_count, root_offset,
        len(exceptions), len(output_words), overflow_count, len(morphology),
        morphology_offset, exceptions_offset, block_offsets_offset,
    )
    return header + dawg + morph_bytes + record_bytes + block_offsets + word_data


def improve_exception_selection(
    selected: list[ExceptionEntry], candidates: list[ExceptionEntry],
    weights: dict[str, float], model_base_size: int, binary_budget: int,
    attempts: int = 512,
) -> list[ExceptionEntry]:
    """Replace low-value records when a higher-value record fits exactly."""
    selected_words = {entry.word for entry in selected}
    unselected = sorted(
        (entry for entry in candidates if entry.word not in selected_words),
        key=lambda entry: (-weights[entry.word], entry.word, entry.outline),
    )[:attempts]
    for candidate in unselected:
        victims = sorted(selected, key=lambda entry: (weights[entry.word], entry.word))[:32]
        for victim in victims:
            if weights[candidate.word] <= weights[victim.word]:
                break
            proposed = [entry for entry in selected if entry != victim] + [candidate]
            try:
                size = model_base_size + exception_storage_size(proposed)
                # pack_model will enforce hashes, but checking them here avoids
                # accepting a swap that cannot be serialized.
                fingerprints: dict[int, str] = {}
                for entry in proposed:
                    fingerprint = hash32(entry.outline.encode("ascii")) & EXCEPTION_HASH_MASK
                    previous = fingerprints.setdefault(fingerprint, entry.outline)
                    if previous != entry.outline:
                        raise ValueError("hash collision")
            except ValueError:
                continue
            if size <= binary_budget:
                selected = proposed
                break
    return selected


def choose_model(dictionary: dict[str, str], frequencies: list[tuple[str, float]],
                 vocabulary_size: int, beam: int,
                 binary_budget: int) -> tuple[list[str], list[ExceptionEntry], dict[str, float | int]]:
    ranked_vocabulary = [word for word, _ in frequencies[:vocabulary_size]]
    max_zipf = frequencies[0][1]
    weights = {word: 10 ** (zipf - max_zipf) for word, zipf in frequencies}
    total_weight = sum(weights.values())
    outlines_by_word: dict[str, list[str]] = defaultdict(list)
    for outline, translation in dictionary.items():
        word = translation.lower()
        if word in weights and WORD_RE.fullmatch(translation):
            outlines_by_word[word].append(outline)
    add_productive_outlines(outlines_by_word, list(weights))

    # Reclaim graph capacity from low-ranked tokens that have no conventional
    # outline, then spend part of it on the next rule-capable words. Keeping
    # more removals than additions accounts for the longer tail-word paths.
    removable = [
        word for word in reversed(ranked_vocabulary)
        if not outlines_by_word.get(word)
    ][:VOCABULARY_REBALANCE_REMOVALS]
    removed = set(removable)
    retained = [word for word in ranked_vocabulary if word not in removed]
    addition_pool = [
        word for word, _ in frequencies[vocabulary_size:]
        if outlines_by_word.get(word)
    ][:200]
    probe_words = set(retained + addition_pool)
    probe_prefixes = {
        word[:length]
        for word in probe_words
        for length in range(1, len(word) + 1)
    }
    additions = []
    for word in addition_pool:
        for outline in sorted(outlines_by_word[word],
                              key=lambda value: (value.count("/"), len(value), value)):
            generated = hand_rules.generate_outline(outline, beam, probe_prefixes)
            accepted = next((candidate for candidate in generated
                             if candidate in probe_words), None)
            if accepted == word:
                additions.append(word)
                break
        if len(additions) == VOCABULARY_REBALANCE_ADDITIONS:
            break
    vocabulary = retained + additions
    vocabulary_set = set(vocabulary)
    vocabulary_prefixes = {
        word[:length]
        for word in vocabulary
        for length in range(1, len(word) + 1)
    }
    generated_outlines: dict[tuple[str, bool], list[str]] = {}

    def generate_for_vocabulary(outline: str, prune_final: bool = True) -> list[str]:
        key = (outline, prune_final)
        if key not in generated_outlines:
            generated_outlines[key] = hand_rules.generate_outline(
                outline, beam, vocabulary_prefixes, prune_final=prune_final,
            )
        return generated_outlines[key]

    # Explicit starred-letter spelling is authoritative and does not require
    # vocabulary membership. Keep it separate from ordinary rule success so
    # spare model bytes can still preserve convenient dictionary outlines.
    fingerspelled = {
        word for word in weights
        if (word.isalpha() and len(word) <= 16)
        or (word.endswith("'s") and word[:-2].isalpha() and len(word[:-2]) <= 15)
    }
    successful: set[str] = set()
    preferred_outline: dict[str, str] = {}
    for word in vocabulary:
        for outline in sorted(outlines_by_word.get(word, ()), key=lambda value: (value.count("/"), len(value), value)):
            generated = generate_for_vocabulary(outline)
            accepted = next((candidate for candidate in generated if candidate in vocabulary_set), None)
            if accepted is None:
                final_candidates = generate_for_vocabulary(outline, prune_final=False)
                accepted = next((repair
                                 for candidate in final_candidates
                                 for repair in hand_rules.orthographic_repairs(candidate)
                                 if repair in vocabulary_set), None)
            if accepted == word:
                successful.add(word)
                break
            preferred_outline.setdefault(word, outline)
    for word in weights:
        if word not in preferred_outline and outlines_by_word.get(word):
            preferred_outline[word] = min(outlines_by_word[word], key=lambda value: (value.count("/"), len(value), value))

    dawg_info = build_dawg(vocabulary)

    # License grouped spelling transformations by an exact, delta-coded identity
    # of a primary root.  A recipe never licenses a spelling by itself.
    root_ids = primary_root_ids(vocabulary, dawg_info)
    morph_candidates: list[tuple[float, str, tuple[str, str], int]] = []
    for word in weights:
        if word in successful or word not in preferred_outline:
            continue
        if not any(
            word in generate_for_vocabulary(outline, prune_final=False)
            for outline in sorted(
                outlines_by_word.get(word, ()),
                key=lambda value: (value.count("/"), len(value), value),
            )
        ):
            continue
        recipes = []
        for root, _ in derivations_for_word(word):
            if root not in root_ids:
                continue
            prefix = common_prefix_length(root, word)
            recipes.append((root[prefix:], word[prefix:], root_ids[root]))
        if recipes:
            root_tail, output_tail, root_id = min(
                recipes, key=lambda item: (len(item[0]) + len(item[1]), item)
            )
            # The denominator approximates a delta varint; group overhead is
            # charged when the first member is selected below.
            morph_candidates.append((weights[word], word,
                                     (root_tail, output_tail), root_id))

    candidate_groups: dict[
        tuple[str, str], list[tuple[int, str, float]]
    ] = defaultdict(list)
    for weight, word, recipe, root_id in morph_candidates:
        candidate_groups[recipe].append((root_id, word, weight))
    ranked_groups = []
    for recipe, values in candidate_groups.items():
        group = MorphologyGroup(
            recipe[0], recipe[1],
            tuple(sorted({value[0] for value in values})),
        )
        size = len(encode_morphology([group]))
        ranked_groups.append(
            (sum(value[2] for value in values) / size, recipe, values, size)
        )

    morph_members: dict[tuple[str, str], list[tuple[int, str]]] = {}
    morph_words: set[str] = set()
    morphology_size = 0
    # Whole recipe groups compete by covered frequency per exact serialized
    # byte, so common derivational families amortize their shared tails.
    for _, recipe, values, group_size in sorted(
            ranked_groups, key=lambda item: (-item[0], item[1])):
        if morphology_size + group_size <= 3824:
            morph_members[recipe] = [
                (root_id, word) for root_id, word, _ in values
            ]
            morph_words.update(word for _, word, _ in values)
            morphology_size += group_size
    morphology = [MorphologyGroup(key[0], key[1],
                  tuple(sorted({entry[0] for entry in values})))
                  for key, values in morph_members.items()]

    candidates = [word for word in weights
                  if word not in successful and word not in morph_words
                  and word in preferred_outline]
    candidates.sort(key=lambda word: weights[word] / (6 + max(1, len(word) // 2)), reverse=True)
    selected: list[ExceptionEntry] = []
    selected_outlines: set[str] = set()
    selected_fingerprints: dict[int, str] = {}
    model_base_size = HEADER.size + len(dawg_info[0]) + len(encode_morphology(morphology))
    current_size = model_base_size
    for word in candidates:
        if len(selected) >= (1 << EXCEPTION_ID_BITS) - 1:
            break
        # Keep considering later candidates even when the model appears full:
        # inserting a lexical neighbor can shorten another front-coded suffix,
        # so the marginal size is not strictly positive.
        outline = preferred_outline[word]
        if outline in selected_outlines:
            continue
        proposed = selected + [ExceptionEntry(outline, word)]
        fingerprint = hash32(outline.encode("ascii")) & EXCEPTION_HASH_MASK
        collision = selected_fingerprints.get(fingerprint)
        if collision is not None and collision != outline:
            continue
        size = model_base_size + exception_storage_size(proposed)
        if size <= binary_budget:
            selected = proposed
            selected_outlines.add(outline)
            selected_fingerprints[fingerprint] = outline
            current_size = size

    used_outlines = {entry.outline for entry in selected}
    selected_words = {entry.word for entry in selected}
    all_exception_candidates = [
        ExceptionEntry(preferred_outline[word], word)
        for word in candidates
        if word in selected_words
        or preferred_outline[word] not in used_outlines
    ]
    selected = improve_exception_selection(
        selected, all_exception_candidates, weights, model_base_size, binary_budget,
    )
    model = pack_model(vocabulary, selected, dawg_info, morphology)
    conventional = successful | morph_words | {entry.word for entry in selected}
    covered = fingerspelled | conventional
    report = {
        "model_bytes": len(model),
        "rule_bytes": RULE_BYTES,
        "total_data_bytes": len(model) + RULE_BYTES,
        "vocabulary_words": len(vocabulary),
        "vocabulary_rebalance_removals": len(removable),
        "vocabulary_rebalance_additions": len(additions),
        "vocabulary_dawg_bytes": len(dawg_info[0]),
        "rule_resolved_words": len(successful),
        "fingerspelled_words": len(fingerspelled),
        "exception_outlines": len(selected),
        "morphology_groups": len(morphology),
        "morphology_words": len(morph_words),
        "morphology_bytes": len(encode_morphology(morphology)),
        "coverage_of_frequency_list": sum(weights.get(word, 0) for word in covered) / total_weight,
        "conventional_coverage_of_frequency_list": (
            sum(weights.get(word, 0) for word in conventional) / total_weight
        ),
        "probabilistic_membership": False,
    }
    report["morphology"] = morphology
    report["conventional_words"] = conventional
    return vocabulary, selected, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("frequencies", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--words", type=int, default=20000)
    parser.add_argument("--vocabulary", type=int, default=8250)
    parser.add_argument("--beam", type=int, default=64)
    parser.add_argument("--total-data-budget", type=int, default=DEFAULT_TOTAL_DATA_BUDGET)
    args = parser.parse_args()

    dictionary = json.loads(args.dictionary.read_text())
    frequencies = load_frequencies(args.frequencies, args.words)
    binary_budget = args.total_data_budget - RULE_BYTES
    vocabulary, exceptions, report = choose_model(
        dictionary, frequencies, args.vocabulary, args.beam, binary_budget,
    )
    morphology = report.pop("morphology")
    report.pop("conventional_words")
    model = pack_model(vocabulary, exceptions, morphology=morphology)
    args.output.write_bytes(model)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
