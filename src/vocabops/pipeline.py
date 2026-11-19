"""End-to-end corpus pipeline for the VocabOps prototype.

Usage::

    python -m vocabops.pipeline \
        --input data/fixtures/sample_corpus \
        --output out/human-se-v0.1-proto \
        --snapshot-id human-se-v0.1-proto

Every ``.txt`` file in the input directory is one document with
``source_family = "fixture"``. Documents are assigned a stable ID derived from
``sha256(source_family + "/" + relative path)`` so that identity survives
re-runs and file moves inside the corpus root are visible.

Outputs (written to the output directory):

- ``ranking.json`` — list of term rows, sorted by ``se_specificity`` desc then
  term asc
- ``ranking.csv`` — the same rows as CSV
- ``manifest.json`` — snapshot metadata and corpus counts

The pipeline writes no timestamps, so repeated runs on the same inputs produce
byte-identical files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .normalize import normalize
from .stats import ALPHA, rank_terms

__all__ = [
    "PIPELINE_VERSION",
    "SOURCE_FAMILY",
    "document_id",
    "load_documents",
    "run",
    "main",
]

PIPELINE_VERSION = __version__
SOURCE_FAMILY = "fixture"
GENERAL_BASELINE = "wordfreq"
SCORE_DECIMALS = 6


def document_id(source_family: str, relative_path: str) -> str:
    """Stable document ID: sha256 of ``source_family + "/" + relative path``."""
    digest = hashlib.sha256()
    digest.update(f"{source_family}/{relative_path}".encode("utf-8"))
    return digest.hexdigest()


def load_documents(
    input_dir: Path, source_family: str = SOURCE_FAMILY
) -> list[tuple[str, str, list[str]]]:
    """Read every ``.txt`` file in ``input_dir`` as one normalized document.

    Returns ``(document_id, relative_path, lemmas)`` tuples in sorted path
    order so the corpus is independent of filesystem iteration order.
    """
    paths = sorted(path for path in input_dir.glob("*.txt") if path.is_file())
    documents = []
    for path in paths:
        relative_path = path.relative_to(input_dir).as_posix()
        lemmas = normalize(path.read_text(encoding="utf-8"))
        documents.append(
            (document_id(source_family, relative_path), relative_path, lemmas)
        )
    return documents


def run(
    input_dir: Path,
    output_dir: Path,
    snapshot_id: str,
    alpha: float = ALPHA,
) -> dict[str, object]:
    """Run the prototype pipeline and write ranking and manifest files."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    documents = load_documents(input_dir)
    if not documents:
        raise ValueError(f"no .txt documents found in {input_dir}")

    rows = rank_terms([lemmas for _, _, lemmas in documents], alpha=alpha)
    ranking = [
        {
            "term": row["term"],
            "tf": row["tf"],
            "df": row["df"],
            "se_specificity": round(float(row["se_specificity"]), SCORE_DECIMALS),
        }
        for row in rows
    ]

    manifest: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "pipeline_version": PIPELINE_VERSION,
        "sources": [SOURCE_FAMILY],
        "general_baseline": GENERAL_BASELINE,
        "documents": len(documents),
        "tokens": sum(len(lemmas) for _, _, lemmas in documents),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_ranking_json(output_dir / "ranking.json", ranking)
    _write_ranking_csv(output_dir / "ranking.csv", ranking)
    _write_manifest(output_dir / "manifest.json", manifest)
    return manifest


def _write_ranking_json(path: Path, ranking: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(ranking, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_ranking_csv(path: Path, ranking: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["term", "tf", "df", "se_specificity"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(ranking)


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vocabops.pipeline",
        description="Build a se_specificity ranking from a corpus directory.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="directory containing .txt documents (one document per file)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="directory for ranking.json, ranking.csv and manifest.json",
    )
    parser.add_argument(
        "--snapshot-id",
        required=True,
        help="fixed snapshot identifier recorded in the manifest",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=ALPHA,
        help=f"additive smoothing constant (default: {ALPHA})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.snapshot_id.strip():
        print("error: --snapshot-id must not be empty", file=sys.stderr)
        return 2
    try:
        manifest = run(args.input, args.output, args.snapshot_id, alpha=args.alpha)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"snapshot:  {manifest['snapshot_id']}")
    print(f"documents: {manifest['documents']}")
    print(f"tokens:    {manifest['tokens']}")
    print(f"output:    {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
