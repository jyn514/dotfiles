#!/usr/bin/env python3
"""Generate the pinned independent English frequency input."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable, Iterable

PINNED_VERSION = "3.1.1"
DEFAULT_WORDS = 50_000


def render_frequencies(
    words: Iterable[str], score: Callable[[str], float],
) -> bytes:
    return "".join(f"{word}\t{score(word)}\n" for word in words).encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--words", type=int, default=DEFAULT_WORDS)
    args = parser.parse_args()

    try:
        installed = version("wordfreq")
    except PackageNotFoundError as error:
        raise SystemExit(
            f"wordfreq=={PINNED_VERSION} is required to generate this input"
        ) from error
    if installed != PINNED_VERSION:
        raise SystemExit(
            f"wordfreq=={PINNED_VERSION} is required; found {installed}"
        )

    from wordfreq import top_n_list, zipf_frequency

    words = top_n_list("en", args.words)
    data = render_frequencies(words, lambda word: zipf_frequency(word, "en"))
    args.output.write_bytes(data)
    print(f"{hashlib.sha256(data).hexdigest()}  {args.output}")


if __name__ == "__main__":
    main()
