#!/usr/bin/env python
"""Evaluate candidate ranking fusions for the three-source corpus.

Reads the per-source count artifact produced by ``scripts/source_counts.py``
and the existing combined ranking, then measures every candidate method on the
metrics fixed in ``docs/ranking-evaluation.md``:

1. the eight tracked target terms (rank, median, count in top 500);
2. recovery of the 500 terms in ``data/core500-vocab-v2.jsonl`` at depth 500
   and 1,020;
3. ranks of six artifact terms;
4. the character of the top 100 by the existing v6 (then v5) classification.

The first step is a hard sanity check: the pooled counts must reproduce the
combined ranking's ``tf``/``df`` for its top 100 terms exactly, and its full
ordering and rounded scores. A mismatch is reported and the run stops.

    .venv/bin/python scripts/evaluate_rankings.py \
        --counts out/ranking-eval/source-counts.json \
        --combined out/combined-rank-v1-df10/ranking.json \
        --output out/ranking-eval/metrics.json \
        --markdown out/ranking-eval/report.md

All inputs are committed document/ranking artifacts except the counts file,
which ``scripts/source_counts.py`` regenerates from the document files.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from wordfreq import word_frequency

from vocabops.fusion import (
    SourceStats,
    borda_scores,
    geometric_mean_specificity,
    mean_specificity,
    min_specificity,
    positive_shift,
    presence_count,
    present_in_at_least,
)
from vocabops.stats import ALPHA, se_specificity

REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_DF = 10
TARGETS = (
    "retrieve",
    "persist",
    "invoke",
    "propagate",
    "reproduce",
    "invalidate",
    "fallback",
    "underlying",
)
ARTIFACTS = ("param", "rtype", "ioexception", "getelementbyid", "kwarg", "dataframe")
DEPTHS = (500, 1020)
SCORE_DECIMALS = 6


@lru_cache(maxsize=None)
def general_frequency(term: str) -> float:
    return word_frequency(term, "en")


def load_counts(path: Path) -> list[SourceStats]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        SourceStats(
            name=source["name"],
            tf={k: int(v) for k, v in source["tf"].items()},
            df={k: int(v) for k, v in source["df"].items()},
            total_tokens=int(source["total_tokens"]),
            vocab_size=int(source["vocab_size"]),
            documents=int(source["documents"]),
        )
        for source in payload["sources"]
    ]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def pooled_source(sources: list[SourceStats]) -> SourceStats:
    tf: Counter[str] = Counter()
    df: Counter[str] = Counter()
    for source in sources:
        tf.update(source.tf)
        df.update(source.df)
    return SourceStats(
        name="pooled",
        tf=dict(tf),
        df=dict(df),
        total_tokens=sum(source.total_tokens for source in sources),
        vocab_size=len(tf),
    )


def score_table(
    terms: list[str], source: SourceStats
) -> dict[str, float]:
    return {
        term: se_specificity(
            term=term,
            tf=source.tf.get(term, 0),
            total_tokens=source.total_tokens,
            vocab_size=source.vocab_size,
            alpha=ALPHA,
            general_frequency=general_frequency(term),
        )
        for term in terms
    }


def rank_rows(scores: Mapping[str, float], lower_is_better: bool = False) -> list[dict]:
    """Order terms by score (desc unless ``lower_is_better``), then term asc."""
    if lower_is_better:
        ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    else:
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"term": term, "rank": index, "score": score}
        for index, (term, score) in enumerate(ordered, start=1)
    ]


def sanity_check(
    pooled: SourceStats, combined_rows: list[dict], pooled_scores: dict[str, float]
) -> list[str]:
    """Compare pooled counts/scores against the existing combined ranking."""
    problems: list[str] = []
    top = combined_rows[:100]
    if len(top) < 100:
        problems.append(f"combined ranking only has {len(top)} rows")
    for row in top:
        term = row["term"]
        if term not in pooled.tf:
            problems.append(f"{term}: missing from pooled counts")
            continue
        if pooled.tf[term] != row["tf"]:
            problems.append(
                f"{term}: tf {pooled.tf[term]} != combined {row['tf']}"
            )
        if pooled.df[term] != row["df"]:
            problems.append(
                f"{term}: df {pooled.df[term]} != combined {row['df']}"
            )
        score = round(pooled_scores[term], SCORE_DECIMALS)
        if score != row["se_specificity"]:
            problems.append(
                f"{term}: score {score} != combined {row['se_specificity']}"
            )

    if len(combined_rows) != len(pooled_scores):
        problems.append(
            f"row count: pooled {len(pooled_scores)} != combined {len(combined_rows)}"
        )
    expected_order = [row["term"] for row in combined_rows]
    actual_order = [
        row["term"] for row in rank_rows(pooled_scores)
    ]
    if expected_order != actual_order:
        first = next(
            (
                index
                for index, (a, b) in enumerate(zip(expected_order, actual_order))
                if a != b
            ),
            min(len(expected_order), len(actual_order)),
        )
        problems.append(
            "ordering differs from first mismatch at position "
            f"{first + 1}: combined={expected_order[first:first + 3]} "
            f"pooled={actual_order[first:first + 3]}"
        )
    return problems


def median_rank(ranks: list[int]) -> float:
    return float(statistics.median(ranks))


def bucket_map(*paths: Path) -> dict[str, str]:
    """First-file-wins bucket lookup across the classification files."""
    mapping: dict[str, str] = {}
    for path in paths:
        for row in load_jsonl(path):
            mapping.setdefault(row["term"], row["bucket"])
    return mapping


def build_methods(
    sources: list[SourceStats], pooled: SourceStats
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return method -> {rows, notes} plus a shared definitions record."""
    pooled_terms = sorted(
        term for term, df in pooled.df.items() if df >= MIN_DF
    )
    pooled_scores = score_table(pooled_terms, pooled)
    union_terms = sorted(pooled.tf)

    shift = positive_shift(union_terms, sources, general_frequency)

    mean_scores = {
        term: mean_specificity(term, sources, general_frequency)
        for term in pooled_terms
    }
    min_scores = {
        term: min_specificity(term, sources, general_frequency)
        for term in pooled_terms
    }
    geo_scores = {
        term: geometric_mean_specificity(term, sources, shift, general_frequency)
        for term in pooled_terms
    }
    borda = borda_scores(pooled_terms, sources, MIN_DF, general_frequency)

    presence_two = present_in_at_least(pooled_terms, sources, 2)
    restrict_scores = {term: pooled_scores[term] for term in presence_two}

    methods = {
        "M0 pooled": {
            "rows": rank_rows(pooled_scores),
            "definition": "Pooled score (existing combined ranking).",
        },
        "M1 mean": {
            "rows": rank_rows(mean_scores),
            "definition": (
                "Mean of the three per-source scores; an absent term takes that "
                "source's smoothed floor score."
            ),
        },
        "M2 min": {
            "rows": rank_rows(min_scores),
            "definition": "Minimum of the three per-source scores.",
        },
        "M3 Borda": {
            "rows": rank_rows(borda, lower_is_better=True),
            "definition": (
                "Sum of per-source ranks; a term below a source's df>=10 cut "
                "gets listed+1 (below every listed term, tied with other absent "
                "terms)."
            ),
        },
        "M4 pooled+presence": {
            "rows": rank_rows(restrict_scores),
            "definition": (
                "Pooled score, restricted to terms with df>0 in at least 2 of 3 "
                "sources and pooled df>=10."
            ),
        },
        "M5 geometric": {
            "rows": rank_rows(geo_scores),
            "definition": (
                f"Geometric mean of per-source scores shifted by {shift:.6f} "
                "(smallest union score maps to 1.0)."
            ),
        },
    }
    return methods, {
        "shift": shift,
        "pooled_rows": len(pooled_terms),
        "union_vocab_size": len(union_terms),
        "per_source_eligible": {
            source.name: sum(1 for df in source.df.values() if df >= MIN_DF)
            for source in sources
        },
        "presence_counts": dict(
            Counter(presence_count(term, sources) for term in pooled_terms)
        ),
    }


