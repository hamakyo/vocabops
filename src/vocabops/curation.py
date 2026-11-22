"""Human curation workbench, override merger, and deterministic release exporter.

Bridges unreviewed GPU-generated drafts (``data/core500-vocab-v3-drafts.jsonl``)
to human-reviewed releases compliant with ``docs/data-schema.md`` and
``docs/release-policy.md``.

Subcommands::

    # 1. Export spreadsheet-friendly CSV + standalone interactive HTML workbench
    python -m vocabops.curation export-review \\
        --drafts data/core500-vocab-v3-drafts.jsonl \\
        --output out/core500-review

    # 2. Apply human overrides.json onto drafts deterministically
    python -m vocabops.curation apply-overrides \\
        --drafts data/core500-vocab-v3-drafts.jsonl \\
        --overrides path/to/overrides.json \\
        --output out/core500-curated

    # 3. Build a release bundle (vocabulary.json, vocabulary.csv, manifest.json, METHODOLOGY.md)
    python -m vocabops.curation build-release \\
        --input data/core500-vocab-v3-drafts.jsonl \\
        --output data/releases/0.1.0-draft \\
        --dataset-version 0.1.0-draft \\
        --snapshot-id core500-draft-v1
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .draft_curation import ALLOWED_CATEGORIES, VALID_CEFR, build_cloze

__all__ = [
    "CSV_COLUMNS",
    "VALID_REVIEW_STATUSES",
    "load_records",
    "validate_record",
    "apply_overrides",
    "write_review_csv",
    "render_review_html",
    "export_review",
    "build_release",
    "main",
]

_ALLOWED_CATEGORY_SET = frozenset(ALLOWED_CATEGORIES)
VALID_REVIEW_STATUSES: frozenset[str] = frozenset({"draft", "reviewed", "flagged"})

CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "term",
    "lemma",
    "pos",
    "cefr",
    "categories",
    "gloss",
    "software_gloss",
    "forms",
    "collocations",
    "example_en",
    "example_ja",
    "example_kind",
    "cloze_prompt",
    "cloze_answer",
    "document_frequency",
    "freq_github",
    "freq_stackoverflow",
    "freq_docs",
    "curation_status",
    "needs_human_review",
    "validation_warnings",
    "review_note",
)


def _clean_str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load vocabulary records from either a JSONL file or a release JSON file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") and path.suffix.lower() == ".json":
        obj = json.loads(text)
        terms = obj.get("terms")
        if not isinstance(terms, list):
            raise ValueError(f"{path}: expected top-level 'terms' list")
        return [dict(t) for t in terms]

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(obj)
    return rows


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of schema/guardrail errors for a single record (empty if valid)."""
    errors: list[str] = []
    rid = record.get("id")
    if not isinstance(rid, str) or not rid.strip():
        errors.append("missing or invalid 'id'")
    for key in ("term", "lemma", "pos"):
        val = record.get(key)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"missing or invalid '{key}'")

    cefr = record.get("cefr")
    if cefr is not None and cefr not in VALID_CEFR:
        errors.append(f"invalid 'cefr': {cefr!r}")

    cats = record.get("categories")
    if not isinstance(cats, list) or not cats:
        errors.append("missing or empty 'categories'")
    else:
        for cat in cats:
            if cat in ("llm-native", "llm-native-candidate"):
                errors.append(f"forbidden unmeasured category: {cat!r}")
            elif cat not in _ALLOWED_CATEGORY_SET:
                errors.append(f"unknown category: {cat!r}")

    metrics = record.get("metrics", {})
    if isinstance(metrics, dict):
        if metrics.get("llm_lift") is not None:
            errors.append("metrics.llm_lift must remain null until measured")
        model_lift = metrics.get("model_lift", {})
        if isinstance(model_lift, dict):
            for k, v in model_lift.items():
                if v is not None:
                    errors.append(f"metrics.model_lift.{k} must remain null until measured")

    curation = record.get("curation", {})
    if isinstance(curation, dict):
        status = curation.get("status")
        if status is not None and status not in VALID_REVIEW_STATUSES:
            errors.append(f"invalid curation.status: {status!r}")
    return errors


