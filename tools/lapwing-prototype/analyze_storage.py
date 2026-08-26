#!/usr/bin/env python3
"""Measure compact representations of a Lapwing word vocabulary."""

from __future__ import annotations

import argparse
import bz2
import json
import lzma
import re
import zlib
from collections.abc import Iterable
from pathlib import Path

PLAIN_WORD = re.compile(r"[A-Za-z]+")


def load_words(path: Path) -> list[str]:
    dictionary = json.loads(path.read_text())
    return sorted({translation.lower() for translation in dictionary.values()
                   if PLAIN_WORD.fullmatch(translation)})


def encode_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def front_code(words: Iterable[str], block_size: int) -> bytes:
    result = bytearray()
    previous = ""
    for index, word in enumerate(words):
        encoded = word.encode("ascii")
        if index % block_size == 0:
            result += encode_varint(len(encoded))
            result += encoded
        else:
            prefix = common_prefix_length(previous, word)
            suffix = encoded[prefix:]
            result += encode_varint(prefix)
            result += encode_varint(len(suffix))
            result += suffix
        previous = word
    return bytes(result)


def bloom_bytes(word_count: int, bits_per_word: int) -> int:
    return (word_count * bits_per_word + 7) // 8


def estimate_trie(words: Iterable[str]) -> tuple[int, int, int]:
    """Return node count, edge count, and a compact serialization estimate.

    The estimate uses one terminal bit per node and three bytes per edge:
    one 5-bit alphabet label plus a 19-bit child index/delta. Real code may
    require wider indices or restart tables.
    """
    root: dict[str, dict] = {}
    nodes = 1
    edges = 0
    terminals = 0
    terminal_marker = ""
    for word in words:
        node = root
        for character in word:
            if character not in node:
                node[character] = {}
                nodes += 1
                edges += 1
            node = node[character]
        if terminal_marker not in node:
            node[terminal_marker] = {}
            terminals += 1
    size = (nodes + 7) // 8 + edges * 3
    return nodes, edges, size


def print_size(label: str, size: int, count: int) -> None:
    print(f"{label:28} {size:9,d} B  {size / 1024:7.1f} KiB  "
          f"{size * 8 / count:6.2f} bits/word")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    args = parser.parse_args()

    words = load_words(args.dictionary)
    raw = "\n".join(words).encode("ascii") + b"\n"
    print(f"unique plain words: {len(words):,}")
    print_size("newline words", len(raw), len(words))
    print_size("zlib level 9", len(zlib.compress(raw, 9)), len(words))
    print_size("bzip2 level 9", len(bz2.compress(raw, 9)), len(words))
    print_size("xz preset 9", len(lzma.compress(raw, preset=9)), len(words))

    for block_size in (4, 8, 16, 32):
        data = front_code(words, block_size)
        restart_count = (len(words) + block_size - 1) // block_size
        # A 24-bit restart offset is enough for these data sizes.
        size = len(data) + restart_count * 3
        print_size(f"front coded, block {block_size}", size, len(words))

    nodes, edges, trie_size = estimate_trie(words)
    print_size("compact trie estimate", trie_size, len(words))
    print(f"  trie nodes={nodes:,}, edges={edges:,}")

    for bits in (6, 8, 10, 12):
        print_size(f"Bloom membership, {bits} b/key",
                   bloom_bytes(len(words), bits), len(words))

    # One byte per word is a useful lower-complexity ranking baseline.
    print_size("8-bit rank payload", len(words), len(words))


if __name__ == "__main__":
    main()
