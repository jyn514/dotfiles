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
VERSION = 2
HEADER = struct.Struct("<4sBBHIIIIIII")
EXCEPTION = struct.Struct("<IH")
BLOCK_WORDS = 32
RULE_BYTES = 4413
DEFAULT_TOTAL_DATA_BUDGET = 40 * 1024
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
ALPHABET = "abcdefghijklmnopqrstuvwxyz'-"
LEAF_OFFSET = 0x1FFF


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


def build_dawg(words: list[str]) -> tuple[bytes, int]:
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
    if edge_count >= LEAF_OFFSET:
        raise ValueError("vocabulary DAWG exceeds 13-bit edge offsets")

    encoded = bytearray()
    for state in states:
        for index, (character, target_id) in enumerate(state.edges):
            target = states[target_id]
            value = ALPHABET.index(character)
            value |= offsets[target_id] << 5
            value |= int(target.terminal) << 18
            value |= int(index + 1 == len(state.edges)) << 19
            encoded += value.to_bytes(3, "little")
    return bytes(encoded), offsets[root_id]


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
                encoded += encode_varint(len(raw)) + raw
            else:
                prefix = common_prefix_length(previous, word)
                suffix = raw[prefix:]
                encoded += encode_varint(prefix) + encode_varint(len(suffix)) + suffix
            previous = word
    return bytes(offsets), bytes(encoded)


@dataclass(frozen=True)
class ExceptionEntry:
    outline: str
    word: str


def pack_model(vocabulary: list[str], exceptions: list[ExceptionEntry]) -> bytes:
    dawg, root_offset = build_dawg(vocabulary)
    outputs_by_outline: dict[str, str] = {}
    for entry in exceptions:
        previous = outputs_by_outline.setdefault(entry.outline, entry.word)
        if previous != entry.word:
            raise ValueError(
                f"exception outline has multiple outputs: {entry.outline}: {previous}, {entry.word}"
            )
    output_words = sorted({entry.word for entry in exceptions})
    word_ids = {word: index for index, word in enumerate(output_words)}
    records = sorted((hash32(entry.outline.encode("ascii")), word_ids[entry.word], entry.outline)
                     for entry in exceptions)
    for left, right in zip(records, records[1:]):
        if left[0] == right[0] and left[2] != right[2]:
            raise ValueError(f"exception hash collision: {left[2]} and {right[2]}")
    record_bytes = b"".join(EXCEPTION.pack(fingerprint, word_id)
                            for fingerprint, word_id, _ in records)
    block_offsets, word_data = encode_word_blocks(output_words)
    exceptions_offset = HEADER.size + len(dawg)
    block_offsets_offset = exceptions_offset + len(record_bytes)
    header = HEADER.pack(
        MAGIC, VERSION, 0, BLOCK_WORDS,
        len(vocabulary), len(dawg) // 3, root_offset,
        len(exceptions), len(output_words), exceptions_offset, block_offsets_offset,
    )
    return header + dawg + record_bytes + block_offsets + word_data


def choose_model(dictionary: dict[str, str], frequencies: list[tuple[str, float]],
                 vocabulary_size: int, beam: int,
                 binary_budget: int) -> tuple[list[str], list[ExceptionEntry], dict[str, float | int]]:
    vocabulary = [word for word, _ in frequencies[:vocabulary_size]]
    vocabulary_set = set(vocabulary)
    max_zipf = frequencies[0][1]
    weights = {word: 10 ** (zipf - max_zipf) for word, zipf in frequencies}
    total_weight = sum(weights.values())
    outlines_by_word: dict[str, list[str]] = defaultdict(list)
    for outline, translation in dictionary.items():
        word = translation.lower()
        if word in weights and WORD_RE.fullmatch(translation):
            outlines_by_word[word].append(outline)

    successful: set[str] = {word for word in vocabulary if len(word) == 1}
    preferred_outline: dict[str, str] = {}
    for word in vocabulary:
        for outline in sorted(outlines_by_word.get(word, ()), key=lambda value: (value.count("/"), len(value), value)):
            generated = hand_rules.generate_outline(outline, beam)
            accepted = next((candidate for candidate in generated if candidate in vocabulary_set), None)
            if accepted == word:
                successful.add(word)
                break
            preferred_outline.setdefault(word, outline)
    for word in weights:
        if word not in preferred_outline and outlines_by_word.get(word):
            preferred_outline[word] = min(outlines_by_word[word], key=lambda value: (value.count("/"), len(value), value))

    candidates = [word for word in weights
                  if word not in successful and word in preferred_outline]
    candidates.sort(key=lambda word: weights[word] / (6 + max(1, len(word) // 2)), reverse=True)
    selected: list[ExceptionEntry] = []
    selected_outlines: set[str] = set()
    for word in candidates:
        outline = preferred_outline[word]
        if outline in selected_outlines:
            continue
        proposed = selected + [ExceptionEntry(outline, word)]
        try:
            size = len(pack_model(vocabulary, proposed))
        except ValueError:
            continue
        if size <= binary_budget:
            selected = proposed
            selected_outlines.add(outline)

    model = pack_model(vocabulary, selected)
    covered = successful | {entry.word for entry in selected}
    report = {
        "model_bytes": len(model),
        "rule_bytes": RULE_BYTES,
        "total_data_bytes": len(model) + RULE_BYTES,
        "vocabulary_words": len(vocabulary),
        "vocabulary_dawg_bytes": len(build_dawg(vocabulary)[0]),
        "rule_resolved_words": len(successful),
        "exception_outlines": len(selected),
        "coverage_of_frequency_list": sum(weights.get(word, 0) for word in covered) / total_weight,
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
    parser.add_argument("--vocabulary", type=int, default=5000)
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