def _recompute_warnings(record: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    ja = record.get("ja", {})
    if not _clean_str(ja.get("gloss")):
        warnings.append("missing_gloss")
    if not _clean_str(ja.get("software_gloss")):
        warnings.append("missing_software_gloss")

    examples = record.get("examples", [])
    if not examples:
        warnings.append("missing_example_en")
    else:
        ex0 = examples[0]
        if not _clean_str(ex0.get("text")):
            warnings.append("missing_example_en")
        else:
            if not _clean_str(ex0.get("ja")):
                warnings.append("missing_example_ja")
            if record.get("cloze") is None:
                warnings.append("example_missing_target_term")
    return warnings


def apply_overrides(
    records: Sequence[dict[str, Any]],
    overrides_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministically apply human review overrides while preserving corpus telemetry.

    ``overrides_payload`` may be either ``{"overrides": {<id>: {...}}}`` (exported
    by the HTML review workbench) or a plain mapping ``{<id>: {...}}``.
    """
    raw_map = overrides_payload.get("overrides", overrides_payload)
    if not isinstance(raw_map, dict):
        raise ValueError("overrides payload must be a JSON object")

    known_ids = {str(r["id"]) for r in records}
    unknown_ids = sorted(k for k in raw_map.keys() if k not in known_ids)
    if unknown_ids:
        raise ValueError(f"overrides reference unknown term IDs: {unknown_ids[:5]}")

    updated: list[dict[str, Any]] = []
    applied_count = 0
    edited_count = 0
    status_counts: Counter[str] = Counter()

    for orig in records:
        rec = copy.deepcopy(orig)
        rid = str(rec["id"])
        patch = raw_map.get(rid)
        if patch is not None:
            if not isinstance(patch, dict):
                raise ValueError(f"override for {rid!r} must be a JSON object")
            applied_count += 1
            human_edited = False

            if "gloss" in patch:
                new_gloss = _clean_str(patch["gloss"])
                if new_gloss != _clean_str(rec["ja"].get("gloss")):
                    rec["ja"]["gloss"] = new_gloss
                    human_edited = True
            if "software_gloss" in patch:
                new_sg = _clean_str(patch["software_gloss"])
                if new_sg != _clean_str(rec["ja"].get("software_gloss")):
                    rec["ja"]["software_gloss"] = new_sg
                    human_edited = True

            if "cefr" in patch:
                raw_cefr = patch["cefr"]
                if raw_cefr is None or raw_cefr == "":
                    new_cefr = None
                elif isinstance(raw_cefr, str) and raw_cefr.strip().upper() in VALID_CEFR:
                    new_cefr = raw_cefr.strip().upper()
                else:
                    raise ValueError(f"override for {rid!r} has invalid cefr: {raw_cefr!r}")
                if new_cefr != rec.get("cefr"):
                    rec["cefr"] = new_cefr
                    human_edited = True

            if "categories" in patch:
                raw_cats = patch["categories"]
                if not isinstance(raw_cats, list):
                    raise ValueError(f"override for {rid!r}: categories must be a list")
                cleaned_cats: list[str] = []
                for cat in raw_cats:
                    if not isinstance(cat, str):
                        raise ValueError(f"override for {rid!r}: invalid category {cat!r}")
                    norm = cat.strip().lower()
                    if norm not in _ALLOWED_CATEGORY_SET:
                        raise ValueError(
                            f"override for {rid!r}: disallowed category {cat!r}"
                        )
                    if norm not in cleaned_cats:
                        cleaned_cats.append(norm)
                if not cleaned_cats:
                    raise ValueError(f"override for {rid!r}: categories must not be empty")
                if cleaned_cats != rec.get("categories"):
                    rec["categories"] = cleaned_cats
                    human_edited = True

            ex_changed = False
            ex0 = rec["examples"][0] if rec.get("examples") else {"text": "", "kind": "synthetic", "ja": ""}
            new_en = _clean_str(patch["example_en"]) if "example_en" in patch else _clean_str(ex0.get("text"))
            new_ja = _clean_str(patch["example_ja"]) if "example_ja" in patch else _clean_str(ex0.get("ja"))
            if "example_en" in patch and new_en != _clean_str(ex0.get("text")):
                ex_changed = True
                human_edited = True
            if "example_ja" in patch and new_ja != _clean_str(ex0.get("ja")):
                ex_changed = True
                human_edited = True

            if ex_changed:
                if new_en:
                    ex_obj: dict[str, str] = {"text": new_en, "kind": "curated"}
                    if new_ja:
                        ex_obj["ja"] = new_ja
                    rec["examples"] = [ex_obj]
                    rec["cloze"] = build_cloze(new_en, str(rec["lemma"]), rec.get("forms", []))
                else:
                    rec["examples"] = []
                    rec["cloze"] = None

            curation = rec.setdefault("curation", {})
            raw_status = patch.get("status")
            if raw_status is not None:
                if raw_status not in VALID_REVIEW_STATUSES:
                    raise ValueError(f"override for {rid!r}: invalid status {raw_status!r}")
                curation["status"] = raw_status
            elif human_edited:
                curation["status"] = "reviewed"

            curation["needs_human_review"] = curation.get("status") != "reviewed"
            curation["human_edited"] = bool(curation.get("human_edited", False) or human_edited)
            if "review_note" in patch:
                note = _clean_str(patch["review_note"])
                if note:
                    curation["review_note"] = note
                else:
                    curation.pop("review_note", None)
            curation["validation_warnings"] = _recompute_warnings(rec)
            if human_edited:
                edited_count += 1

        errs = validate_record(rec)
        if errs:
            raise ValueError(f"record {rid!r} failed validation: {'; '.join(errs)}")
        status_counts[str(rec.get("curation", {}).get("status", "draft"))] += 1
        updated.append(rec)

    summary: dict[str, Any] = {
        "total_records": len(updated),
        "overrides_applied": applied_count,
        "human_edited": edited_count,
        "status_counts": dict(sorted(status_counts.items())),
        "clean_records": sum(
            1 for r in updated if not r.get("curation", {}).get("validation_warnings")
        ),
    }
    return updated, summary


def _record_to_csv_row(record: dict[str, Any]) -> dict[str, Any]:
    ja = record.get("ja", {})
    examples = record.get("examples", [])
    ex0 = examples[0] if examples else {}
    cloze = record.get("cloze") or {}
    metrics = record.get("metrics", {})
    freq = metrics.get("frequency", {})
    curation = record.get("curation", {})
    return {
        "id": record.get("id", ""),
        "term": record.get("term", ""),
        "lemma": record.get("lemma", ""),
        "pos": record.get("pos", ""),
        "cefr": record.get("cefr") or "",
        "categories": "|".join(record.get("categories", [])),
        "gloss": ja.get("gloss", ""),
        "software_gloss": ja.get("software_gloss", ""),
        "forms": "|".join(record.get("forms", [])),
        "collocations": "|".join(record.get("collocations", [])),
        "example_en": ex0.get("text", ""),
        "example_ja": ex0.get("ja", ""),
        "example_kind": ex0.get("kind", ""),
        "cloze_prompt": cloze.get("prompt", ""),
        "cloze_answer": cloze.get("answer", ""),
        "document_frequency": metrics.get("document_frequency", ""),
        "freq_github": freq.get("github", ""),
        "freq_stackoverflow": freq.get("stackoverflow", ""),
        "freq_docs": freq.get("docs", ""),
        "curation_status": curation.get("status", ""),
        "needs_human_review": str(bool(curation.get("needs_human_review", True))).lower(),
        "validation_warnings": "|".join(curation.get("validation_warnings", [])),
        "review_note": curation.get("review_note", ""),
    }


def write_review_csv(
    records: Sequence[dict[str, Any]],
    path: Path,
    *,
    utf8_bom: bool = False,
) -> None:
    """Write vocabulary records in deterministic order to a flat CSV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if utf8_bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for rec in records:
            writer.writerow(_record_to_csv_row(rec))


def render_review_html(
    records: Sequence[dict[str, Any]],
    *,
    title: str = "VocabOps Core 500 — Curation Workbench",
    storage_key: str = "vocabops-curation-v1",
) -> str:
    """Render a self-contained, zero-dependency HTML curation review workbench."""
    # Escape closing script tags defensively before embedding JSON into <script>.
    safe_records_json = json.dumps(
        list(records), ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    safe_cats_json = json.dumps(list(ALLOWED_CATEGORIES), ensure_ascii=False)
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    safe_storage_key = json.dumps(storage_key)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{safe_title}</title>
<style>
  :root {{
    --bg: #0f1117;
    --panel: #171a23;
    --panel-2: #1f2430;
    --border: #2c3345;
    --text: #e6e9f2;
    --muted: #98a2b8;
    --accent: #6ea8fe;
    --ok: #3dd68c;
    --warn: #f5b942;
    --flag: #ff6b6b;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f6f7fb;
      --panel: #ffffff;
      --panel-2: #f0f2f8;
      --border: #d8deea;
      --text: #1b2230;
      --muted: #5c667a;
      --accent: #2563eb;
      --ok: #15803d;
      --warn: #b45309;
      --flag: #dc2626;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  header {{
    position: sticky;
    top: 0;
    z-index: 10;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    padding: 12px 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
  }}
  header h1 {{
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }}
  .stats {{
    display: flex;
    gap: 10px;
    font-size: 12px;
    color: var(--muted);
    flex-wrap: wrap;
  }}
  .stats strong {{ color: var(--text); }}
  .toolbar {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px 16px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    align-items: center;
  }}
  input, select, textarea, button {{
    font: inherit;
    color: var(--text);
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 10px;
  }}
  button {{
    cursor: pointer;
    font-size: 13px;
  }}
  button:hover {{ border-color: var(--accent); }}
  button.primary {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}
  button.ok {{
    background: var(--ok);
    color: #0b1912;
    border-color: var(--ok);
    font-weight: 600;
  }}
  button.flag {{
    border-color: var(--flag);
    color: var(--flag);
  }}
  .layout {{
    display: grid;
    grid-template-columns: 320px 1fr;
    height: calc(100vh - 112px);
  }}
  @media (max-width: 860px) {{
    .layout {{
      grid-template-columns: 1fr;
      height: auto;
    }}
    .sidebar {{ max-height: 280px; }}
  }}
  .sidebar {{
    border-right: 1px solid var(--border);
    overflow-y: auto;
    background: var(--panel);
  }}
  .item {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }}
  .item:hover {{ background: var(--panel-2); }}
  .item.active {{
    background: var(--panel-2);
    border-left: 3px solid var(--accent);
  }}
  .item-title {{ font-weight: 600; font-size: 14px; }}
  .item-sub {{ font-size: 12px; color: var(--muted); }}
  .badges {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .badge {{
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 999px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    color: var(--muted);
  }}
  .badge.warn {{ border-color: var(--warn); color: var(--warn); }}
  .badge.ok {{ border-color: var(--ok); color: var(--ok); }}
  .badge.flag {{ border-color: var(--flag); color: var(--flag); }}
  .main {{
    padding: 18px 22px;
    overflow-y: auto;
    max-width: 880px;
  }}
  .card-head {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
  }}
  .card-head h2 {{ margin: 0; font-size: 24px; }}
  .telemetry {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 14px;
    font-size: 12px;
    color: var(--muted);
  }}
  .field {{ margin-bottom: 12px; }}
  .field label {{
    display: block;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 4px;
  }}
  .field input[type="text"], .field textarea {{ width: 100%; }}
  .row-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }}
  @media (max-width: 640px) {{ .row-2 {{ grid-template-columns: 1fr; }} }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{
    font-size: 12px;
    padding: 4px 8px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--panel-2);
    cursor: pointer;
    user-select: none;
  }}
  .chip.selected {{
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }}
  .cloze-box {{
    padding: 10px 12px;
    border-radius: 6px;
    background: var(--panel-2);
    border: 1px dashed var(--border);
    font-size: 13px;
  }}
  .actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }}
  .hint {{
    font-size: 11px;
    color: var(--muted);
    margin-top: 10px;
  }}
