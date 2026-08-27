#!/usr/bin/env python3
"""Generate the exact flash-resident Lapwing vocabulary and exception model."""

from __future__ import annotations

import argparse
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
VERSION = 4
HEADER = struct.Struct("<4sBBHIIIIIII")
EXCEPTION_HASH_BITS = 29
EXCEPTION_ID_BITS = 11
EXCEPTION_HASH_MASK = (1 << EXCEPTION_HASH_BITS) - 1
BLOCK_WORDS = 384
VOCABULARY_REBALANCE_REMOVALS = 100
VOCABULARY_REBALANCE_ADDITIONS = 40
RULE_BYTES = 4181
DEFAULT_TOTAL_DATA_BUDGET = 40 * 1024
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
ALPHABET = "abcdefghijklmnopqrstuvwxyz'-"
LEAF_OFFSET = 0x1FFF
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
    offsets: list[int] = [LEAF_OFFSET] * len(states)
    edge_count = 0
    for state_id, state in enumerate(states):
        if state.edges:
            offsets[state_id] = edge_count
            edge_count += len(state.edges)
    target_ids = {target_id for state in states for _, target_id in state.edges}
    if any(states[target_id].edges and offsets[target_id] >= LEAF_OFFSET
           for target_id in target_ids):
        raise ValueError("vocabulary DAWG exceeds 13-bit target offsets")

    values = []
    for state in states:
        for index, (character, target_id) in enumerate(state.edges):
            target = states[target_id]
            value = ALPHABET.index(character)
            value |= offsets[target_id] << 5
            value |= int(target.terminal) << 18
            value |= int(index + 1 == len(state.edges)) << 19
            values.append(value)
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
    return bytes(encoded), offsets[root_id], edge_count


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
            size += varint_size(prefix) + varint_size(suffix) + packed_letters_size(suffix)
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
                encoded += encode_varint(prefix) + encode_varint(len(suffix)) + pack_letters(suffix)
            previous = word
    return bytes(offsets), bytes(encoded)


@dataclass(frozen=True)
class ExceptionEntry:
    outline: str
    word: str


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


def add_productive_outlines(outlines_by_word: dict[str, list[str]],
                            words: list[str]) -> None:
    """Add standalone, fingerspelling, and recursively productive outlines."""
    for word in words:
        if word in outlines_by_word:
            continue
        if word in STANDALONE_OUTLINES:
            outlines_by_word.setdefault(word, []).append(STANDALONE_OUTLINES[word])
            continue
        for outline, values in hand_rules.PREFIXES.items():
            if word in values:
                outlines_by_word.setdefault(word, []).append(outline)

    # Multiple rounds permit chains such as success -> successful -> successfully.
    for _ in range(4):
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

    # Compose known roots for closed compounds such as health + care and
    # out + standing. Keep only combinations the firmware can retain.
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
                        if candidate.count("/") < 8:
                            outlines_by_word.setdefault(word, []).append(candidate)
                            changed = True
        if not changed:
            break



def pack_model(vocabulary: list[str], exceptions: list[ExceptionEntry],
               dawg_info: tuple[bytes, int, int] | None = None) -> bytes:
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
    exceptions_offset = HEADER.size + len(dawg)
    block_offsets_offset = exceptions_offset + len(record_bytes)
    header = HEADER.pack(
        MAGIC, VERSION, 0, BLOCK_WORDS,
        len(vocabulary), edge_count, root_offset,
        len(exceptions), len(output_words), exceptions_offset, block_offsets_offset,
    )
    return header + dawg + record_bytes + block_offsets + word_data


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
            generated = hand_rules.generate_outline(outline, beam, vocabulary_prefixes)
            accepted = next((candidate for candidate in generated if candidate in vocabulary_set), None)
            if accepted is None:
                final_candidates = hand_rules.generate_outline(
                    outline, beam, vocabulary_prefixes, prune_final=False,
                )
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
    candidates = [word for word in weights
                  if word not in successful and word in preferred_outline]
    candidates.sort(key=lambda word: weights[word] / (6 + max(1, len(word) // 2)), reverse=True)
    selected: list[ExceptionEntry] = []
    selected_outlines: set[str] = set()
    selected_fingerprints: dict[int, str] = {}
    model_base_size = HEADER.size + len(dawg_info[0])
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
    model = pack_model(vocabulary, selected, dawg_info)
    conventional = successful | {entry.word for entry in selected}
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
        "coverage_of_frequency_list": sum(weights.get(word, 0) for word in covered) / total_weight,
        "conventional_coverage_of_frequency_list": (
            sum(weights.get(word, 0) for word in conventional) / total_weight
        ),
        "probabilistic_membership": False,
    }
    return vocabulary, selected, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("frequencies", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--words", type=int, default=20000)
    parser.add_argument("--vocabulary", type=int, default=6275)
    parser.add_argument("--beam", type=int, default=24)
    parser.add_argument("--total-data-budget", type=int, default=DEFAULT_TOTAL_DATA_BUDGET)
    args = parser.parse_args()

    dictionary = json.loads(args.dictionary.read_text())
    frequencies = load_frequencies(args.frequencies, args.words)
    binary_budget = args.total_data_budget - RULE_BYTES
    vocabulary, exceptions, report = choose_model(
        dictionary, frequencies, args.vocabulary, args.beam, binary_budget,
    )
    model = pack_model(vocabulary, exceptions)
    args.output.write_bytes(model)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
