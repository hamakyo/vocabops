"""GPU open-model batch draft curation for VocabOps vocabulary records.

Consumes POS + collocation enrichment JSONL (from ``python -m vocabops.enrich``)
and generates structured, unreviewed draft vocabulary records aligned with
``docs/data-schema.md``:

- Japanese general gloss (``ja.gloss``) and software-engineering gloss
  (``ja.software_gloss``)
- CEFR estimate (``A1``..``C2`` or ``null``)
- Allowlisted taxonomy ``categories`` (never assigns ``llm-native`` labels)
- One synthetic software-engineering example sentence (EN + JA) grounded in
  corpus-derived collocations, plus a deterministically derived cloze card

Every generated record is explicitly tagged with ``examples[].kind = "synthetic"``
and ``curation.status = "draft"`` / ``needs_human_review = true`` so unreviewed
drafts stay cleanly separated from human-curated releases.

Usage::

    python -m vocabops.draft_curation \\
        --enrichment data/core500-vocab-v3-enrichment.jsonl \\
        --ranking data/core500-vocab-v3.jsonl \\
        --output out/core500-draft-v1 \\
        --snapshot-id core500-draft-v1 \\
        --metric-snapshot combined-3source-enrich-v1 \\
        --model Qwen/Qwen2.5-7B-Instruct \\
        --batch-size 16
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import __version__

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_MIN_POS_SHARE",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_NEW_TOKENS",
    "ALLOWED_CATEGORIES",
    "VALID_CEFR",
    "select_entries",
    "build_prompt_messages",
    "parse_llm_json",
    "build_cloze",
    "assemble_draft_record",
    "TransformersBatchGenerator",
    "run",
    "main",
]

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_MIN_POS_SHARE = 0.25
DEFAULT_BATCH_SIZE = 16
DEFAULT_MAX_NEW_TOKENS = 256

# Allowlisted categories from ``docs/data-schema.md`` excluding
# ``llm-native-candidate`` / ``llm-native``, which must only be assigned from
# comparative corpus measurements (see AGENTS.md).
ALLOWED_CATEGORIES: tuple[str, ...] = (
    "core",
    "frontend",
    "backend",
    "database",
    "git",
    "cloud",
    "security",
    "testing",
    "documentation",
    "architecture",
    "ai",
    "agentic",
)
_ALLOWED_CATEGORY_SET = frozenset(ALLOWED_CATEGORIES)

VALID_CEFR: frozenset[str] = frozenset({"A1", "A2", "B1", "B2", "C1", "C2"})

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

_SYSTEM_PROMPT = (
    "You are a lexicographer creating concise English-to-Japanese vocabulary "
    "study cards for software engineers. Return ONLY a single valid JSON object "
    "with no extra prose or markdown.\n"
    "Required JSON keys:\n"
    '- "gloss": concise general Japanese meaning (string, 2-15 chars)\n'
    '- "software_gloss": concise Japanese meaning in software engineering '
    "context (string, 5-35 chars)\n"
    '- "cefr": one of "A1","A2","B1","B2","C1","C2", or null if purely '
    "technical jargon/abbreviation\n"
    '- "categories": 1 to 3 strings chosen ONLY from: '
    "core, frontend, backend, database, git, cloud, security, testing, "
    "documentation, architecture, ai, agentic\n"
    '- "example_en": one natural, realistic software-engineering English '
    "sentence (10-22 words) that uses the target word (or one of its inflected "
    "forms) in the requested part of speech, ideally incorporating one of the "
    "provided corpus collocations\n"
    '- "example_ja": natural Japanese translation of example_en\n'
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(obj)
    return rows


def select_entries(
    enrichment_rows: Sequence[dict[str, Any]],
    *,
    min_pos_share: float = DEFAULT_MIN_POS_SHARE,
    ranking_order: dict[str, int] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Keep each lemma's primary POS plus secondary POS with ``pos_share >= min_pos_share``.

    Deterministic ordering: when ``ranking_order`` (lemma -> rank) is supplied,
    sorts by rank ascending, then ``pos_share`` descending, then ``id``
    ascending; otherwise by ``df`` descending, ``tf`` descending, ``id``
    ascending.
    """
    by_lemma: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enrichment_rows:
        by_lemma[str(row["lemma"])].append(row)

    selected: list[dict[str, Any]] = []
    for _lemma, group in sorted(by_lemma.items()):
        ordered = sorted(
            group,
            key=lambda r: (
                -float(r.get("pos_share", 0.0)),
                -int(r.get("df", 0)),
                str(r["id"]),
            ),
        )
        for idx, row in enumerate(ordered):
            if idx == 0 or float(row.get("pos_share", 0.0)) >= min_pos_share:
                selected.append(row)

    if ranking_order is not None:
        fallback_rank = len(ranking_order) + 10**6
        selected.sort(
            key=lambda r: (
                ranking_order.get(str(r["lemma"]), fallback_rank),
                -float(r.get("pos_share", 0.0)),
                str(r["id"]),
            )
        )
    else:
        selected.sort(
            key=lambda r: (
                -int(r.get("df", 0)),
                -int(r.get("tf", 0)),
                str(r["id"]),
            )
        )

    if limit is not None:
        selected = selected[:limit]
    return selected


