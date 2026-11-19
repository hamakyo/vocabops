#!/usr/bin/env python
"""Derive the vocabulary and technical views from the classification review.

The classification file (``data/ranking-v3-classification.jsonl``) is the
review artifact: one row per ranked term, in rank order, with the bucket that
a human/LLM annotation assigned. This script only splits that file; it makes
no judgement of its own, so both views are reproducible from it:

    .venv/bin/python scripts/build_views.py \
        --classification data/ranking-v3-classification.jsonl \
        --vocab-output data/core500-vocab-v0.jsonl \
        --technical-output data/core500-technical-v0.jsonl

Buckets are the audit vocabulary from ``docs/core500-evaluation.md``:

    (a) transferable SE vocabulary      -> vocabulary view
    (b) technical nouns / names         -> technical view
    (c) abbreviations and acronyms      -> vocabulary view
    (d) fragments and artifacts         -> neither view
    (e) other / unclear                 -> neither view

Each output row carries ``view_rank`` (1-based within the view), the original
``rank``, ``tf``, ``df``, ``score`` and ``bucket``. Views keep ranking order
and are capped at ``--vocab-limit`` / ``--technical-limit`` rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VOCAB_BUCKETS = ("a", "c")
TECHNICAL_BUCKETS = ("b",)
ALL_BUCKETS = ("a", "b", "c", "d", "e")
DEFAULT_VOCAB_LIMIT = 500
DEFAULT_TECHNICAL_LIMIT = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/build_views.py",
        description="Split a classification file into the vocabulary and technical views.",
    )
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--vocab-output", type=Path, required=True)
    parser.add_argument("--technical-output", type=Path, required=True)
    parser.add_argument("--vocab-limit", type=int, default=DEFAULT_VOCAB_LIMIT)
    parser.add_argument("--technical-limit", type=int, default=DEFAULT_TECHNICAL_LIMIT)
    return parser


def load_classification(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
            for field in ("term", "rank", "tf", "df", "score", "bucket"):
                if field not in row:
                    raise ValueError(f"{path}:{lineno}: missing field {field!r}")
            if row["bucket"] not in ALL_BUCKETS:
                raise ValueError(f"{path}:{lineno}: unknown bucket {row['bucket']!r}")
            rows.append(row)
    expected = list(range(1, len(rows) + 1))
    if [row["rank"] for row in rows] != expected:
        raise ValueError(f"{path}: ranks must be contiguous and 1-based")
    return rows


def select(rows: list[dict], buckets: tuple[str, ...], limit: int) -> list[dict]:
    selected = [row for row in rows if row["bucket"] in buckets]
    if limit > 0:
        selected = selected[:limit]
    return [
        {
            "term": row["term"],
            "view_rank": index,
            "rank": row["rank"],
            "tf": row["tf"],
            "df": row["df"],
            "score": row["score"],
            "bucket": row["bucket"],
        }
        for index, row in enumerate(selected, start=1)
    ]


def write_view(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        classified = load_classification(args.classification)
        vocab = select(classified, VOCAB_BUCKETS, args.vocab_limit)
        technical = select(classified, TECHNICAL_BUCKETS, args.technical_limit)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_view(args.vocab_output, vocab)
    write_view(args.technical_output, technical)
    print(f"classified rows: {len(classified)}")
    print(f"vocab rows:      {len(vocab)} (a={sum(r['bucket'] == 'a' for r in vocab)}, "
          f"c={sum(r['bucket'] == 'c' for r in vocab)}) -> {args.vocab_output}")
    print(f"technical rows:  {len(technical)} -> {args.technical_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
