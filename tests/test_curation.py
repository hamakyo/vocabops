"""Unit tests for vocabops.curation (review export, override merging, release bundling)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from vocabops import curation


def _sample_drafts() -> list[dict[str, Any]]:
    return [
        {
            "id": "invalidate.v",
            "term": "invalidate",
            "lemma": "invalidate",
            "pos": "verb",
            "ja": {
                "gloss": "無効にする",
                "software_gloss": "キャッシュを無効化する",
            },
            "cefr": "B2",
            "categories": ["backend", "security"],
            "forms": ["invalidates", "invalidated", "invalidating"],
            "collocations": ["invalidate cache", "invalidate token"],
            "examples": [
                {
                    "text": "The system invalidates tokens after they expire.",
                    "kind": "synthetic",
                    "ja": "トークンが期限切れになるとシステムはそれを無効にします。",
                }
            ],
            "cloze": {
                "prompt": "The system ____ tokens after they expire.",
                "answer": "invalidates",
            },
            "metrics": {
                "frequency": {"github": 40, "stackoverflow": 25, "docs": 15, "llm": None},
                "document_frequency": 60,
                "se_specificity": None,
                "llm_lift": None,
                "model_lift": {"claude": None, "gpt": None, "gemini": None},
            },
            "learning": {"tier": "core", "priority": None},
            "provenance": {
                "dataset_version": "0.1.0-draft",
                "metric_snapshot": "combined-3source-enrich-v1",
                "sources": ["codesearchnet", "gharchive", "stackoverflow"],
            },
            "curation": {
                "status": "draft",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "needs_human_review": True,
                "validation_warnings": [],
            },
        },
        {
            "id": "param.n",
            "term": "param",
            "lemma": "param",
            "pos": "noun",
            "ja": {
                "gloss": "パラメータ",
                "software_gloss": "関数の引数・パラメータ",
            },
            "cefr": None,
            "categories": ["core"],
            "forms": ["params"],
            "collocations": ["query param"],
            "examples": [
                {
                    "text": "Define the parameters and their values in the function.",
                    "kind": "synthetic",
                    "ja": "関数のパラメータとその値を定義する。",
                }
            ],
            "cloze": None,
            "metrics": {
                "frequency": {"github": 90, "stackoverflow": 50, "docs": 30, "llm": None},
                "document_frequency": 120,
                "se_specificity": None,
                "llm_lift": None,
                "model_lift": {"claude": None, "gpt": None, "gemini": None},
            },
            "learning": {"tier": "core", "priority": None},
            "provenance": {
                "dataset_version": "0.1.0-draft",
                "metric_snapshot": "combined-3source-enrich-v1",
                "sources": ["codesearchnet", "gharchive", "stackoverflow"],
            },
            "curation": {
                "status": "draft",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "needs_human_review": True,
                "validation_warnings": ["example_missing_target_term"],
            },
        },
    ]


def test_apply_overrides_updates_fields_recomputes_cloze_and_preserves_metrics() -> None:
    drafts = _sample_drafts()
    overrides = {
        "overrides": {
            "param.n": {
                "gloss": "仮引数・パラメータ",
                "cefr": "B1",
                "categories": ["core", "backend"],
                "example_en": "Pass the query param to filter the API response.",
                "example_ja": "API レスポンスを絞り込むためにクエリ param を渡す。",
                "status": "reviewed",
                "review_note": "Replaced expanded 'parameters' with 'param'.",
            },
            "invalidate.v": {
                "status": "flagged",
                "review_note": "Check CEFR B2 vs C1.",
            },
        }
    }

    updated, summary = curation.apply_overrides(drafts, overrides)
    by_id = {r["id"]: r for r in updated}

    p = by_id["param.n"]
    assert p["ja"]["gloss"] == "仮引数・パラメータ"
    assert p["cefr"] == "B1"
    assert p["categories"] == ["core", "backend"]
    assert p["examples"][0]["kind"] == "curated"
    assert p["cloze"] == {
        "prompt": "Pass the query ____ to filter the API response.",
        "answer": "param",
    }
    assert p["curation"]["status"] == "reviewed"
    assert p["curation"]["needs_human_review"] is False
    assert p["curation"]["human_edited"] is True
    assert p["curation"]["validation_warnings"] == []
    # Corpus telemetry remains untouched.
    assert p["metrics"] == drafts[1]["metrics"]

    inv = by_id["invalidate.v"]
    assert inv["curation"]["status"] == "flagged"
    assert inv["curation"]["needs_human_review"] is True
    assert inv["curation"]["human_edited"] is False
    assert inv["examples"][0]["kind"] == "synthetic"

    assert summary == {
        "total_records": 2,
        "overrides_applied": 2,
        "human_edited": 1,
        "status_counts": {"flagged": 1, "reviewed": 1},
        "clean_records": 2,
    }


def test_apply_overrides_rejects_guardrail_violations() -> None:
    drafts = _sample_drafts()

    with pytest.raises(ValueError, match="unknown term IDs"):
        curation.apply_overrides(drafts, {"does_not_exist.v": {"status": "reviewed"}})

    with pytest.raises(ValueError, match="disallowed category"):
        curation.apply_overrides(
            drafts, {"invalidate.v": {"categories": ["llm-native"]}}
        )

    with pytest.raises(ValueError, match="disallowed category"):
        curation.apply_overrides(
            drafts, {"invalidate.v": {"categories": ["llm-native-candidate"]}}
        )

    with pytest.raises(ValueError, match="invalid cefr"):
        curation.apply_overrides(drafts, {"invalidate.v": {"cefr": "Z9"}})


def test_export_review_escapes_script_tags_and_writes_bom_csv(tmp_path: Path) -> None:
    drafts = _sample_drafts()
    drafts[0]["ja"]["gloss"] = "テスト</script><script>alert(1)</script>"
    drafts_path = tmp_path / "drafts.jsonl"
    drafts_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in drafts) + "\n",
        encoding="utf-8",
    )

    out_a = tmp_path / "rev_a"
    out_b = tmp_path / "rev_b"
    info_a = curation.export_review(drafts_path, out_a)
    curation.export_review(drafts_path, out_b)

    assert info_a["records"] == 2
    assert info_a["records_with_warnings"] == 1

    csv_bytes = (out_a / "review.csv").read_bytes()
    assert csv_bytes.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for spreadsheets
    assert csv_bytes == (out_b / "review.csv").read_bytes()

    html_text = (out_a / "review.html").read_text(encoding="utf-8")
    assert html_text == (out_b / "review.html").read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html_text
    assert "<\\/script>" in html_text


def test_build_release_deterministic_and_json_csv_parity(tmp_path: Path) -> None:
    drafts_path = tmp_path / "drafts.jsonl"
    drafts_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in _sample_drafts()) + "\n",
        encoding="utf-8",
    )

    rel_a = tmp_path / "rel_a"
    rel_b = tmp_path / "rel_b"
    m_a = curation.build_release(
        drafts_path,
        rel_a,
        dataset_version="0.1.0-draft",
        snapshot_id="core500-draft-v1",
    )
    m_b = curation.build_release(
        drafts_path,
        rel_b,
        dataset_version="0.1.0-draft",
        snapshot_id="core500-draft-v1",
    )

    assert m_a == m_b
    assert m_a["status"] == "draft"
    assert m_a["record_count"] == 2
    assert m_a["unique_lemmas"] == 2

    for fname in ("vocabulary.json", "vocabulary.csv", "manifest.json", "METHODOLOGY.md"):
        assert (rel_a / fname).read_bytes() == (rel_b / fname).read_bytes()

    vocab_json = json.loads((rel_a / "vocabulary.json").read_text(encoding="utf-8"))
    with (rel_a / "vocabulary.csv").open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    assert [t["id"] for t in vocab_json["terms"]] == [r["id"] for r in csv_rows]
    assert len(csv_rows) == 2


def test_cli_roundtrip(tmp_path: Path) -> None:
    drafts_path = tmp_path / "drafts.jsonl"
    drafts_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in _sample_drafts()) + "\n",
        encoding="utf-8",
    )
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps({"overrides": {"invalidate.v": {"status": "reviewed"}}}),
        encoding="utf-8",
    )

    assert (
        curation.main(
            [
                "export-review",
                "--drafts",
                str(drafts_path),
                "--output",
                str(tmp_path / "review"),
            ]
        )
        == 0
    )
    assert (
        curation.main(
            [
                "apply-overrides",
                "--drafts",
                str(drafts_path),
                "--overrides",
                str(overrides_path),
                "--output",
                str(tmp_path / "curated"),
            ]
        )
        == 0
    )
    assert (
        curation.main(
            [
                "build-release",
                "--input",
                str(tmp_path / "curated" / "curated.jsonl"),
                "--output",
                str(tmp_path / "release"),
                "--dataset-version",
                "0.1.0-rc1",
                "--snapshot-id",
                "snap-1",
            ]
        )
        == 0
    )
    manifest = json.loads(
        (tmp_path / "release" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "mixed"
    assert manifest["curation_counts"] == {"draft": 1, "reviewed": 1}