</style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <div class="stats" id="stats"></div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <button id="btn-import">Import overrides.json</button>
    <input id="file-import" type="file" accept=".json" style="display:none" />
    <button id="btn-export" class="primary">Export overrides.json</button>
  </div>
</header>

<div class="toolbar">
  <input id="search" type="search" placeholder="Search id, lemma, gloss, collocation (/) ..." style="min-width:240px;flex:1" />
  <select id="filter-status">
    <option value="all">All</option>
    <option value="needs-review">Needs review</option>
    <option value="warnings">Warnings only</option>
    <option value="reviewed">Approved / Edited</option>
    <option value="flagged">Flagged</option>
  </select>
  <select id="filter-pos">
    <option value="all">All POS</option>
    <option value="verb">verb</option>
    <option value="noun">noun</option>
    <option value="adjective">adjective</option>
    <option value="adverb">adverb</option>
  </select>
  <select id="filter-cat">
    <option value="all">All categories</option>
  </select>
</div>

<div class="layout">
  <div class="sidebar" id="list"></div>
  <div class="main" id="detail"></div>
</div>

<script>
const BASE_RECORDS = {safe_records_json};
const ALLOWED_CATEGORIES = {safe_cats_json};
const STORAGE_KEY = {safe_storage_key};

let overrides = {{}};
try {{
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) overrides = JSON.parse(saved);
}} catch (_) {{ overrides = {{}}; }}

