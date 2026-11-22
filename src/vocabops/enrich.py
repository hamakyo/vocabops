"""GPU-ready POS tagging and dependency-based collocation enrichment.

This module upgrades VocabOps from dictionary-only lemmatization to POS-aware
lemmatization and syntactic collocation extraction using spaCy (for example
``en_core_web_trf`` on a Google Colab GPU, or ``en_core_web_sm`` on CPU).

Usage::

    # Fixture smoke run (CPU or GPU)
    python -m vocabops.enrich \\
        --input data/fixtures/sample_corpus \\
        --output out/enrich-fixture \\
        --snapshot-id human-se-v0.1-proto \\
        --model en_core_web_sm \\
        --min-collocation-count 1

    # Core 500 enrichment on a multi-source JSONL corpus (Colab GPU)
    python -m vocabops.enrich \\
        --input /content/drive/MyDrive/vocabops/documents.jsonl \\
        --terms data/core500-vocab-v3.jsonl \\
        --output /content/drive/MyDrive/vocabops/out/core500-enrich-v1 \\
        --snapshot-id core500-enrich-v1 \\
        --model en_core_web_trf \\
        --device auto \\
        --min-df 3

Outputs written to ``--output``:

- ``enrichment.jsonl`` — one deterministic JSON object per ``(lemma, pos)``
  record (``id``, ``lemma``, ``pos``, ``tf``, ``df``, ``pos_share``,
  ``forms``, ``collocations``, ``by_source``), sorted by ``df`` desc,
  ``tf`` desc, ``id`` asc.
- ``manifest.json`` — snapshot metadata, pinned spaCy/model versions, device
  selection, filter thresholds, and counts. No timestamps are emitted so
  repeated runs on the same inputs are byte-identical.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

from . import __version__
from .normalize import (
    STOPWORDS,
    _DIGIT_FIRST_SHARD_RE,
    _FENCED_CODE_RE,
    _HTML_TAG_RE,
    _INLINE_CODE_RE,
    _ISO_DATE_RE,
    _ISO_DATETIME_RE,
    _MEASUREMENT_RE,
    _URL_RE,
)
from .pipeline import SOURCE_FAMILY, _read_jsonl_documents, _read_txt_documents

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MIN_DF",
    "DEFAULT_MIN_COLLOCATION_COUNT",
    "DEFAULT_MAX_COLLOCATIONS",
    "DEFAULT_MAX_FORMS",
    "DEVICES",
    "UPOS_TO_SCHEMA_POS",
    "POS_ID_SUFFIX",
    "MEANINGFUL_PREPOSITIONS",
    "clean_text_for_nlp",
    "load_target_terms",
    "record_id",
    "extract_enrichment",
    "load_spacy_model",
    "run",
    "main",
]

DEFAULT_MODEL = "en_core_web_trf"
DEFAULT_BATCH_SIZE = 64
DEFAULT_MIN_DF = 1
DEFAULT_MIN_COLLOCATION_COUNT = 2
DEFAULT_MAX_COLLOCATIONS = 8
DEFAULT_MAX_FORMS = 8
DEVICES = ("auto", "gpu", "cpu")

# Map Universal POS tags (spaCy ``token.pos_``) to the VocabOps data schema
# defined in ``docs/data-schema.md``.
UPOS_TO_SCHEMA_POS: dict[str, str] = {
    "NOUN": "noun",
    "PROPN": "noun",
    "VERB": "verb",
    "ADJ": "adjective",
    "ADV": "adverb",
}

# Stable ID suffixes matching ``docs/data-schema.md`` and ``data/sample.json``.
POS_ID_SUFFIX: dict[str, str] = {
    "noun": "n",
    "verb": "v",
    "adjective": "adjective",
    "adverb": "adv",
    "phrase": "phrase",
    "other": "other",
}

# Prepositions that carry meaningful software-engineering argument structure
# in ``verb + prep + pobj`` collocations (e.g. ``propagate to caller``,
# ``retrieve from cache``).
MEANINGFUL_PREPOSITIONS: frozenset[str] = frozenset(
    {
        "against",
        "by",
        "for",
        "from",
        "in",
        "into",
        "on",
        "onto",
        "over",
        "through",
        "to",
        "via",
        "with",
    }
)

_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")
_VALID_WORD_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class TokenLike(Protocol):
    """Minimal subset of spaCy ``Token`` needed for enrichment."""

    text: str
    lemma_: str
    pos_: str
    dep_: str
    is_space: bool
    is_punct: bool
    head: Any
    children: Iterable[Any]


class DocLike(Protocol):
    """Minimal subset of spaCy ``Doc`` needed for enrichment."""

    def __iter__(self) -> Iterator[TokenLike]: ...


def clean_text_for_nlp(text: str) -> str:
    """Remove code/markup/URLs/timestamps while preserving case and syntax.

    Unlike :func:`vocabops.normalize.clean_text`, original casing and sentence
    punctuation are preserved so Transformer POS taggers and dependency parsers
    keep accurate sentence boundaries and proper-noun cues.
    """
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _ISO_DATETIME_RE.sub(" ", text)
    text = _ISO_DATE_RE.sub(" ", text)
    text = _MARKDOWN_HEADING_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


def record_id(lemma: str, schema_pos: str) -> str:
    """Build a VocabOps stable record ID (``<lemma>.<pos_suffix>``)."""
    suffix = POS_ID_SUFFIX.get(schema_pos, "other")
    return f"{lemma}.{suffix}"


def _clean_lemma(raw: str) -> str | None:
    """Normalize a spaCy lemma/surface string and reject noise artifacts."""
    cleaned = raw.strip().strip("-_").lower()
    if len(cleaned) < 2:
        return None
    if "_" in cleaned:
        return None
    if not any(ch.isalpha() for ch in cleaned):
        return None
    if _MEASUREMENT_RE.match(cleaned) or _DIGIT_FIRST_SHARD_RE.match(cleaned):
        return None
    if not _VALID_WORD_RE.match(cleaned):
        return None
    if cleaned in STOPWORDS:
        return None
    return cleaned


def _token_lemma_and_pos(token: TokenLike) -> tuple[str, str] | None:
    """Return ``(lemma, schema_pos)`` for a content token, or ``None``."""
    if token.is_space or token.is_punct:
        return None
    schema_pos = UPOS_TO_SCHEMA_POS.get(token.pos_)
    if schema_pos is None:
        return None
    # Keep "underlying" intact when tagged as an adjective (matches normalize.py
    # and the VocabOps target vocabulary).
    surface = token.text.strip().lower()
    if surface == "underlying" and schema_pos == "adjective":
        lemma = "underlying"
    else:
        lemma = _clean_lemma(token.lemma_ or token.text)
    if lemma is None:
        return None
    return lemma, schema_pos


def _clean_surface(token: TokenLike) -> str | None:
    """Return a clean lowercase surface form for ``forms`` tracking."""
    surface = token.text.strip().strip("-_").lower()
    if len(surface) < 2 or not _VALID_WORD_RE.match(surface):
        return None
    return surface


def load_target_terms(path: Path) -> frozenset[str]:
    """Load target lemmas from a JSONL file (``term``/``lemma``) or text file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"terms file not found: {path}")

    terms: set[str] = set()
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{path}:{line_number}: invalid JSON: {exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected JSON object")
                value = row.get("lemma") or row.get("term")
                if isinstance(value, str) and value.strip():
                    terms.add(value.strip().lower())
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            terms.add(stripped.lower())

    if not terms:
        raise ValueError(f"no terms found in {path}")
    return frozenset(terms)


def _iter_doc_collocations(
    doc: DocLike,
) -> Iterator[tuple[tuple[str, str], str, str]]:
    """Yield ``((lemma, schema_pos), phrase, pattern)`` observations in a doc."""
    for token in doc:
        parsed = _token_lemma_and_pos(token)
        if parsed is None:
            continue
        lemma, schema_pos = parsed

        # 1. Verb + direct object / passive subject -> "<verb> <noun>"
        if schema_pos == "verb":
            for child in token.children:
                child_dep = child.dep_
                if child_dep in ("dobj", "obj", "nsubjpass"):
                    obj = _token_lemma_and_pos(child)
                    if obj is not None and obj[1] == "noun":
                        phrase = f"{lemma} {obj[0]}"
                        yield (lemma, "verb"), phrase, "verb_obj"
                        yield (obj[0], "noun"), phrase, "verb_obj"
                elif child_dep == "prep":
                    prep_text = child.text.strip().lower()
                    if prep_text in MEANINGFUL_PREPOSITIONS:
                        for grand in child.children:
                            if grand.dep_ == "pobj":
                                pobj = _token_lemma_and_pos(grand)
                                if pobj is not None and pobj[1] == "noun":
                                    phrase = f"{lemma} {prep_text} {pobj[0]}"
                                    yield (lemma, "verb"), phrase, "verb_prep_obj"
                                    yield (pobj[0], "noun"), phrase, "verb_prep_obj"
                elif child_dep == "advmod":
                    adv = _token_lemma_and_pos(child)
                    if adv is not None and adv[1] == "adverb":
                        phrase = f"{lemma} {adv[0]}"
                        yield (lemma, "verb"), phrase, "verb_adv"
                        yield (adv[0], "adverb"), phrase, "verb_adv"

        # 2. Adjective + Noun ("amod") -> "<adj> <noun>"
        elif schema_pos == "adjective" and token.dep_ == "amod":
            head_parsed = _token_lemma_and_pos(token.head)
            if head_parsed is not None and head_parsed[1] == "noun":
                phrase = f"{lemma} {head_parsed[0]}"
                yield (lemma, "adjective"), phrase, "adj_noun"
                yield (head_parsed[0], "noun"), phrase, "adj_noun"

        # 3. Noun + Noun compound ("compound") -> "<mod_noun> <head_noun>"
        elif schema_pos == "noun" and token.dep_ == "compound":
            head_parsed = _token_lemma_and_pos(token.head)
            if (
                head_parsed is not None
                and head_parsed[1] == "noun"
                and head_parsed[0] != lemma
            ):
                phrase = f"{lemma} {head_parsed[0]}"
                yield (lemma, "noun"), phrase, "noun_compound"
                yield (head_parsed[0], "noun"), phrase, "noun_compound"


def extract_enrichment(
    source_families: Sequence[str],
    docs: Iterable[DocLike],
    *,
    target_terms: frozenset[str] | None = None,
    min_df: int = DEFAULT_MIN_DF,
    min_collocation_count: int = DEFAULT_MIN_COLLOCATION_COUNT,
    max_collocations: int = DEFAULT_MAX_COLLOCATIONS,
    max_forms: int = DEFAULT_MAX_FORMS,
) -> list[dict[str, object]]:
    """Aggregate POS-aware counts, surface forms, and collocations from docs.

    ``source_families`` must align positionally with ``docs``. Output ordering
    is completely deterministic (``df`` desc, ``tf`` desc, ``id`` asc).
    """
    tf_by_key: Counter[tuple[str, str]] = Counter()
    df_by_key: Counter[tuple[str, str]] = Counter()
    lemma_total_tf: Counter[str] = Counter()
    source_tf: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    source_df: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    forms_by_key: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    # Collocation counts per (lemma, pos) -> Counter[(phrase, pattern)]
    colloc_tf: dict[tuple[str, str], Counter[tuple[str, str]]] = defaultdict(Counter)
    colloc_df: dict[tuple[str, str], Counter[tuple[str, str]]] = defaultdict(Counter)

    doc_count = 0
    for family, doc in zip(source_families, docs, strict=True):
        doc_count += 1
        seen_keys: set[tuple[str, str]] = set()
        seen_collocs: set[tuple[tuple[str, str], str, str]] = set()

        for token in doc:
            parsed = _token_lemma_and_pos(token)
            if parsed is None:
                continue
            lemma, schema_pos = parsed
            key = (lemma, schema_pos)

            tf_by_key[key] += 1
            lemma_total_tf[lemma] += 1
            source_tf[key][family] += 1
            seen_keys.add(key)

            surface = _clean_surface(token)
            if surface is not None and surface != lemma:
                forms_by_key[key][surface] += 1

        for key in seen_keys:
            df_by_key[key] += 1
            source_df[key][family] += 1

        for key, phrase, pattern in _iter_doc_collocations(doc):
            if target_terms is not None and key[0] not in target_terms:
                continue
            pair = (phrase, pattern)
            colloc_tf[key][pair] += 1
            seen_collocs.add((key, phrase, pattern))

        for key, phrase, pattern in seen_collocs:
            colloc_df[key][(phrase, pattern)] += 1

    if doc_count == 0:
        return []

    rows: list[dict[str, object]] = []
    for key, tf in tf_by_key.items():
        lemma, schema_pos = key
        if target_terms is not None and lemma not in target_terms:
            continue
        df = df_by_key[key]
        if df < min_df:
            continue

        total_for_lemma = lemma_total_tf[lemma]
        pos_share = round(tf / total_for_lemma, 4) if total_for_lemma else 0.0

        sorted_forms = [
            form
            for form, _count in sorted(
                forms_by_key[key].items(),
                key=lambda item: (-item[1], item[0]),
            )[:max_forms]
        ]

        sorted_collocs = [
            {
                "phrase": phrase,
                "pattern": pattern,
                "count": count,
                "df": colloc_df[key][(phrase, pattern)],
            }
            for (phrase, pattern), count in sorted(
                colloc_tf[key].items(),
                key=lambda item: (
                    -colloc_df[key][item[0]],
                    -item[1],
                    item[0][0],
                    item[0][1],
                ),
            )
            if count >= min_collocation_count
        ][:max_collocations]

        by_source = {
            src: {"tf": source_tf[key][src], "df": source_df[key][src]}
            for src in sorted(source_tf[key].keys())
        }

        rows.append(
            {
                "id": record_id(lemma, schema_pos),
                "lemma": lemma,
                "pos": schema_pos,
                "tf": tf,
                "df": df,
                "pos_share": pos_share,
                "forms": sorted_forms,
                "collocations": sorted_collocs,
                "by_source": by_source,
            }
        )

    rows.sort(key=lambda row: (-int(row["df"]), -int(row["tf"]), str(row["id"])))
    return rows


def load_spacy_model(
    model_name: str = DEFAULT_MODEL,
    *,
    device: str = "auto",
) -> tuple[Any, dict[str, str]]:
    """Lazily import spaCy, configure GPU/CPU device, and load ``model_name``.

    Disables ``ner`` to accelerate POS tagging and dependency parsing on GPU.
    """
    if device not in DEVICES:
        raise ValueError(f"unsupported device {device!r}; expected one of {DEVICES}")

    try:
        import spacy
    except ImportError as exc:
        raise RuntimeError(
            "spaCy is required for vocabops.enrich. Install the optional extra:\n"
            '  pip install -e ".[nlp]"        # CPU / en_core_web_sm\n'
            '  pip install -e ".[colab]"      # GPU / en_core_web_trf'
        ) from exc

    device_used = "cpu"
    if device == "gpu":
        spacy.require_gpu()
        device_used = "gpu"
    elif device == "auto":
        if spacy.prefer_gpu():
            device_used = "gpu"

    try:
        nlp = spacy.load(model_name, exclude=["ner"])
    except OSError as exc:
        raise RuntimeError(
            f"spaCy model {model_name!r} is not installed. Download it first:\n"
            f"  python -m spacy download {model_name}"
        ) from exc

    meta = {
        "model": model_name,
        "model_version": str(nlp.meta.get("version", "unknown")),
        "spacy_version": str(getattr(spacy, "__version__", "unknown")),
        "device_requested": device,
        "device_used": device_used,
    }
    return nlp, meta


def _read_raw_documents(input_path: Path) -> tuple[list[str], list[str]]:
    """Return parallel ``(source_families, cleaned_texts)`` lists in fixed order."""
    input_path = Path(input_path)
    if input_path.is_dir():
        raw_docs = _read_txt_documents(input_path, SOURCE_FAMILY)
        if not raw_docs:
            raise ValueError(f"no .txt documents found in {input_path}")
        families = [SOURCE_FAMILY for _ in raw_docs]
        texts = [clean_text_for_nlp(text) for _id, _rel, text in raw_docs]
        return families, texts

    if input_path.is_file():
        raw_docs = _read_jsonl_documents(input_path)
        if not raw_docs:
            raise ValueError(f"no documents found in {input_path}")
        families = [family for _id, family, _text in raw_docs]
        texts = [clean_text_for_nlp(text) for _id, _family, text in raw_docs]
        return families, texts

    raise FileNotFoundError(f"input path does not exist: {input_path}")


def run(
    input_path: Path,
    output_dir: Path,
    snapshot_id: str,
    *,
    terms_path: Path | None = None,
    model_name: str = DEFAULT_MODEL,
    device: str = "auto",
    batch_size: int = DEFAULT_BATCH_SIZE,
    min_df: int = DEFAULT_MIN_DF,
    min_collocation_count: int = DEFAULT_MIN_COLLOCATION_COUNT,
    max_collocations: int = DEFAULT_MAX_COLLOCATIONS,
    max_forms: int = DEFAULT_MAX_FORMS,
    nlp: Any | None = None,
    model_meta: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run POS + collocation enrichment and write deterministic outputs."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if not snapshot_id.strip():
        raise ValueError("snapshot_id must not be empty")
    if min_df < 1:
        raise ValueError(f"min_df must be at least 1, got {min_df}")
    if min_collocation_count < 1:
        raise ValueError(
            f"min_collocation_count must be at least 1, got {min_collocation_count}"
        )
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, got {batch_size}")

    target_terms = load_target_terms(terms_path) if terms_path is not None else None
    source_families, texts = _read_raw_documents(input_path)

    if nlp is None:
        nlp, resolved_meta = load_spacy_model(model_name, device=device)
    else:
        resolved_meta = model_meta or {
            "model": model_name,
            "model_version": "custom",
            "spacy_version": "custom",
            "device_requested": device,
            "device_used": "cpu",
        }

    docs = nlp.pipe(texts, batch_size=batch_size)
    rows = extract_enrichment(
        source_families,
        docs,
        target_terms=target_terms,
        min_df=min_df,
        min_collocation_count=min_collocation_count,
        max_collocations=max_collocations,
        max_forms=max_forms,
    )

    manifest: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "pipeline_version": __version__,
        "stage": "pos_collocations",
        "model": resolved_meta["model"],
        "model_version": resolved_meta["model_version"],
        "spacy_version": resolved_meta["spacy_version"],
        "device_requested": resolved_meta["device_requested"],
        "device_used": resolved_meta["device_used"],
        "documents": len(texts),
        "sources": sorted(set(source_families)),
        "terms_filter_count": len(target_terms) if target_terms is not None else None,
        "min_df": min_df,
        "min_collocation_count": min_collocation_count,
        "max_collocations": max_collocations,
        "max_forms": max_forms,
        "emitted_entries": len(rows),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "enrichment.jsonl", rows)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vocabops.enrich",
        description=(
            "Run POS-aware lemmatization and dependency-based collocation "
            "extraction using spaCy (GPU-ready for Google Colab)."
        ),
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
        help="output directory for enrichment.jsonl and manifest.json",
    )
    parser.add_argument(
        "--snapshot-id",
        required=True,
        help="fixed snapshot identifier recorded in manifest.json",
    )
    parser.add_argument(
        "--terms",
        type=Path,
        default=None,
        help=(
            "optional JSONL (with 'term'/'lemma') or newline-separated text "
            "file restricting output to target lemmas (e.g. data/core500-vocab-v3.jsonl)"
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"spaCy model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--device",
        choices=DEVICES,
        default="auto",
        help="compute device: auto (prefer GPU), gpu (require GPU), or cpu",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"spaCy nlp.pipe batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--min-df",
        type=int,
        default=DEFAULT_MIN_DF,
        help=f"minimum document frequency for emitted entries (default: {DEFAULT_MIN_DF})",
    )
    parser.add_argument(
        "--min-collocation-count",
        type=int,
        default=DEFAULT_MIN_COLLOCATION_COUNT,
        help=(
            "minimum occurrence count for a collocation to be kept "
            f"(default: {DEFAULT_MIN_COLLOCATION_COUNT})"
        ),
    )
    parser.add_argument(
        "--max-collocations",
        type=int,
        default=DEFAULT_MAX_COLLOCATIONS,
        help=f"maximum collocations per (lemma, pos) entry (default: {DEFAULT_MAX_COLLOCATIONS})",
    )
    parser.add_argument(
        "--max-forms",
        type=int,
        default=DEFAULT_MAX_FORMS,
        help=f"maximum surface forms per (lemma, pos) entry (default: {DEFAULT_MAX_FORMS})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run(
            args.input,
            args.output,
            args.snapshot_id,
            terms_path=args.terms,
            model_name=args.model,
            device=args.device,
            batch_size=args.batch_size,
            min_df=args.min_df,
            min_collocation_count=args.min_collocation_count,
            max_collocations=args.max_collocations,
            max_forms=args.max_forms,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"snapshot:        {manifest['snapshot_id']}")
    print(f"model:           {manifest['model']} ({manifest['model_version']})")
    print(f"device:          {manifest['device_used']}")
    print(f"documents:       {manifest['documents']}")
    print(f"emitted_entries: {manifest['emitted_entries']}")
    print(f"output:          {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
