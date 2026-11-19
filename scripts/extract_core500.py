#!/usr/bin/env python
"""Extract the Core 500 candidate from a pipeline ranking.

This is an extraction step, not a publication step: it takes the first N rows
of an existing ``ranking.json`` (already sorted by ``se_specificity`` desc,
then term asc) and writes one JSON object per line with ``term``, ``rank``
(1-based), ``tf``, ``df`` and ``score`` (the pipeline's ``se_specificity``).

The output is byte-identical for the same input ranking:

    .venv/bin/python scripts/extract_core500.py \
        --ranking out/gharchive-rank-day-floor-df10/ranking.json \
        --output data/core500-v0.jsonl

The candidate is derived from the 24-hour GH Archive day corpus at
``--min-df 10`` with the shared ``ENGLISH_WORD_MIN_FREQUENCY`` floor; see
``docs/core500-evaluation.md``. Regenerate the ranking first (see
``docs/prototype.md``) if it is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_LIMIT = 500


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/extract_core500.py",
        description="Extract the top N rows of a ranking.json as core500 JSONL.",
    )
    parser.add_argument(
        "--ranking",
        type=Path,
        required=True,
        help="path to a pipeline ranking.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="path of the JSONL file to write",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"number of rows to take (default: {DEFAULT_LIMIT})",
    )
    return parser


def extract(ranking_path: Path, output_path: Path, limit: int = DEFAULT_LIMIT) -> int:
    """Write the first ``limit`` rows as JSONL and return the row count."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    with ranking_path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError(f"{ranking_path}: expected a JSON list of rows")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for rank, row in enumerate(rows[:limit], start=1):
            record = {
                "term": row["term"],
                "rank": rank,
                "tf": row["tf"],
                "df": row["df"],
                "score": row["se_specificity"],
            }
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        written = extract(args.ranking, args.output, args.limit)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"rows:   {written}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