let filtered = [];
let selectedId = BASE_RECORDS.length ? BASE_RECORDS[0].id : null;

const catFilter = document.getElementById("filter-cat");
ALLOWED_CATEGORIES.forEach(c => {{
  const opt = document.createElement("option");
  opt.value = c;
  opt.textContent = c;
  catFilter.appendChild(opt);
}});

function saveLocal() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides)); }} catch (_) {{}}
}}

function escapeRegex(s) {{
  return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
}}

function computeCloze(exampleEn, lemma, forms) {{
  if (!exampleEn || !exampleEn.trim()) return null;
  const set = new Set([lemma, ...(forms || [])].map(s => String(s || "").trim().toLowerCase()).filter(Boolean));
  const cands = Array.from(set).sort((a, b) => b.length - a.length || a.localeCompare(b));
  if (!cands.length) return null;
  const re = new RegExp("\\\\b(" + cands.map(escapeRegex).join("|") + ")\\\\b", "i");
  const m = re.exec(exampleEn);
  if (!m) return null;
  return {{
    prompt: exampleEn.slice(0, m.index) + "____" + exampleEn.slice(m.index + m[0].length),
    answer: m[1]
  }};
}}

function mergedRecord(base) {{
  const ov = overrides[base.id] || null;
  const ex0 = (base.examples && base.examples[0]) || {{ text: "", ja: "", kind: "synthetic" }};
  const gloss = ov && "gloss" in ov ? ov.gloss : (base.ja.gloss || "");
  const software_gloss = ov && "software_gloss" in ov ? ov.software_gloss : (base.ja.software_gloss || "");
  const cefr = ov && "cefr" in ov ? ov.cefr : base.cefr;
  const categories = ov && "categories" in ov ? ov.categories : base.categories;
  const example_en = ov && "example_en" in ov ? ov.example_en : (ex0.text || "");
  const example_ja = ov && "example_ja" in ov ? ov.example_ja : (ex0.ja || "");
  const status = (ov && ov.status) || (base.curation && base.curation.status) || "draft";
  const review_note = (ov && ov.review_note) || (base.curation && base.curation.review_note) || "";
  const cloze = computeCloze(example_en, base.lemma, base.forms);
  const warnings = [];
  if (!gloss.trim()) warnings.push("missing_gloss");
  if (!software_gloss.trim()) warnings.push("missing_software_gloss");
  if (!example_en.trim()) warnings.push("missing_example_en");
  else {{
    if (!example_ja.trim()) warnings.push("missing_example_ja");
    if (!cloze) warnings.push("example_missing_target_term");
  }}
  return {{
    base, ov, gloss, software_gloss, cefr, categories,
    example_en, example_ja, status, review_note, cloze, warnings
  }};
}}

function renderStats() {{
  let reviewed = 0, flagged = 0, warnings = 0;
  for (const r of BASE_RECORDS) {{
    const m = mergedRecord(r);
    if (m.status === "reviewed") reviewed++;
    if (m.status === "flagged") flagged++;
    if (m.warnings.length) warnings++;
  }}
  document.getElementById("stats").innerHTML =
    `<span>Total <strong>${{BASE_RECORDS.length}}</strong></span>` +
    `<span>Reviewed <strong>${{reviewed}}</strong></span>` +
    `<span>Flagged <strong>${{flagged}}</strong></span>` +
    `<span>Warnings <strong>${{warnings}}</strong></span>` +
    `<span>Overrides <strong>${{Object.keys(overrides).length}}</strong></span>`;
}}