def build_prompt_messages(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Build chat messages for drafting a single ``(lemma, pos)`` entry."""
    lemma = str(entry["lemma"])
    pos = str(entry["pos"])
    forms = [str(f) for f in entry.get("forms", [])[:6]]
    collocs = [str(c["phrase"]) for c in entry.get("collocations", [])[:5]]

    user_lines = [
        f"Target word (lemma): {lemma}",
        f"Part of speech: {pos}",
    ]
    if forms:
        user_lines.append(f"Observed forms: {', '.join(forms)}")
    if collocs:
        user_lines.append(f"Top corpus collocations: {', '.join(collocs)}")
    user_lines.append("Output the JSON object now.")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def parse_llm_json(raw_text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from model output, or ``None`` if invalid."""
    text = raw_text.strip()
    if not text:
        return None

    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def build_cloze(
    example_en: str,
    lemma: str,
    forms: Sequence[str],
) -> dict[str, str] | None:
    """Deterministically mask the first occurrence of ``lemma`` or its ``forms``."""
    if not example_en.strip():
        return None
    candidates = sorted(
        {c.strip().lower() for c in [lemma, *forms] if c and c.strip()},
        key=lambda s: (-len(s), s),
    )
    if not candidates:
        return None
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(c) for c in candidates) + r")\b",
        re.IGNORECASE,
    )
    match = pattern.search(example_en)
    if match is None:
        return None
    answer = match.group(1)
    prompt = example_en[: match.start()] + "____" + example_en[match.end() :]
    return {"prompt": prompt, "answer": answer}


def _clean_str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def assemble_draft_record(
    entry: dict[str, Any],
    raw_output: str,
    *,
    model_name: str,
    dataset_version: str,
    metric_snapshot: str,
    tier: str = "core",
) -> dict[str, Any]:
    """Combine enrichment measurements and parsed LLM draft into schema format."""
    lemma = str(entry["lemma"])
    pos = str(entry["pos"])
    forms = [str(f) for f in entry.get("forms", [])]
    collocations = [str(c["phrase"]) for c in entry.get("collocations", [])[:5]]
    by_source = entry.get("by_source", {})

    warnings: list[str] = []
    parsed = parse_llm_json(raw_output)
    if parsed is None:
        warnings.append("json_parse_failed")
        parsed = {}

    gloss = _clean_str(parsed.get("gloss"))
    software_gloss = _clean_str(parsed.get("software_gloss"))
    if not gloss:
        warnings.append("missing_gloss")
    if not software_gloss:
        warnings.append("missing_software_gloss")

    raw_cefr = parsed.get("cefr")
    cefr: str | None = None
    if isinstance(raw_cefr, str):
        upper = raw_cefr.strip().upper()
        if upper in VALID_CEFR:
            cefr = upper

    raw_cats = parsed.get("categories")
    categories: list[str] = []
    if isinstance(raw_cats, list):
        for cat in raw_cats:
            if isinstance(cat, str):
                norm = cat.strip().lower()
                if norm in _ALLOWED_CATEGORY_SET and norm not in categories:
                    categories.append(norm)
    if not categories:
        categories = ["core"]

    example_en = _clean_str(parsed.get("example_en"))
    example_ja = _clean_str(parsed.get("example_ja"))
    examples: list[dict[str, str]] = []
    cloze: dict[str, str] | None = None

    if example_en:
        ex_obj: dict[str, str] = {"text": example_en, "kind": "synthetic"}
        if example_ja:
            ex_obj["ja"] = example_ja
        else:
            warnings.append("missing_example_ja")
        examples.append(ex_obj)
        cloze = build_cloze(example_en, lemma, forms)
        if cloze is None:
            warnings.append("example_missing_target_term")
    else:
        warnings.append("missing_example_en")

    freq_github = int(by_source.get("gharchive", {}).get("tf", 0))
    freq_so = int(by_source.get("stackoverflow", {}).get("tf", 0))
    freq_docs = int(by_source.get("codesearchnet", {}).get("tf", 0))
    contributing_sources = sorted(str(k) for k in by_source.keys())

    return {
        "id": str(entry["id"]),
        "term": lemma,
        "lemma": lemma,
        "pos": pos,
        "ja": {
            "gloss": gloss,
            "software_gloss": software_gloss,
        },
        "cefr": cefr,
        "categories": categories,
        "forms": forms,
        "collocations": collocations,
        "examples": examples,
        "cloze": cloze,
        "metrics": {
            "frequency": {
                "github": freq_github,
                "stackoverflow": freq_so,
                "docs": freq_docs,
                "llm": None,
            },
            "document_frequency": int(entry.get("df", 0)),
            "se_specificity": None,
            "llm_lift": None,
            "model_lift": {
                "claude": None,
                "gpt": None,
                "gemini": None,
            },
        },
        "learning": {
            "tier": tier,
            "priority": None,
        },
        "provenance": {
            "dataset_version": dataset_version,
            "metric_snapshot": metric_snapshot,
            "sources": contributing_sources,
        },
        "curation": {
            "status": "draft",
            "model": model_name,
            "needs_human_review": True,
            "validation_warnings": warnings,
        },
    }


