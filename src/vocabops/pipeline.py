"""End-to-end corpus pipeline for the VocabOps prototype.

Usage::

    # directory of .txt documents (Phase 1 fixtures)
    python -m vocabops.pipeline \
        --input data/fixtures/sample_corpus \
        --output out/human-se-v0.1-proto \
        --snapshot-id human-se-v0.1-proto

    # JSONL documents produced by ``python -m vocabops.ingest``
    python -m vocabops.pipeline \
        --input out/gharchive/documents.jsonl \
        --output out/gharchive-rank \
        --snapshot-id gharchive-2026-11-18-3-proto \
        --min-df 3

Every ``.txt`` file in an input directory is one document with
``source_family = "fixture"``. Documents are assigned a stable ID derived from
``sha256(source_family + "/" + relative path)`` so that identity survives
re-runs and file moves inside the corpus root are visible.

When ``--input`` is a ``.jsonl`` file, every line is one document. Its
``text`` field holds the body, its ``source_family`` field is preserved, and
its ``doc_id`` is reused when present. The manifest's ``sources`` list is
derived from the distinct source families actually present in the input.

``--min-df N`` (default 1) drops terms that occur in fewer than ``N``
documents from ``ranking.json`` and ``ranking.csv``. Frequencies and scores
are still computed over the whole corpus; only the emitted rows are filtered.

``--ranking-method {pooled,borda}`` (default ``pooled``) selects the ranking.
``pooled`` is the existing single-table ``se_specificity`` ranking. ``borda``
groups documents by ``source_family``, ranks each source's own ``df >= min_df``
terms by that source's ``se_specificity``, and sums percentile ranks
(``rank / listed``; an absent term contributes 1.0), so the score column holds
the fused value and lower is better. Borda mode requires at least two source
families and fails rather than falling back. Its manifest records the method,
variant and each source's document/token/listed counts.

Before lemmatizing, the pipeline tokenizes every document and counts in how
many documents each raw form occurs. Forms in at least
``ATTESTATION_MIN_DOCUMENTS`` (3) documents are corpus-attested headwords, and
the lemmatizer may accept an attested candidate that wordfreq places below the
lemma floor (``rebase`` 6.46e-08, ``dedup`` 0.0). The pre-pass reads documents
in the same fixed order as everything else and uses only set membership, so it
cannot change output for the same input.

Outputs (written to the output directory):

- ``ranking.json`` — list of term rows, sorted by ``se_specificity`` desc then
  term asc
- ``ranking.csv`` — the same rows as CSV
- ``manifest.json`` — snapshot metadata and corpus counts, plus
  ``attestation_min_documents`` and the number of ``attested_forms``

The pipeline writes no timestamps, so repeated runs on the same inputs produce
byte-identical files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .fusion import SourceStats, borda_scores_percentile
from .normalize import (
    ATTESTATION_MIN_DOCUMENTS,
    attested_headwords,
    clean_text,
    normalize,
    normalize_tokens,
    tokenize,
)
from .stats import ALPHA, rank_terms

__all__ = [
    "PIPELINE_VERSION",
    "SOURCE_FAMILY",
    "RANKING_METHODS",
    "BORDA_VARIANT",
    "document_id",
    "load_documents",
    "load_jsonl_documents",
    "run",
    "main",
]

PIPELINE_VERSION = __version__
SOURCE_FAMILY = "fixture"
GENERAL_BASELINE = "wordfreq"
SCORE_DECIMALS = 6
DEFAULT_MIN_DF = 1
RANKING_METHODS = ("pooled", "borda")
# The Borda absence-penalty correction measured in docs/ranking-evaluation.md.
BORDA_VARIANT = "percentile"


def document_id(source_family: str, relative_path: str) -> str:
    """Stable document ID: sha256 of ``source_family + "/" + relative path``."""
    digest = hashlib.sha256()
    digest.update(f"{source_family}/{relative_path}".encode("utf-8"))
    return digest.hexdigest()


def _read_txt_documents(
    input_dir: Path, source_family: str = SOURCE_FAMILY
) -> list[tuple[str, str, str]]:
    """Read every ``.txt`` file in ``input_dir`` as one raw document.

    Returns ``(document_id, relative_path, text)`` tuples in sorted path order
    so the corpus is independent of filesystem iteration order.
    """
    paths = sorted(path for path in input_dir.glob("*.txt") if path.is_file())
    return [
        (
            document_id(source_family, path.relative_to(input_dir).as_posix()),
            path.relative_to(input_dir).as_posix(),
            path.read_text(encoding="utf-8"),
        )
        for path in paths
    ]


def load_documents(
    input_dir: Path, source_family: str = SOURCE_FAMILY
) -> list[tuple[str, str, list[str]]]:
    """Read every ``.txt`` file in ``input_dir`` as one normalized document.

    Returns ``(document_id, relative_path, lemmas)`` tuples in sorted path
    order. This is the corpus-free normalization path (no attested set); the
    pipeline's own run builds the attested set first and normalizes from it.
    """
    return [
        (doc_id, relative_path, normalize(text))
        for doc_id, relative_path, text in _read_txt_documents(
            input_dir, source_family
        )
    ]


def _read_jsonl_documents(path: Path) -> list[tuple[str, str, str]]:
    """Read a JSONL document file as ``(document_id, source_family, text)``.

    Each line must be a JSON object with a non-empty string ``text`` and
    ``source_family``. ``doc_id`` is reused when present, otherwise a stable ID
    is derived from the source family and the 1-based line number, so the
    fallback depends on position rather than on content.

    Blank lines are ignored; anything else that fails to parse is an error
    naming the line number.
    """
    documents: list[tuple[str, str, str]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")

            text = record.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{path}:{line_number}: missing non-empty 'text'")
            family = record.get("source_family")
            if not isinstance(family, str) or not family.strip():
                raise ValueError(
                    f"{path}:{line_number}: missing non-empty 'source_family'"
                )
            family = family.strip()

            doc_id = record.get("doc_id")
            if not isinstance(doc_id, str) or not doc_id.strip():
                doc_id = document_id(family, f"line/{line_number}")
            documents.append((doc_id.strip(), family, text))
    return documents


def load_jsonl_documents(path: Path) -> list[tuple[str, str, list[str]]]:
    """Read a JSONL document file as ``(document_id, source_family, lemmas)``.

    The corpus-free normalization path, kept for callers that want the plain
    single-document behavior; :func:`run` normalizes from the attested set.
    """
    return [
        (doc_id, family, normalize(text))
        for doc_id, family, text in _read_jsonl_documents(path)
    ]


def _load_document_texts(path: Path) -> list[tuple[str, str, str]]:
    """Load either a ``.txt`` directory or a ``.jsonl`` document file as text."""
    if path.is_dir():
        return [
            (doc_id, SOURCE_FAMILY, text)
            for doc_id, _, text in _read_txt_documents(path)
        ]
    if path.is_file():
        if path.suffix.lower() == ".jsonl":
            return _read_jsonl_documents(path)
        raise ValueError(
            f"unsupported input file {path}: expected a directory of .txt "
            "documents or a .jsonl file"
        )
    raise FileNotFoundError(f"input not found: {path}")


def _source_stats(
    documents: Sequence[tuple[str, str, list[str]]],
) -> list[SourceStats]:
    """Per-source count tables, ordered by source family name.

    ``vocab_size`` is that source's number of distinct lemma types, the same
    smoothing denominator the evaluation uses. Only terms the source uses are
    stored; a missing key is a zero count.
    """
    tf: dict[str, Counter[str]] = {}
    df: dict[str, Counter[str]] = {}
    counts: dict[str, int] = {}
    for _, family, lemmas in documents:
        tf.setdefault(family, Counter()).update(lemmas)
        df.setdefault(family, Counter()).update(set(lemmas))
        counts[family] = counts.get(family, 0) + 1
    return [
        SourceStats(
            name=family,
            tf=dict(tf[family]),
            df=dict(df[family]),
            total_tokens=sum(tf[family].values()),
            vocab_size=len(tf[family]),
            documents=counts[family],
        )
        for family in sorted(tf)
    ]


def run(
    input_path: Path,
    output_dir: Path,
    snapshot_id: str,
    alpha: float = ALPHA,
    min_df: int = DEFAULT_MIN_DF,
    ranking_method: str = "pooled",
) -> dict[str, object]:
    """Run the prototype pipeline and write ranking and manifest files."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if min_df < 1:
        raise ValueError("min_df must be at least 1")
    if ranking_method not in RANKING_METHODS:
        raise ValueError(
            f"unknown ranking method {ranking_method!r}; "
            f"choose from {', '.join(RANKING_METHODS)}"
        )

    records = _load_document_texts(input_path)
    if not records:
        raise ValueError(f"no documents found in {input_path}")

    # Corpus-attested headwords, computed before lemmatization so that a
    # candidate the suffix rules propose can be validated by the corpus itself
    # when wordfreq is below the lemma floor (``rebase`` 6.46e-08, ``dedup``
    # 0.0). The pass is deterministic: documents are read in a fixed order, the
    # attested set is a set built from document-frequency counts, and no
    # threshold depends on the set's contents.
    token_documents = [
        tokenize(clean_text(text)) for _, _, text in records
    ]
    attested = attested_headwords(token_documents)
    # Keep only the identity of each document while normalizing. The raw token
    # lists are released one at a time, so the peak holds either raw tokens or
    # lemmas for a document, not both full corpora at once. This matters for
    # the 52k-document combined corpus and changes no output.
    keys = [(doc_id, family) for doc_id, family, _ in records]
    del records
    documents = []
    for index, (doc_id, family) in enumerate(keys):
        tokens = token_documents[index]
        documents.append((doc_id, family, normalize_tokens(tokens, attested=attested)))
        token_documents[index] = []
    del token_documents

    rows = rank_terms(
        [lemmas for _, _, lemmas in documents], alpha=alpha, min_df=min_df
    )

    sources: list[SourceStats] = []
    if ranking_method == "borda":
        # Borda fusion needs at least two lists to balance. A single family is
        # an input error, not something to silently fall back from.
        sources = _source_stats(documents)
        if len(sources) < 2:
            found = ", ".join(source.name for source in sources) or "none"
            raise ValueError(
                "borda ranking requires at least two source families; "
                f"found {len(sources)} ({found}). Use --ranking-method pooled "
                "or provide documents with distinct 'source_family' values."
            )
        fused = borda_scores_percentile(
            [str(row["term"]) for row in rows], sources, min_df
        )
        ordered = sorted(
            rows, key=lambda row: (fused[str(row["term"])], str(row["term"]))
        )
        ranking = [
            {
                "term": row["term"],
                "tf": row["tf"],
                "df": row["df"],
                # The fused value, not se_specificity: sum of per-source
                # rank/listed counts, absence contributes 1.0. Lower is better.
                "se_specificity": round(
                    float(fused[str(row["term"])]), SCORE_DECIMALS
                ),
            }
            for row in ordered
        ]
    else:
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
        "sources": sorted({family for _, family, _ in documents}),
        "general_baseline": GENERAL_BASELINE,
        "documents": len(documents),
        "tokens": sum(len(lemmas) for _, _, lemmas in documents),
        "min_df": min_df,
        "attestation_min_documents": ATTESTATION_MIN_DOCUMENTS,
        "attested_forms": len(attested),
    }
    if ranking_method == "borda":
        # Pooled manifests stay exactly as before; the Borda manifest records
        # what the score column means and what each source contributed.
        manifest["ranking_method"] = "borda"
        manifest["borda_variant"] = BORDA_VARIANT
        manifest["score_semantics"] = (
            "sum over sources of rank/listed_count for listed terms and 1.0 "
            "for absent terms; lower is better (not se_specificity)"
        )
        manifest["per_source"] = [
            {
                "name": source.name,
                "documents": source.documents,
                "tokens": source.total_tokens,
                "listed": sum(1 for df in source.df.values() if df >= min_df),
            }
            for source in sources
        ]

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
        help="directory of .txt documents or a .jsonl document file",
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
    parser.add_argument(
        "--min-df",
        type=int,
        default=DEFAULT_MIN_DF,
        help=(
            "exclude terms occurring in fewer than N documents "
            f"(default: {DEFAULT_MIN_DF})"
        ),
    )
    parser.add_argument(
        "--ranking-method",
        choices=RANKING_METHODS,
        default="pooled",
        help=(
            "pooled scores the concatenated corpus (default); borda fuses "
            "per-source specificity rankings grouped by source_family"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.snapshot_id.strip():
        print("error: --snapshot-id must not be empty", file=sys.stderr)
        return 2
    if args.min_df < 1:
        print("error: --min-df must be at least 1", file=sys.stderr)
        return 2
    try:
        manifest = run(
            args.input,
            args.output,
            args.snapshot_id,
            alpha=args.alpha,
            min_df=args.min_df,
            ranking_method=args.ranking_method,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"snapshot:  {manifest['snapshot_id']}")
    print(f"documents: {manifest['documents']}")
    print(f"tokens:    {manifest['tokens']}")
    print(f"min_df:    {manifest['min_df']}")
    print(f"output:    {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
