#!/usr/bin/env python3
"""Generate deterministic nonsense without reading or mutating external state."""

from __future__ import annotations

import argparse


WORDS = (
    "florp",
    "nebula",
    "wobblecrank",
    "zibble",
    "moonpickle",
    "quasar-snort",
    "blim",
    "frobnicate",
)
MAX_WORDS = 256


def generate(seed: int, word_count: int) -> str:
    """Return a stable sequence for the same seed and word count."""
    state = seed % len(WORDS)
    generated: list[str] = []
    for _ in range(word_count):
        state = (state * 5 + 3) % len(WORDS)
        generated.append(WORDS[state])
    return " ".join(generated) + "."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic gibberish from a seed and word count."
    )
    parser.add_argument("--seed", type=int, default=42, help="Numeric sequence seed.")
    parser.add_argument(
        "--words",
        type=int,
        default=8,
        metavar="1..256",
        help="Number of words to emit, from 1 through 256 (default: 8).",
    )
    args = parser.parse_args()
    if not 1 <= args.words <= MAX_WORDS:
        parser.error(f"--words must be between 1 and {MAX_WORDS}")
    return args


def main() -> None:
    args = parse_args()
    print(generate(args.seed, args.words))


if __name__ == "__main__":
    main()