function applyFilters() {{
  const q = document.getElementById("search").value.trim().toLowerCase();
  const st = document.getElementById("filter-status").value;
  const pos = document.getElementById("filter-pos").value;
  const cat = document.getElementById("filter-cat").value;

  filtered = BASE_RECORDS.filter(base => {{
    const m = mergedRecord(base);
    if (st === "needs-review" && m.status === "reviewed") return false;
    if (st === "warnings" && !m.warnings.length) return false;
    if (st === "reviewed" && m.status !== "reviewed") return false;
    if (st === "flagged" && m.status !== "flagged") return false;
    if (pos !== "all" && base.pos !== pos) return false;
    if (cat !== "all" && !m.categories.includes(cat)) return false;
    if (q) {{
      const hay = [
        base.id, base.lemma, m.gloss, m.software_gloss,
        (base.collocations || []).join(" "), m.example_en
      ].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  if (!filtered.some(r => r.id === selectedId)) {{
    selectedId = filtered.length ? filtered[0].id : null;
  }}
  renderStats();
  renderList();
  renderDetail();
}}

function renderList() {{
  const el = document.getElementById("list");
  el.innerHTML = "";
  const frag = document.createDocumentFragment();
  for (const base of filtered) {{
    const m = mergedRecord(base);
    const div = document.createElement("div");
    div.className = "item" + (base.id === selectedId ? " active" : "");
    div.onclick = () => {{ selectedId = base.id; renderList(); renderDetail(); }};
    const left = document.createElement("div");
    left.innerHTML = `<div class="item-title">${{base.id}}</div><div class="item-sub">${{m.gloss || "(empty)"}}</div>`;
    const badges = document.createElement("div");
    badges.className = "badges";
    if (m.status === "reviewed") badges.innerHTML += `<span class="badge ok">ok</span>`;
    if (m.status === "flagged") badges.innerHTML += `<span class="badge flag">flag</span>`;
    if (m.warnings.length) badges.innerHTML += `<span class="badge warn">!${{m.warnings.length}}</span>`;
    div.appendChild(left);
    div.appendChild(badges);
    frag.appendChild(div);
  }}
  el.appendChild(frag);
}}

function setOverride(id, patch) {{
  overrides[id] = Object.assign({{}}, overrides[id] || {{}}, patch);
  saveLocal();
  renderStats();
  renderList();
}}

function advance(delta) {{
  const idx = filtered.findIndex(r => r.id === selectedId);
  if (idx === -1) return;
  const next = idx + delta;
  if (next >= 0 && next < filtered.length) {{
    selectedId = filtered[next].id;
    renderList();
    renderDetail();
  }}
}}

function renderDetail() {{
  const el = document.getElementById("detail");
  const base = BASE_RECORDS.find(r => r.id === selectedId);
  if (!base) {{
    el.innerHTML = "<p>No matching records.</p>";
    return;
  }}
  const m = mergedRecord(base);
  const freq = (base.metrics && base.metrics.frequency) || {{}};

  el.innerHTML = `
    <div class="card-head">
      <h2>${{base.term}} <span class="badge">${{base.pos}}</span> <span class="badge">${{base.id}}</span></h2>
      <div class="badges">
        <span class="badge ${{m.status === 'reviewed' ? 'ok' : m.status === 'flagged' ? 'flag' : ''}}">status: ${{m.status}}</span>
        ${{m.warnings.map(w => `<span class="badge warn">${{w}}</span>`).join("")}}
      </div>
    </div>
    <div class="telemetry">
      <span>df: <strong>${{base.metrics.document_frequency}}</strong></span>
      <span>GitHub: <strong>${{freq.github}}</strong></span>
      <span>SO: <strong>${{freq.stackoverflow}}</strong></span>
      <span>Docs: <strong>${{freq.docs}}</strong></span>
      <span>forms: <strong>${{(base.forms || []).join(", ") || "-"}}</strong></span>
    </div>
    <div class="telemetry">
      <span>collocations: <strong>${{(base.collocations || []).join(" · ") || "-"}}</strong></span>
    </div>

    <div class="row-2">
      <div class="field">
        <label>General Japanese Gloss (ja.gloss)</label>
        <input id="ed-gloss" type="text" />
      </div>
      <div class="field">
        <label>Software-Engineering Gloss (ja.software_gloss)</label>
        <input id="ed-sgloss" type="text" />
      </div>
    </div>

    <div class="row-2">
      <div class="field">
        <label>CEFR</label>
        <select id="ed-cefr">
          <option value="">null (technical / unmapped)</option>
          <option value="A1">A1</option><option value="A2">A2</option>
          <option value="B1">B1</option><option value="B2">B2</option>
          <option value="C1">C1</option><option value="C2">C2</option>
        </select>
      </div>
      <div class="field">
        <label>Categories (click to toggle)</label>
        <div class="chips" id="ed-cats"></div>
      </div>
    </div>

    <div class="field">
      <label>Example (EN)</label>
      <textarea id="ed-ex-en" rows="2"></textarea>
    </div>
    <div class="field">
      <label>Example (JA)</label>
      <textarea id="ed-ex-ja" rows="2"></textarea>
    </div>
    <div class="field">
      <label>Live Cloze Preview</label>
      <div class="cloze-box" id="cloze-preview"></div>
    </div>
    <div class="field">
      <label>Review Note (optional)</label>
      <input id="ed-note" type="text" placeholder="Notes for follow-up or rationale..." />
    </div>

    <div class="actions">
      <button id="btn-approve" class="ok">Approve & Next (a)</button>
      <button id="btn-save" class="primary">Save as Reviewed</button>
      <button id="btn-flag" class="flag">Flag for Later (f)</button>
      <button id="btn-reset">Reset to Draft</button>
      <span style="flex:1"></span>
      <button id="btn-prev">Prev (k)</button>
      <button id="btn-next">Next (j)</button>
    </div>
    <div class="hint">Shortcuts (outside text inputs): <strong>j</strong>/<strong>k</strong> move, <strong>a</strong> approve &amp; next, <strong>f</strong> flag &amp; next, <strong>/</strong> search. Changes auto-save to browser localStorage; click "Export overrides.json" to commit via <code>python -m vocabops.curation apply-overrides</code>.</div>
  `;

  document.getElementById("ed-gloss").value = m.gloss;
  document.getElementById("ed-sgloss").value = m.software_gloss;
  document.getElementById("ed-cefr").value = m.cefr || "";
  document.getElementById("ed-ex-en").value = m.example_en;
  document.getElementById("ed-ex-ja").value = m.example_ja;
  document.getElementById("ed-note").value = m.review_note;

  let currentCats = [...m.categories];
  const catsEl = document.getElementById("ed-cats");
  function renderCats() {{
    catsEl.innerHTML = "";
    for (const c of ALLOWED_CATEGORIES) {{
      const span = document.createElement("span");
      span.className = "chip" + (currentCats.includes(c) ? " selected" : "");
      span.textContent = c;
      span.onclick = () => {{
        if (currentCats.includes(c)) {{
          if (currentCats.length > 1) currentCats = currentCats.filter(x => x !== c);
        }} else {{
          currentCats.push(c);
        }}
        renderCats();
      }};
      catsEl.appendChild(span);
    }}
  }}
  renderCats();

  function updateClozePreview() {{
    const en = document.getElementById("ed-ex-en").value;
    const cl = computeCloze(en, base.lemma, base.forms);
    const box = document.getElementById("cloze-preview");
    if (cl) {{
      box.textContent = cl.prompt + "  [answer: " + cl.answer + "]";
    }} else {{
      box.textContent = "Target term/form not found in example sentence (warning: example_missing_target_term)";
    }}
  }}
  updateClozePreview();
  document.getElementById("ed-ex-en").addEventListener("input", updateClozePreview);

  function collectPatch(status) {{
    return {{
      gloss: document.getElementById("ed-gloss").value.trim(),
      software_gloss: document.getElementById("ed-sgloss").value.trim(),
      cefr: document.getElementById("ed-cefr").value || null,
      categories: currentCats,
      example_en: document.getElementById("ed-ex-en").value.trim(),
      example_ja: document.getElementById("ed-ex-ja").value.trim(),
      review_note: document.getElementById("ed-note").value.trim(),
      status
    }};
  }}

  document.getElementById("btn-approve").onclick = () => {{
    setOverride(base.id, collectPatch("reviewed"));
    advance(1);
  }};
  document.getElementById("btn-save").onclick = () => {{
    setOverride(base.id, collectPatch("reviewed"));
    renderDetail();
  }};
  document.getElementById("btn-flag").onclick = () => {{
    setOverride(base.id, collectPatch("flagged"));
    advance(1);
  }};
  document.getElementById("btn-reset").onclick = () => {{
    delete overrides[base.id];
    saveLocal();
    applyFilters();
  }};
  document.getElementById("btn-prev").onclick = () => advance(-1);
  document.getElementById("btn-next").onclick = () => advance(1);
}}

document.getElementById("search").addEventListener("input", applyFilters);
document.getElementById("filter-status").addEventListener("change", applyFilters);
document.getElementById("filter-pos").addEventListener("change", applyFilters);
document.getElementById("filter-cat").addEventListener("change", applyFilters);

document.getElementById("btn-export").onclick = () => {{
  const sorted = {{}};
  for (const k of Object.keys(overrides).sort()) sorted[k] = overrides[k];
  const blob = new Blob([JSON.stringify({{ overrides: sorted }}, null, 2) + "\\n"], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "core500-overrides.json";
  a.click();
  URL.revokeObjectURL(url);
}};

document.getElementById("btn-import").onclick = () => document.getElementById("file-import").click();
document.getElementById("file-import").onchange = async (ev) => {{
  const file = ev.target.files[0];
  if (!file) return;
  try {{
    const data = JSON.parse(await file.text());
    overrides = data.overrides || data;
    saveLocal();
    applyFilters();
  }} catch (err) {{
    alert("Invalid overrides JSON: " + err);
  }}
}};

document.addEventListener("keydown", (ev) => {{
  const tag = (ev.target && ev.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (ev.key === "/") {{ ev.preventDefault(); document.getElementById("search").focus(); }}
  else if (ev.key === "j" || ev.key === "ArrowDown") {{ ev.preventDefault(); advance(1); }}
  else if (ev.key === "k" || ev.key === "ArrowUp") {{ ev.preventDefault(); advance(-1); }}
  else if (ev.key === "a") {{ ev.preventDefault(); const b = document.getElementById("btn-approve"); if (b) b.click(); }}
  else if (ev.key === "f") {{ ev.preventDefault(); const b = document.getElementById("btn-flag"); if (b) b.click(); }}
}});

applyFilters();
</script>
</body>
</html>
"""


def export_review(
    drafts_path: Path,
    output_dir: Path,
    *,
    overrides_path: Path | None = None,
) -> dict[str, Any]:
    """Export spreadsheet-friendly CSV and standalone HTML review workbench."""
    records = load_records(drafts_path)
    if overrides_path is not None:
        payload = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
        records, _ = apply_overrides(records, payload)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "review.csv"
    html_path = output_dir / "review.html"
    write_review_csv(records, csv_path, utf8_bom=True)

    digest = hashlib.sha256(
        json.dumps([r["id"] for r in records], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    html_text = render_review_html(
        records,
        title="VocabOps Core 500 — Curation Workbench",
        storage_key=f"vocabops-curation-{digest}",
    )
    html_path.write_text(html_text, encoding="utf-8", newline="\n")

    warnings = sum(
        1 for r in records if r.get("curation", {}).get("validation_warnings")
    )
    return {
        "records": len(records),
        "records_with_warnings": warnings,
        "csv": str(csv_path),
        "html": str(html_path),
    }


def _render_methodology(
    *,
    dataset_version: str,
    snapshot_id: str,
    records: Sequence[dict[str, Any]],
    curation_counts: dict[str, int],
    warning_counts: dict[str, int],
    draft_manifest: dict[str, Any] | None,
) -> str:
    unique_lemmas = len({r["lemma"] for r in records})
    clean = sum(1 for r in records if not r.get("curation", {}).get("validation_warnings"))
    model_name = (
        str(draft_manifest.get("model"))
        if draft_manifest and draft_manifest.get("model")
        else "Qwen/Qwen2.5-7B-Instruct"
    )
    metric_snapshot = (
        str(records[0].get("provenance", {}).get("metric_snapshot"))
        if records
        else "unknown"
    )
    sources = sorted(
        {
            s
            for r in records
            for s in r.get("provenance", {}).get("sources", [])
        }
    )

    lines = [
        f"# VocabOps Core 500 — Methodology ({dataset_version})",
        "",
        "## Overview",
        "",
        f"- **Dataset version:** `{dataset_version}`",
        f"- **Pipeline version:** `{__version__}`",
        f"- **Snapshot ID:** `{snapshot_id}`",
        f"- **Metric snapshot:** `{metric_snapshot}`",
        f"- **Records:** {len(records)} `(lemma, pos)` entries covering {unique_lemmas} unique lemmas",
        f"- **Curation status breakdown:** {json.dumps(curation_counts, sort_keys=True)}",
        f"- **Zero-warning records (with cloze):** {clean} / {len(records)}",
        "",
        "## Corpus & Ranking",
        "",
        f"- **Source families:** {', '.join(f'`{s}`' for s in sources) if sources else 'none'}",
        "- **Human Software Corpus v0.1:** 52,170 documents (17,390 GH Archive + 17,390 Stack Overflow two-stage sample + 17,390 CodeSearchNet docstrings).",
        "- **General-English baseline:** `wordfreq` (shared lemma floor `3e-07`, ranking cut `--min-df 10`).",
        "- **Ranking method:** Percentile Borda fusion with equalized absence penalty across source families (`vocabops.fusion`), split into vocabulary vs. technical views (`data/core500-vocab-v3.jsonl`).",
        "",
        "## POS & Collocation Enrichment",
        "",
        "- Generated with `python -m vocabops.enrich` using spaCy `en_core_web_trf` (`3.8.0`) on Colab GPU.",
        "- Selects each lemma's primary part of speech plus secondary POS tags with `pos_share >= 0.25`.",
        "- Extracts dependency-based collocations (`verb_obj`, `verb_prep_obj`, `amod_noun`, `noun_compound`, `verb_adv`) and observed inflected `forms`.",
        "",
        "## Draft Curation & Human Review",
        "",
        f"- Initial Japanese glosses (`ja.gloss`), software-engineering glosses (`ja.software_gloss`), CEFR estimates, allowlisted categories, and synthetic EN/JA examples were generated via `python -m vocabops.draft_curation` using `{model_name}` with greedy decoding.",
        "- Cloze cards (`cloze.prompt`, `cloze.answer`) are derived deterministically by masking the target lemma or one of its observed inflected forms.",
        "- Human edits and approvals are applied deterministically via `python -m vocabops.curation apply-overrides`, preserving corpus telemetry and distinguishing `examples[].kind = \"curated\"` from `\"synthetic\"`.",
        "",
        "## Known Limitations",
        "",
        "- Records with `curation.status = \"draft\"` and `needs_human_review = true` have not yet been manually audited.",
        "- `metrics.llm_lift` and `metrics.model_lift` remain `null` until a controlled Human vs. LLM benchmark corpus is measured (Phase 5). Neither `llm-native` nor `llm-native-candidate` is assigned automatically.",
        f"- Remaining validation warnings: `{json.dumps(warning_counts, sort_keys=True)}` (primarily shorthand abbreviations whose synthetic examples expand to full English words).",
        "",
    ]
    return "\n".join(lines)


def build_release(
    input_path: Path,
    output_dir: Path,
    *,
    dataset_version: str,
    snapshot_id: str,
    draft_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Build a release directory compliant with ``docs/release-policy.md``."""
    if not dataset_version.strip():
        raise ValueError("dataset_version must not be empty")
    if not snapshot_id.strip():
        raise ValueError("snapshot_id must not be empty")

    raw_records = load_records(input_path)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    curation_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()

    for orig in raw_records:
        rec = copy.deepcopy(orig)
        errs = validate_record(rec)
        if errs:
            raise ValueError(f"record {rec.get('id')!r} failed validation: {'; '.join(errs)}")
        rid = str(rec["id"])
        if rid in seen_ids:
            raise ValueError(f"duplicate term ID: {rid!r}")
        seen_ids.add(rid)
        rec.setdefault("provenance", {})["dataset_version"] = dataset_version
        curation_counts[str(rec.get("curation", {}).get("status", "draft"))] += 1
        for w in rec.get("curation", {}).get("validation_warnings", []):
            warning_counts[str(w)] += 1
        records.append(rec)

    if curation_counts and set(curation_counts.keys()) == {"reviewed"}:
        release_status = "reviewed"
        note = "Human-reviewed Core 500 vocabulary dataset."
    elif curation_counts.get("reviewed", 0) > 0:
        release_status = "mixed"
        note = "Partially reviewed Core 500 dataset; inspect curation.status per record."
    else:
        release_status = "draft"
        note = (
            "Unreviewed GPU-generated pre-release draft aligned with the VocabOps "
            "schema. Inspect curation.needs_human_review before treating glosses "
            "or synthetic examples as curated."
        )

    draft_manifest: dict[str, Any] | None = None
    if draft_manifest_path is not None:
        draft_manifest = json.loads(Path(draft_manifest_path).read_text(encoding="utf-8"))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    vocab_json_path = output_dir / "vocabulary.json"
    vocab_csv_path = output_dir / "vocabulary.csv"
    methodology_path = output_dir / "METHODOLOGY.md"
    manifest_path = output_dir / "manifest.json"

    vocab_payload = {
        "dataset": "vocabops-core500",
        "version": dataset_version,
        "snapshot_id": snapshot_id,
        "status": release_status,
        "note": note,
        "terms": records,
    }
    vocab_json_path.write_text(
        json.dumps(vocab_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_review_csv(records, vocab_csv_path, utf8_bom=False)

    methodology_text = _render_methodology(
        dataset_version=dataset_version,
        snapshot_id=snapshot_id,
        records=records,
        curation_counts=dict(sorted(curation_counts.items())),
        warning_counts=dict(sorted(warning_counts.items())),
        draft_manifest=draft_manifest,
    )
    methodology_path.write_text(methodology_text, encoding="utf-8", newline="\n")

    def _file_info(p: Path) -> dict[str, Any]:
        raw = p.read_bytes()
        return {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    manifest: dict[str, Any] = {
        "dataset": "vocabops-core500",
        "dataset_version": dataset_version,
        "pipeline_version": __version__,
        "snapshot_id": snapshot_id,
        "status": release_status,
        "record_count": len(records),
        "unique_lemmas": len({r["lemma"] for r in records}),
        "curation_counts": dict(sorted(curation_counts.items())),
        "clean_records": sum(
            1 for r in records if not r.get("curation", {}).get("validation_warnings")
        ),
        "warning_counts": dict(sorted(warning_counts.items())),
        "sources": sorted(
            {
                s
                for r in records
                for s in r.get("provenance", {}).get("sources", [])
            }
        ),
        "files": {
            "vocabulary.json": _file_info(vocab_json_path),
            "vocabulary.csv": _file_info(vocab_csv_path),
            "METHODOLOGY.md": _file_info(methodology_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vocabops.curation",
        description="Human curation workbench, override merger, and release exporter.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_exp = sub.add_parser(
        "export-review",
        help="export review.csv (UTF-8 BOM) and standalone review.html workbench",
    )
    p_exp.add_argument("--drafts", required=True, type=Path)
    p_exp.add_argument("--overrides", type=Path, default=None)
    p_exp.add_argument("--output", required=True, type=Path)

    p_app = sub.add_parser(
        "apply-overrides",
        help="merge human overrides.json onto drafts deterministically",
    )
    p_app.add_argument("--drafts", required=True, type=Path)
    p_app.add_argument("--overrides", required=True, type=Path)
    p_app.add_argument("--output", required=True, type=Path)

    p_rel = sub.add_parser(
        "build-release",
        help="build release bundle (vocabulary.json, vocabulary.csv, manifest.json, METHODOLOGY.md)",
    )
    p_rel.add_argument("--input", required=True, type=Path)
    p_rel.add_argument("--output", required=True, type=Path)
    p_rel.add_argument("--dataset-version", required=True)
    p_rel.add_argument("--snapshot-id", required=True)
    p_rel.add_argument("--draft-manifest", type=Path, default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export-review":
            info = export_review(
                args.drafts, args.output, overrides_path=args.overrides
            )
            print(f"records:  {info['records']} (warnings: {info['records_with_warnings']})")
            print(f"csv:      {info['csv']}")
            print(f"html:     {info['html']}")
            return 0

        if args.command == "apply-overrides":
            records = load_records(args.drafts)
            payload = json.loads(args.overrides.read_text(encoding="utf-8"))
            updated, summary = apply_overrides(records, payload)
            args.output.mkdir(parents=True, exist_ok=True)
            out_jsonl = args.output / "curated.jsonl"
            with out_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
                for rec in updated:
                    handle.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")
            out_summary = args.output / "curation-summary.json"
            out_summary.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(f"curated:  {out_jsonl} ({summary['total_records']} records)")
            print(f"applied:  {summary['overrides_applied']} (edited: {summary['human_edited']})")
            print(f"statuses: {summary['status_counts']}")
            return 0

        if args.command == "build-release":
            manifest = build_release(
                args.input,
                args.output,
                dataset_version=args.dataset_version,
                snapshot_id=args.snapshot_id,
                draft_manifest_path=args.draft_manifest,
            )
            print(f"release:  {manifest['dataset_version']} ({manifest['status']})")
            print(f"records:  {manifest['record_count']} ({manifest['unique_lemmas']} lemmas)")
            print(f"clean:    {manifest['clean_records']}")
            print(f"output:   {args.output}")
            return 0
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