def method_metrics(
    rows: list[dict],
    vocab_terms: list[str],
    buckets: dict[str, str],
    sources: list[SourceStats],
) -> dict[str, Any]:
    ranks = {row["term"]: row["rank"] for row in rows}
    target_ranks = {term: ranks.get(term) for term in TARGETS}
    present_target_ranks = [r for r in target_ranks.values() if r is not None]

    by_depth = {
        depth: sum(1 for term in vocab_terms if ranks.get(term, math.inf) <= depth)
        for depth in DEPTHS
    }

    top100 = [row["term"] for row in rows[:100]]
    core_buckets = Counter()
    unclassified = 0
    for term in top100:
        bucket = buckets.get(term)
        if bucket is None:
            unclassified += 1
        else:
            core_buckets[bucket] += 1

    presence = Counter(presence_count(term, sources) for term in top100)

    return {
        "rows": len(rows),
        "target_ranks": target_ranks,
        "target_median": median_rank(present_target_ranks)
        if present_target_ranks
        else None,
        "targets_in_top500": sum(1 for r in present_target_ranks if r <= 500),
        "view_recovery": by_depth,
        "artifact_ranks": {term: ranks.get(term) for term in ARTIFACTS},
        "top100": {
            "a": core_buckets["a"],
            "c": core_buckets["c"],
            "a_plus_c": core_buckets["a"] + core_buckets["c"],
            "b": core_buckets["b"],
            "d": core_buckets["d"],
            "e": core_buckets["e"],
            "unclassified": unclassified,
        },
        "top100_presence": {
            "one": presence[1],
            "two": presence[2],
            "three": presence[3],
        },
    }