class TransformersBatchGenerator:
    """Greedy batched Hugging Face ``transformers`` text generator for Colab GPU."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    ) -> None:
        try:
            import torch
            import transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "transformers and torch are required for GPU draft curation. "
                'Install with: pip install -e ".[draft]"'
            ) from exc

        self._torch = torch
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto",
        )
        self.model.eval()
        # Clear sampling defaults so greedy decoding emits no warnings.
        gen_cfg = self.model.generation_config
        gen_cfg.do_sample = False
        for attr in ("temperature", "top_p", "top_k"):
            if hasattr(gen_cfg, attr):
                setattr(gen_cfg, attr, None)

        self.meta: dict[str, str] = {
            "model": model_name,
            "model_revision": str(
                getattr(self.model.config, "_commit_hash", "unknown") or "unknown"
            ),
            "transformers_version": str(getattr(transformers, "__version__", "unknown")),
            "torch_version": str(getattr(torch, "__version__", "unknown")),
            "device": str(self.model.device),
        }

    def generate_batch(
        self, batch_messages: Sequence[list[dict[str, str]]]
    ) -> list[str]:
        prompts = [
            self.tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True
            )
            for msgs in batch_messages
        ]
        inputs = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
        ).to(self.model.device)
        prompt_len = inputs["input_ids"].shape[1]

        with self._torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
            )

        generated_tokens = outputs[:, prompt_len:]
        return self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)


def run(
    enrichment_path: Path,
    output_dir: Path,
    snapshot_id: str,
    *,
    ranking_path: Path | None = None,
    metric_snapshot: str = "combined-3source-enrich-v1",
    dataset_version: str = "0.1.0-draft",
    model_name: str = DEFAULT_MODEL,
    min_pos_share: float = DEFAULT_MIN_POS_SHARE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    limit: int | None = None,
    generator: Callable[[Sequence[list[dict[str, str]]]], list[str]] | None = None,
    generator_meta: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run batch draft curation and write deterministic JSONL + manifest."""
    if not snapshot_id.strip():
        raise ValueError("snapshot_id must not be empty")
    if not (0.0 <= min_pos_share <= 1.0):
        raise ValueError(f"min_pos_share must be in [0, 1], got {min_pos_share}")
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, got {batch_size}")

    enrichment_rows = _load_jsonl(enrichment_path)
    ranking_order: dict[str, int] | None = None
    if ranking_path is not None:
        ranking_rows = _load_jsonl(ranking_path)
        ranking_order = {
            str(r["term"]).strip().lower(): int(r.get("view_rank", idx + 1))
            for idx, r in enumerate(ranking_rows)
            if isinstance(r.get("term"), str)
        }

    entries = select_entries(
        enrichment_rows,
        min_pos_share=min_pos_share,
        ranking_order=ranking_order,
        limit=limit,
    )

    if generator is None:
        hf_gen = TransformersBatchGenerator(
            model_name, max_new_tokens=max_new_tokens
        )
        gen_fn: Callable[[Sequence[list[dict[str, str]]]], list[str]] = (
            hf_gen.generate_batch
        )
        resolved_meta = hf_gen.meta
    else:
        gen_fn = generator
        resolved_meta = generator_meta or {
            "model": model_name,
            "model_revision": "custom",
            "transformers_version": "custom",
            "torch_version": "custom",
            "device": "custom",
        }

    records: list[dict[str, Any]] = []
    total = len(entries)
    for start in range(0, total, batch_size):
        batch = entries[start : start + batch_size]
        batch_msgs = [build_prompt_messages(entry) for entry in batch]
        raw_outputs = gen_fn(batch_msgs)
        if len(raw_outputs) != len(batch):
            raise RuntimeError(
                f"generator returned {len(raw_outputs)} outputs for {len(batch)} inputs"
            )
        for entry, raw_out in zip(batch, raw_outputs, strict=True):
            records.append(
                assemble_draft_record(
                    entry,
                    raw_out,
                    model_name=resolved_meta["model"],
                    dataset_version=dataset_version,
                    metric_snapshot=metric_snapshot,
                )
            )
        print(
            f"[draft_curation] {min(start + batch_size, total)}/{total} entries drafted",
            flush=True,
        )

    warning_counts: dict[str, int] = {}
    clean_records = 0
    for rec in records:
        wlist = rec["curation"]["validation_warnings"]
        if not wlist:
            clean_records += 1
        for w in wlist:
            warning_counts[w] = warning_counts.get(w, 0) + 1

    manifest: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "pipeline_version": __version__,
        "stage": "draft_curation",
        "dataset_version": dataset_version,
        "metric_snapshot": metric_snapshot,
        "model": resolved_meta["model"],
        "model_revision": resolved_meta["model_revision"],
        "transformers_version": resolved_meta["transformers_version"],
        "torch_version": resolved_meta["torch_version"],
        "device": resolved_meta["device"],
        "decoding": "greedy",
        "min_pos_share": min_pos_share,
        "entries_drafted": len(records),
        "clean_records": clean_records,
        "warning_counts": dict(sorted(warning_counts.items())),
    }

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "drafts.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    with (output_dir / "manifest.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vocabops.draft_curation",
        description=(
            "Generate unreviewed draft Japanese glosses, software-context "
            "examples, categories, and cloze cards using an open GPU LLM."
        ),
    )
    parser.add_argument(
        "--enrichment",
        required=True,
        type=Path,
        help="enrichment JSONL file (e.g. data/core500-vocab-v3-enrichment.jsonl)",
    )
    parser.add_argument(
        "--ranking",
        type=Path,
        default=None,
        help="optional ranking JSONL for stable view_rank ordering (e.g. data/core500-vocab-v3.jsonl)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="output directory for drafts.jsonl and manifest.json",
    )
    parser.add_argument(
        "--snapshot-id",
        required=True,
        help="fixed snapshot identifier recorded in manifest.json",
    )
    parser.add_argument(
        "--metric-snapshot",
        default="combined-3source-enrich-v1",
        help="metric snapshot ID recorded in provenance.metric_snapshot",
    )
    parser.add_argument(
        "--dataset-version",
        default="0.1.0-draft",
        help="dataset version recorded in provenance.dataset_version",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Hugging Face causal LM name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--min-pos-share",
        type=float,
        default=DEFAULT_MIN_POS_SHARE,
        help=(
            "include secondary POS entries with pos_share >= threshold; "
            f"primary POS is always kept (default: {DEFAULT_MIN_POS_SHARE})"
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"generation batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=DEFAULT_MAX_NEW_TOKENS,
        help=f"maximum new tokens per entry (default: {DEFAULT_MAX_NEW_TOKENS})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="optional cap on number of entries (for smoke tests)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run(
            args.enrichment,
            args.output,
            args.snapshot_id,
            ranking_path=args.ranking,
            metric_snapshot=args.metric_snapshot,
            dataset_version=args.dataset_version,
            model_name=args.model,
            min_pos_share=args.min_pos_share,
            batch_size=args.batch_size,
            max_new_tokens=args.max_new_tokens,
            limit=args.limit,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"snapshot:        {manifest['snapshot_id']}")
    print(f"model:           {manifest['model']}")
    print(f"entries_drafted: {manifest['entries_drafted']}")
    print(f"clean_records:   {manifest['clean_records']}")
    print(f"warnings:        {manifest['warning_counts']}")
    print(f"output:          {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
