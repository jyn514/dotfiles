#!/usr/bin/env python3
"""Estimate frequency-weighted coverage under an embedded data budget."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import hand_rules
from analyze_storage import front_code

EXCEPTION_RECORD_BYTES = 6
EXCEPTION_BLOCK_WORDS = 32


def load_frequencies(path: Path, limit: int) -> list[tuple[str, float]]:
    result = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        word, zipf_text = line.rsplit("\t", 1)
        word = word.lower()
        if re.fullmatch(r"[a-z]+(?:[-'][a-z]+)*", word):
            result.append((word, float(zipf_text)))
            if len(result) == limit:
                break
    return result


def exception_output_size(words: list[str]) -> int:
    """Size a lexically front-coded, randomly addressable output-word pool."""
    if not words:
        return 0
    encoded = front_code(sorted(words), EXCEPTION_BLOCK_WORDS)
    block_count = (len(words) + EXCEPTION_BLOCK_WORDS - 1) // EXCEPTION_BLOCK_WORDS
    return len(encoded) + block_count * 2


def exception_storage_size(words: list[str]) -> int:
    # Each immutable-MPHF record budgets MPHF overhead, a 24-bit fingerprint,
    # and a 16-bit ID into the front-coded output pool.
    return EXCEPTION_RECORD_BYTES * len(words) + exception_output_size(words)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("frequencies", type=Path,
                        help="TSV: word, tab, Zipf frequency; descending")
    parser.add_argument("--words", type=int, default=20000)
    parser.add_argument("--budget", type=int, default=40 * 1024)
    parser.add_argument("--beam", type=int, default=5000)
    parser.add_argument("--vocabulary-sizes", default="1000,2000,5000,10000")
    parser.add_argument("--details-out", type=Path,
                        help="write selected rule and exception words by vocabulary tier")
    args = parser.parse_args()

    frequencies = load_frequencies(args.frequencies, args.words)
    ranks = {word: index for index, (word, _) in enumerate(frequencies)}
    max_zipf = frequencies[0][1]
    weights = {word: 10 ** (zipf - max_zipf) for word, zipf in frequencies}
    total_weight = sum(weights.values())

    raw = json.loads(args.dictionary.read_text())
    outlines_by_word: dict[str, list[str]] = defaultdict(list)
    for outline, translation in raw.items():
        word = translation.lower()
        if word in ranks and hand_rules.WORD_RE.fullmatch(translation):
            outlines_by_word[word].append(outline)

    # The default Lapwing stack generates common inflections dynamically rather
    # than listing every surface form in lapwing-base.json. Synthesize their
    # documented suffix outlines so the text benchmark measures that behavior.
    for word, _ in frequencies:
        if word in outlines_by_word:
            continue
        derivations: list[tuple[str, str]] = []
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
        for root, suffix in derivations:
            for outline in outlines_by_word.get(root, ())[:4]:
                outlines_by_word[word].append(outline + "/" + suffix)

    tiers = [int(value) for value in args.vocabulary_sizes.split(",")]
    tier_vocabularies = [set(word for word, _ in frequencies[:size])
                         for size in tiers]
    rule_success = [set() for _ in tiers]
    # Chapter 18 fingerspelling handles isolated letters algorithmically.
    for tier_index, vocabulary in enumerate(tier_vocabularies):
        rule_success[tier_index].update(
            word for word in vocabulary if len(word) == 1 and word.isalpha()
        )

    for word, outlines in outlines_by_word.items():
        for outline in outlines:
            generated = hand_rules.generate_outline(outline, args.beam)
            if not generated:
                continue
            generated_set = set(generated)
            for tier_index, vocabulary in enumerate(tier_vocabularies):
                if word not in vocabulary or word in rule_success[tier_index]:
                    continue
                accepted = [candidate for candidate in generated_set
                            if candidate in vocabulary]
                if accepted and min(accepted, key=lambda item: ranks[item]) == word:
                    rule_success[tier_index].add(word)

    reports = []
    details = {}
    rule_bytes = hand_rules.packed_rule_size()
    available_weight = sum(weights[word] for word in outlines_by_word)
    for size, vocabulary, successes in zip(tiers, tier_vocabularies, rule_success):
        # Approximate immutable MPHF plus an 8-bit membership fingerprint.
        # The MPHF result is also the frequency-rank ID.
        vocabulary_bytes = (10 * len(vocabulary) + 7) // 8
        remaining = args.budget - rule_bytes - vocabulary_bytes
        covered = set(successes)
        exceptions = []
        if remaining > 0:
            candidates = []
            for word in outlines_by_word:
                if word in covered:
                    continue
                # Use a local estimate only to order candidates. The acceptance
                # check below measures the complete shared output pool.
                estimated_cost = EXCEPTION_RECORD_BYTES + max(1, len(word) // 2)
                candidates.append((weights[word] / estimated_cost, weights[word], word))
            candidates.sort(reverse=True)
            for _, _, word in candidates:
                proposed = exceptions + [word]
                if exception_storage_size(proposed) <= remaining:
                    covered.add(word)
                    exceptions.append(word)
        covered_weight = sum(weights[word] for word in covered)
        details[str(size)] = {
            "rule_words": sorted(successes, key=lambda word: ranks[word]),
            "exception_words": sorted(exceptions, key=lambda word: ranks[word]),
        }
        reports.append({
            "vocabulary_target_words": size,
            "vocabulary_stored_words": len(vocabulary),
            "rule_resolved_words": len(successes),
            "exception_words": len(exceptions),
            "bytes": {
                "rules": rule_bytes,
                "vocabulary_membership_and_rank": vocabulary_bytes,
                "exceptions": exception_storage_size(exceptions),
                "total": rule_bytes + vocabulary_bytes + exception_storage_size(exceptions),
            },
            "coverage_of_frequency_list": covered_weight / total_weight,
            "coverage_of_lapwing_available_mass": covered_weight / available_weight,
            "lapwing_available_mass": available_weight / total_weight,
        })

    if args.details_out:
        args.details_out.write_text(json.dumps(details, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "frequency_words": len(frequencies),
        "budget_bytes": args.budget,
        "rule_table_bytes": rule_bytes,
        "reports": reports,
        "notes": [
            "Frequency weights are derived from supplied Zipf frequencies.",
            "One usable outline per word is sufficient.",
            "Vocabulary cost assumes a compact MPHF plus 8-bit membership fingerprints; MPHF IDs encode rank.",
            "Exception outlines use an immutable MPHF, 24-bit fingerprint, and 16-bit output-pool ID (six bytes/entry estimate).",
            "Exception output words are stored in lexically front-coded 32-word blocks with 16-bit restart offsets.",
            "Decoder code size and QMK firmware are not included.",
        ],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