def markdown(
    methods: dict[str, dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    definitions: dict[str, Any],
    sources: list[SourceStats],
) -> str:
    lines: list[str] = []
    add = lines.append

    add("## Corpus")
    add("")
    add("| source | documents | tokens | types | df>=10 terms |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for source in sources:
        add(
            f"| {source.name} | {source.documents:,} | {source.total_tokens:,} | "
            f"{source.vocab_size:,} | "
            f"{definitions['per_source_eligible'][source.name]:,} |"
        )
    add("")

    add("## Row counts")
    add("")
    add("| method | rows |")
    add("| --- | ---: |")
    for name, data in methods.items():
        add(f"| {name} | {metrics[name]['rows']:,} |")
    add("")

    add("## Target terms")
    add("")
    header = "| term | " + " | ".join(methods) + " |"
    add(header)
    add("| --- | " + " | ".join("---:" for _ in methods) + " |")
    for term in TARGETS:
        cells = []
        for name in methods:
            rank = metrics[name]["target_ranks"][term]
            cells.append(f"{rank:,}" if rank else "—")
        add(f"| `{term}` | " + " | ".join(cells) + " |")
    add(
        "| **median** | "
        + " | ".join(f"{metrics[name]['target_median']:.1f}" for name in methods)
        + " |"
    )
    add(
        "| **top 500** | "
        + " | ".join(str(metrics[name]["targets_in_top500"]) for name in methods)
        + " |"
    )
    add("")

    add("## View recovery")
    add("")
    add("| method | top 500 | top 1,020 |")
    add("| --- | ---: | ---: |")
    for name in methods:
        recovery = metrics[name]["view_recovery"]
        add(f"| {name} | {recovery[500]} | {recovery[1020]} |")
    add("")

    add("## Artifact ranks")
    add("")
    add("| term | " + " | ".join(methods) + " |")
    add("| --- | " + " | ".join("---:" for _ in methods) + " |")
    for term in ARTIFACTS:
        cells = [
            f"{metrics[name]['artifact_ranks'][term]:,}"
            if metrics[name]["artifact_ranks"][term]
            else "—"
            for name in methods
        ]
        add(f"| `{term}` | " + " | ".join(cells) + " |")
    add("")

    add("## Source footprint")
    add("")
    add("| term | " + " | ".join(source.name + " df" for source in sources) + " | sources |")
    add("| --- | " + " | ".join("---:" for _ in sources) + " | ---: |")
    for term in TARGETS + ARTIFACTS:
        cells = [f"{source.df.get(term, 0):,}" for source in sources]
        present = sum(1 for source in sources if source.df.get(term, 0) > 0)
        add(f"| `{term}` | " + " | ".join(cells) + f" | {present} |")
    add("")

    add("## Top-100 source presence")
    add("")
    add("| method | 1 source | 2 sources | 3 sources |")
    add("| --- | ---: | ---: | ---: |")
    for name in methods:
        presence = metrics[name]["top100_presence"]
        add(
            f"| {name} | {presence['one']} | {presence['two']} | "
            f"{presence['three']} |"
        )
    add("")

    add("## Top-100 character")
    add("")
    add("| method | a | c | a+c | b | d | e | unclassified |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name in methods:
        top = metrics[name]["top100"]
        add(
            f"| {name} | {top['a']} | {top['c']} | **{top['a_plus_c']}** | "
            f"{top['b']} | {top['d']} | {top['e']} | {top['unclassified']} |"
        )
    add("")

    add("## Top 20 per method")
    add("")
    for name in methods:
        add(f"### {name}")
        add("")
        add(", ".join(f"`{row['term']}`" for row in methods[name]["rows"][:20]))
        add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/evaluate_rankings.py",
        description="Evaluate candidate ranking fusions for the three-source corpus.",
    )
    parser.add_argument(
        "--counts",
        type=Path,
        default=REPO_ROOT / "out/ranking-eval/source-counts.json",
    )
    parser.add_argument(
        "--combined",
        type=Path,
        default=REPO_ROOT / "out/combined-rank-v1-df10/ranking.json",
    )
    parser.add_argument(
        "--vocab",
        type=Path,
        default=REPO_ROOT / "data/core500-vocab-v2.jsonl",
    )
    parser.add_argument(
        "--classification",
        type=Path,
        nargs="+",
        default=[
            REPO_ROOT / "data/ranking-v6-classification.jsonl",
            REPO_ROOT / "data/ranking-v5-classification.jsonl",
        ],
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        sources = load_counts(args.counts)
    except FileNotFoundError:
        print(
            f"error: {args.counts} not found; run scripts/source_counts.py first",
            file=sys.stderr,
        )
        return 2

    combined_rows = json.loads(args.combined.read_text(encoding="utf-8"))
    pooled = pooled_source(sources)
    pooled_scores = score_table(
        sorted(term for term, df in pooled.df.items() if df >= MIN_DF), pooled
    )

    problems = sanity_check(pooled, combined_rows, pooled_scores)
    if problems:
        print("SANITY CHECK FAILED — stopping before evaluation:", file=sys.stderr)
        for problem in problems[:50]:
            print(f"  - {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 3
    print(
        "sanity check: pooled counts reproduce the combined ranking "
        f"({len(pooled_scores):,} rows, top-100 tf/df exact, ordering identical)"
    )

    methods, definitions = build_methods(sources, pooled)
    vocab_terms = [row["term"] for row in load_jsonl(args.vocab)]
    buckets = bucket_map(*args.classification)

    metrics = {
        name: method_metrics(data["rows"], vocab_terms, buckets, sources)
        for name, data in methods.items()
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "definitions": definitions,
                    "metrics": metrics,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    report = markdown(methods, metrics, definitions, sources)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(report + "\n", encoding="utf-8")

    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
