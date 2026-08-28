#!/usr/bin/env python3
"""Evaluate a frozen Lapwing model selection on independent text corpora."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import generate_model
from common_text_budget import load_frequencies

TOKEN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def tokenize(text: str) -> list[str]:
    normalized = text.replace("\u2018", "'").replace("\u2019", "'")
    return [match.group(0).lower() for match in TOKEN_RE.finditer(normalized)]


def frequency_report(
    frequencies: list[tuple[str, float]], conventional: set[str], limit: int,
) -> dict[str, int | float]:
    selected = frequencies[:limit]
    maximum = frequencies[0][1]
    weights = {word: 10 ** (zipf - maximum) for word, zipf in selected}
    total = sum(weights.values())
    covered = sum(weight for word, weight in weights.items() if word in conventional)
    return {
        "word_types": len(selected),
        "conventional_word_types": sum(word in conventional for word, _ in selected),
        "conventional_frequency_coverage": covered / total if total else 0.0,
    }


def missing_word_report(
    tokens: list[str], conventional: set[str], frequency_words: list[str],
    selection_words: int, dictionary_words: set[str], limit: int = 100,
) -> dict[str, object]:
    counts = Counter(word for word in tokens if word not in conventional)
    ranks = {word: index for index, word in enumerate(frequency_words)}
    categories: dict[str, dict[str, int]] = {}
    for word, count in counts.items():
        rank = ranks.get(word)
        if rank is None:
            category = "absent_from_frequency_source"
        elif rank >= selection_words:
            category = "below_selection_cutoff"
        elif word not in dictionary_words:
            category = "absent_from_lapwing_stack"
        else:
            category = "unresolved_or_omitted"
        totals = categories.setdefault(category, {"tokens": 0, "word_types": 0})
        totals["tokens"] += count
        totals["word_types"] += 1
    return {
        "categories": categories,
        "top_words": [
            {"word": word, "tokens": count}
            for word, count in counts.most_common(limit)
        ],
    }


def corpus_report(tokens: list[str], conventional: set[str]) -> dict[str, int | float]:
    counts = Counter(tokens)
    conventional_tokens = sum(count for word, count in counts.items() if word in conventional)
    fingerspellable_tokens = sum(
        count for word, count in counts.items()
        if word.isalpha() and len(word) <= 16
    )
    total = len(tokens)
    return {
        "tokens": total,
        "unique_word_types": len(counts),
        "conventional_tokens": conventional_tokens,
        "conventional_token_coverage": conventional_tokens / total if total else 0.0,
        "fingerspellable_tokens": fingerspellable_tokens,
        "fingerspellable_token_coverage": fingerspellable_tokens / total if total else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("frequencies", type=Path)
    parser.add_argument("corpora", type=Path, nargs="+")
    parser.add_argument("--words", type=int, default=20000)
    parser.add_argument("--vocabulary", type=int, default=7250)
    parser.add_argument("--evaluation-words", type=int, default=50000)
    parser.add_argument("--beam", type=int, default=64)
    parser.add_argument("--total-data-budget", type=int, default=40960)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    dictionary = json.loads(args.dictionary.read_text())
    frequencies = load_frequencies(args.frequencies, args.evaluation_words)
    model_frequencies = frequencies[:args.words]
    _, _, model_report = generate_model.choose_model(
        dictionary, model_frequencies, args.vocabulary, args.beam,
        args.total_data_budget - generate_model.RULE_BYTES,
    )
    conventional = set(model_report["conventional_words"])

    reports: dict[str, dict[str, int | float]] = {}
    aggregate: list[str] = []
    for corpus in args.corpora:
        tokens = tokenize(corpus.read_text(errors="replace"))
        reports[corpus.name] = corpus_report(tokens, conventional)
        aggregate.extend(tokens)
    dictionary_words = {
        translation.lower()
        for translation in dictionary.values()
        if isinstance(translation, str) and generate_model.WORD_RE.fullmatch(translation)
    }
    result = {
        "model_selection_words": args.words,
        "model_conventional_word_types": len(conventional),
        "frequency_cutoffs": {
            str(limit): frequency_report(frequencies, conventional, limit)
            for limit in (5000, 10000, 20000, min(50000, len(frequencies)))
        },
        "corpora": reports,
        "aggregate": corpus_report(aggregate, conventional),
        "missing": missing_word_report(
            aggregate, conventional, [word for word, _ in frequencies],
            args.words, dictionary_words,
        ),
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
