#!/usr/bin/env python3
"""Generate the exact flash-resident Lapwing vocabulary and exception model."""

from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import hand_rules
from analyze_storage import common_prefix_length, encode_varint
from common_text_budget import load_frequencies

MAGIC = b"LWMD"
VERSION = 10
HEADER = struct.Struct("<4sBBHIIIIIIIIII")
EXCEPTION_HASH_BITS = 29
EXCEPTION_ID_BITS = 11
EXCEPTION_HASH_MASK = (1 << EXCEPTION_HASH_BITS) - 1
BLOCK_WORDS = 384
EXCEPTION_CHECKPOINT_STRIDE = 64
VOCABULARY_REBALANCE_REMOVALS = 100
VOCABULARY_REBALANCE_ADDITIONS = 40
RULE_BYTES = 4228
DEFAULT_TOTAL_DATA_BUDGET = 40 * 1024 + 10_000
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
ALPHABET = "abcdefghijklmnopqrstuvwxyz'-"
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


LOUDS_CHECKPOINT_STRIDE = 64


def pack_bit_values(values: list[int], width: int) -> bytes:
    encoded = bytearray((len(values) * width + 7) // 8)
    for index, value in enumerate(values):
        if value < 0 or value >= 1 << width:
            raise ValueError("packed value exceeds field width")
        bit = index * width
        remaining = width
        while remaining:
            byte = bit // 8
            offset = bit % 8
            chunk = min(remaining, 8 - offset)
            encoded[byte] |= (value & ((1 << chunk) - 1)) << offset
            value >>= chunk
            bit += chunk
            remaining -= chunk
    return bytes(encoded)


def read_bit_value(data: bytes, index: int, width: int) -> int:
    bit = index * width
    value = int.from_bytes(data[bit // 8:bit // 8 + 2], "little")
    return value >> (bit % 8) & ((1 << width) - 1)


def build_dawg(words: list[str]) -> tuple[bytes, int, int]:
    """Build the exact breadth-first LOUDS vocabulary trie."""
    terminal = ""
    root: dict[str, dict] = {}
    for word in words:
        node = root
        for character in word:
            if character not in ALPHABET:
                raise ValueError(f"unsupported vocabulary character: {character!r}")
            node = node.setdefault(character, {})
        node[terminal] = {}

    nodes = [root]
    labels: list[int] = []
    topology: list[int] = []
    terminals: list[int] = []
    for node in nodes:
        children = sorted((character, child)
                          for character, child in node.items() if character)
        terminals.append(int(terminal in node))
        topology.extend([1] * len(children))
        topology.append(0)
        for character, child in children:
            labels.append(ALPHABET.index(character))
            nodes.append(child)
    if len(nodes) > 0xffff:
        raise ValueError("vocabulary LOUDS trie exceeds 16-bit node indexes")

    zero_positions = [index for index, value in enumerate(topology) if not value]
    checkpoint_positions = zero_positions[::LOUDS_CHECKPOINT_STRIDE]
    if checkpoint_positions and checkpoint_positions[-1] > 0xffffff:
        raise ValueError("vocabulary LOUDS checkpoints exceed 24-bit positions")
    checkpoints = b"".join(
        position.to_bytes(3, "little") for position in checkpoint_positions
    )
    encoded = (
        pack_bit_values(labels, 5)
        + pack_bit_values(topology, 1)
        + pack_bit_values(terminals, 1)
        + checkpoints
    )
    return encoded, 0, len(labels)


def louds_sections(data: bytes, edges: int) -> tuple[bytes, bytes, bytes, bytes]:
    nodes = edges + 1
    label_bytes = (edges * 5 + 7) // 8
    topology_bytes = (2 * nodes - 1 + 7) // 8
    terminal_bytes = (nodes + 7) // 8
    checkpoint_bytes = 3 * ((nodes + LOUDS_CHECKPOINT_STRIDE - 1)
                            // LOUDS_CHECKPOINT_STRIDE)
    expected = label_bytes + topology_bytes + terminal_bytes + checkpoint_bytes
    if len(data) != expected:
        raise ValueError("invalid LOUDS vocabulary size")
    topology_start = label_bytes
    terminal_start = topology_start + topology_bytes
    checkpoint_start = terminal_start + terminal_bytes
    return (data[:topology_start], data[topology_start:terminal_start],
            data[terminal_start:checkpoint_start], data[checkpoint_start:])


def louds_select_zero(topology: bytes, checkpoints: bytes, node: int) -> int:
    block, remaining = divmod(node, LOUDS_CHECKPOINT_STRIDE)
    position = int.from_bytes(checkpoints[block * 3:block * 3 + 3], "little")
    while remaining:
        position += 1
        if not read_bit_value(topology, position, 1):
            remaining -= 1
    return position


def louds_child_interval(topology: bytes, checkpoints: bytes,
                         node: int) -> tuple[int, int]:
    end_zero = louds_select_zero(topology, checkpoints, node)
    start = 0 if node == 0 else louds_select_zero(topology, checkpoints, node - 1) + 1
    first = start - node
    return first, first + end_zero - start


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


def full_word_size(word: str) -> int:
    return varint_size(len(word)) + packed_letters_size(len(word))


def delta_word_size(previous: str, word: str) -> int:
    prefix = common_prefix_length(previous, word)
    suffix = len(word) - prefix
    return word_delta_size(prefix, suffix) + packed_letters_size(suffix)


def exception_storage_size(exceptions: list[ExceptionEntry]) -> int:
    words = sorted(entry.word for entry in exceptions)
    size = len(exceptions) * 5 + 2 * ((len(words) + BLOCK_WORDS - 1) // BLOCK_WORDS)
    for index, word in enumerate(words):
        size += (full_word_size(word) if index % BLOCK_WORDS == 0
                 else delta_word_size(words[index - 1], word))
    return size


def exception_storage_size_after_insert(
    words: list[str], current_size: int, word: str,
) -> int:
    """Return exact storage after inserting one word into a sorted pool."""
    position = bisect.bisect_left(words, word)
    old_count = len(words)
    new_count = old_count + 1
    size = current_size + 5
    size += 2 * (
        (new_count + BLOCK_WORDS - 1) // BLOCK_WORDS
        - (old_count + BLOCK_WORDS - 1) // BLOCK_WORDS
    )

    if position % BLOCK_WORDS == 0:
        size += full_word_size(word)
    else:
        size += delta_word_size(words[position - 1], word)

    affected = {position}
    first_boundary = ((position + BLOCK_WORDS - 1) // BLOCK_WORDS) * BLOCK_WORDS
    for boundary in range(first_boundary, old_count + 1, BLOCK_WORDS):
        affected.add(boundary)
        if boundary:
            affected.add(boundary - 1)
    for index in affected:
        if not position <= index < old_count:
            continue
        old_size = (full_word_size(words[index]) if index % BLOCK_WORDS == 0
                    else delta_word_size(words[index - 1], words[index]))
        new_index = index + 1
        if new_index % BLOCK_WORDS == 0:
            new_size = full_word_size(words[index])
        else:
            previous = word if index == position else words[index - 1]
            new_size = delta_word_size(previous, words[index])
        size += new_size - old_size
    return size


def exception_storage_size_after_remove(
    words: list[str], current_size: int, position: int,
) -> tuple[int, list[str]]:
    """Return exact storage and sorted words after removing one position."""
    reduced = words.copy()
    word = reduced.pop(position)
    insertion_cost = exception_storage_size_after_insert(reduced, 0, word)
    return current_size - insertion_cost, reduced


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
    """Return exact (terminal trie node, length) primary-word identities."""
    trie, root, edges = dawg_info
    labels, topology, terminals, checkpoints = louds_sections(trie, edges)
    identities: dict[str, int] = {}
    for word in vocabulary:
        node = root
        for character in word:
            wanted = ALPHABET.index(character)
            first, end = louds_child_interval(topology, checkpoints, node)
            child = next((edge + 1 for edge in range(first, end)
                          if read_bit_value(labels, edge, 5) == wanted), None)
            if child is None:
                raise AssertionError(word)
            node = child
        if not read_bit_value(terminals, node, 1):
            raise AssertionError(word)
        if len(word) <= 31:
            identities[word] = (node << 5) | len(word)
    return identities

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



def node_exception_parameters(count: int, nodes: int) -> tuple[int, int, int]:
    """Return Elias-Fano low bits, quotient buckets, and node-reference bits."""
    if count <= 0 or nodes <= 1:
        return 0, 0, 0
    low_bits = ((1 << EXCEPTION_HASH_BITS) // count).bit_length() - 1
    buckets = 1 << (EXCEPTION_HASH_BITS - low_bits)
    node_bits = (nodes - 1).bit_length()
    return low_bits, buckets, node_bits


def node_exception_storage_size(count: int, nodes: int) -> int:
    if not count:
        return 0
    low_bits, buckets, node_bits = node_exception_parameters(count, nodes)
    return (
        (count * low_bits + 7) // 8
        + (count + buckets + 7) // 8
        + 2 * ((buckets + EXCEPTION_CHECKPOINT_STRIDE - 1)
               // EXCEPTION_CHECKPOINT_STRIDE)
        + (count * node_bits + 7) // 8
    )


def encode_node_exceptions(
    vocabulary: list[str], exceptions: list[ExceptionEntry],
    dawg_info: tuple[bytes, int, int],
) -> tuple[bytes, int, int]:
    if not exceptions:
        return b"", 0, 0
    identities = primary_root_ids(vocabulary, dawg_info)
    records = []
    for entry in exceptions:
        identity = identities.get(entry.word)
        if identity is None:
            raise ValueError(f"exception output is not a primary trie word: {entry.word}")
        records.append((hash32(entry.outline.encode("ascii")) & EXCEPTION_HASH_MASK,
                        identity >> 5, entry.outline))
    records.sort()
    for left, right in zip(records, records[1:]):
        if left[0] == right[0]:
            raise ValueError(f"exception hash collision: {left[2]} and {right[2]}")

    count = len(records)
    if count >= 0xffff:
        raise ValueError("exception count exceeds format limit")
    nodes = dawg_info[2] + 1
    low_bits, buckets, node_bits = node_exception_parameters(count, nodes)
    low_mask = (1 << low_bits) - 1
    lows = [fingerprint & low_mask for fingerprint, _, _ in records]
    highs = [fingerprint >> low_bits for fingerprint, _, _ in records]
    high_stream: list[int] = []
    zero_positions: list[int] = []
    index = 0
    for bucket in range(buckets):
        while index < count and highs[index] == bucket:
            high_stream.append(1)
            index += 1
        zero_positions.append(len(high_stream))
        high_stream.append(0)
    if index != count:
        raise AssertionError("exception quotient outside Elias-Fano range")
    checkpoints = zero_positions[::EXCEPTION_CHECKPOINT_STRIDE]
    if checkpoints[-1] > 0xffff:
        raise ValueError("exception Elias-Fano checkpoints exceed 16-bit positions")
    encoded = (
        pack_bit_values(lows, low_bits)
        + pack_bit_values(high_stream, 1)
        + b"".join(struct.pack("<H", position) for position in checkpoints)
        + pack_bit_values([node for _, node, _ in records], node_bits)
    )
    if len(encoded) != node_exception_storage_size(count, nodes):
        raise AssertionError("incorrect exception Elias-Fano size")
    return encoded, low_bits, node_bits


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
    louds_sections(dawg, edge_count)
    morphology = morphology or []
    morph_bytes = encode_morphology(morphology)
    exception_bytes, low_bits, node_bits = encode_node_exceptions(
        vocabulary, exceptions, (dawg, root_offset, edge_count),
    )
    morphology_offset = HEADER.size + len(dawg)
    exceptions_offset = morphology_offset + len(morph_bytes)
    total_size = exceptions_offset + len(exception_bytes)
    header = HEADER.pack(
        MAGIC, VERSION, 0, EXCEPTION_CHECKPOINT_STRIDE,
        len(vocabulary), edge_count, root_offset,
        len(exceptions), low_bits, node_bits, len(morphology),
        morphology_offset, exceptions_offset, total_size,
    )
    return header + dawg + morph_bytes + exception_bytes


def improve_exception_selection(
    selected: list[ExceptionEntry], candidates: list[ExceptionEntry],
    weights: dict[str, float], model_base_size: int, binary_budget: int,
    attempts: int = 512,
) -> list[ExceptionEntry]:
    """Replace low-value records when a higher-value record fits exactly."""
    selected_words = {entry.word for entry in selected}
    sorted_words = sorted(selected_words)
    storage_size = exception_storage_size(selected)
    fingerprints = {
        hash32(entry.outline.encode("ascii")) & EXCEPTION_HASH_MASK: entry.outline
        for entry in selected
    }
    unselected = sorted(
        (entry for entry in candidates if entry.word not in selected_words),
        key=lambda entry: (-weights[entry.word], entry.word, entry.outline),
    )[:attempts]
    for candidate in unselected:
        victims = sorted(selected, key=lambda entry: (weights[entry.word], entry.word))[:32]
        candidate_fingerprint = hash32(candidate.outline.encode("ascii")) & EXCEPTION_HASH_MASK
        for victim in victims:
            if weights[candidate.word] <= weights[victim.word]:
                break
            collision = fingerprints.get(candidate_fingerprint)
            if collision not in (None, candidate.outline, victim.outline):
                continue
            victim_position = bisect.bisect_left(sorted_words, victim.word)
            reduced_size, reduced_words = exception_storage_size_after_remove(
                sorted_words, storage_size, victim_position,
            )
            proposed_size = exception_storage_size_after_insert(
                reduced_words, reduced_size, candidate.word,
            )
            if model_base_size + proposed_size <= binary_budget:
                selected[selected.index(victim)] = candidate
                bisect.insort(reduced_words, candidate.word)
                sorted_words = reduced_words
                storage_size = proposed_size
                victim_fingerprint = (
                    hash32(victim.outline.encode("ascii")) & EXCEPTION_HASH_MASK
                )
                if fingerprints.get(victim_fingerprint) == victim.outline:
                    del fingerprints[victim_fingerprint]
                fingerprints[candidate_fingerprint] = candidate.outline
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
            accepted = next((candidate for candidate in generated
                             if candidate in vocabulary_set), None)
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
                  if word in vocabulary_set and word not in successful
                  and word not in morph_words and word in preferred_outline]
    candidates.sort(key=lambda word: (-weights[word], word, preferred_outline[word]))
    selected: list[ExceptionEntry] = []
    selected_outlines: set[str] = set()
    fingerprint_outlines: dict[int, str | None] = {}
    for outline in (value for values in outlines_by_word.values() for value in values):
        fingerprint = hash32(outline.encode("ascii")) & EXCEPTION_HASH_MASK
        previous = fingerprint_outlines.get(fingerprint)
        if previous is None and fingerprint not in fingerprint_outlines:
            fingerprint_outlines[fingerprint] = outline
        elif previous != outline:
            fingerprint_outlines[fingerprint] = None
    model_base_size = HEADER.size + len(dawg_info[0]) + len(encode_morphology(morphology))
    nodes = dawg_info[2] + 1
    collision_exclusions = 0
    for word in candidates:
        outline = preferred_outline[word]
        if outline in selected_outlines:
            continue
        fingerprint = hash32(outline.encode("ascii")) & EXCEPTION_HASH_MASK
        if fingerprint_outlines.get(fingerprint) != outline:
            collision_exclusions += 1
            continue
        proposed_count = len(selected) + 1
        if model_base_size + node_exception_storage_size(proposed_count, nodes) > binary_budget:
            break
        selected.append(ExceptionEntry(outline, word))
        selected_outlines.add(outline)
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
        "vocabulary_trie_bytes": len(dawg_info[0]),
        "rule_resolved_words": len(successful),
        "fingerspelled_words": len(fingerspelled),
        "exception_outlines": len(selected),
        "exception_bytes": node_exception_storage_size(len(selected), dawg_info[2] + 1),
        "exception_collision_exclusions": collision_exclusions,
        "morphology_groups": len(morphology),
        "morphology_words": len(morph_words),
        "morphology_bytes": len(encode_morphology(morphology)),
        "coverage_of_frequency_list": sum(weights.get(word, 0) for word in covered) / total_weight,
        "conventional_coverage_of_frequency_list": (
            sum(weights.get(word, 0) for word in conventional) / total_weight
        ),
        "probabilistic_membership": False,
        "probabilistic_exception_lookup": True,
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
    parser.add_argument("--vocabulary", type=int, default=14200)
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
