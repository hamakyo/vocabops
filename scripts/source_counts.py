#!/usr/bin/env python
"""Build per-source term counts for the three-source corpus.

This is the measurement input for ``docs/ranking-evaluation.md``. It reads the
three fixed document files, normalizes them with the project's own pipeline
(``clean_text`` -> ``tokenize`` -> corpus-attested lemmatization), and writes
one scratch artifact holding ``tf`` and ``df`` per source, plus the per-source
token total and vocabulary size that the ``se_specificity`` smoothing needs.

The attested headword set is built from the *combined* corpus, matching how
``out/combined-rank-v1-df10`` was produced: the pipeline's pre-pass sees every
document, then lemmatizes with that one attested set.

    .venv/bin/python scripts/source_counts.py \
        --output out/ranking-eval/source-counts.json

The artifact is scratch data under ``out/`` (git-ignored); the evaluation is
reproducible from the document files with the command above followed by
``scripts/evaluate_rankings.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from vocabops.normalize import (
    attested_headwords,
    clean_text,
    normalize_tokens,
    tokenize,
)
# Same JSONL reader as the pipeline, so this measurement sees the same input
# contract (required fields, blank lines, line-numbered errors) as the ranking
# it is compared against.
from vocabops.pipeline import _read_jsonl_documents

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    REPO_ROOT / "out/gharchive/documents-day-v3.jsonl",
    REPO_ROOT / "out/stackoverflow/documents-so-sample.jsonl",
    REPO_ROOT / "out/codesearchnet/documents-csn-sample.jsonl",
)


def load_records(paths: list[Path]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Read the document files in order, tagging each record with its file."""
    records: list[tuple[str, str, str]] = []
    names: list[str] = []
    for path in paths:
        name = path.parent.name
        if name in names:
            raise ValueError(f"duplicate source directory name: {name}")
        names.append(name)
        for doc_id, _family, text in _read_jsonl_documents(path):
            records.append((doc_id, name, text))
    return records, names


def build_counts(
    records: list[tuple[str, str, str]], names: list[str]
) -> dict[str, Any]:
    """One normalization pass; per-source tf/df over the union vocabulary."""
    token_documents = [tokenize(clean_text(text)) for _, _, text in records]
    attested = attested_headwords(token_documents)
    doc_names = [name for _, name, _ in records]
    del records

    tf = {name: Counter() for name in names}
    df = {name: Counter() for name in names}
    documents = {name: 0 for name in names}

    for tokens, name in zip(token_documents, doc_names):
        lemmas = normalize_tokens(tokens, attested=attested)
        tf[name].update(lemmas)
        df[name].update(set(lemmas))
        documents[name] += 1

    sources = []
    for name in names:
        total = sum(tf[name].values())
        sources.append(
            {
                "name": name,
                "documents": documents[name],
                "total_tokens": total,
                "vocab_size": len(tf[name]),
                "attested_forms": len(attested),
                "tf": {term: tf[name][term] for term in sorted(tf[name])},
                "df": {term: df[name][term] for term in sorted(df[name])},
            }
        )
    union = set()
    for source in sources:
        union.update(source["tf"])
    return {
        "note": (
            "Per-source tf/df over the union vocabulary. Normalization: "
            "clean_text + tokenize + normalize_tokens with an attested set "
            "built from all documents (attestation_min_documents=3)."
        ),
        "attestation_min_documents": 3,
        "union_vocab_size": len(union),
        "sources": sources,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/source_counts.py",
        description="Compute per-source tf/df for the three-source corpus.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "out/ranking-eval/source-counts.json",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=list(DEFAULT_SOURCES),
        help="document JSONL files; the parent directory name is the source name",
    )
    args = parser.parse_args(argv)

    try:
        records, names = load_records([Path(p) for p in args.input])
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not records:
        print("error: no documents loaded", file=sys.stderr)
        return 2

    # ``build_counts`` consumes ``records`` in order; the per-document source
    # names are carried alongside, so the order is stable.
    counts = build_counts(records, names)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(counts, handle, ensure_ascii=False)
        handle.write("\n")

    for source in counts["sources"]:
        print(
            f"{source['name']:>14}: {source['documents']:>6} docs  "
            f"{source['total_tokens']:>9} tokens  "
            f"{source['vocab_size']:>7} types"
        )
    print(f"union vocabulary: {counts['union_vocab_size']} types")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
