"""Offline unit tests for vocabops.draft_curation (no GPU or HF downloads)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vocabops import draft_curation


def _sample_enrichment_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": "invalidate.v",
            "lemma": "invalidate",
            "pos": "verb",
            "tf": 120,
            "df": 85,
            "pos_share": 0.92,
            "forms": ["invalidated", "invalidates", "invalidating"],
            "collocations": [
                {"phrase": "invalidate cache", "pattern": "verb_obj", "count": 40, "df": 32},
                {"phrase": "invalidate session", "pattern": "verb_obj", "count": 12, "df": 10},
            ],
            "by_source": {
                "gharchive": {"tf": 50, "df": 35},
                "stackoverflow": {"tf": 40, "df": 30},
                "codesearchnet": {"tf": 30, "df": 20},
            },
        },
        {
            "id": "invalidate.n",
            "lemma": "invalidate",
            "pos": "noun",
            "tf": 10,
            "df": 8,
            "pos_share": 0.08,
            "forms": [],
            "collocations": [],
            "by_source": {"gharchive": {"tf": 10, "df": 8}},
        },
        {
            "id": "build.v",
            "lemma": "build",
            "pos": "verb",
            "tf": 500,
            "df": 300,
            "pos_share": 0.65,
            "forms": ["built", "builds", "building"],
            "collocations": [
                {"phrase": "build image", "pattern": "verb_obj", "count": 60, "df": 50},
            ],
            "by_source": {
                "gharchive": {"tf": 300, "df": 180},
                "stackoverflow": {"tf": 200, "df": 120},
            },
        },
        {
            "id": "build.n",
            "lemma": "build",
            "pos": "noun",
            "tf": 270,
            "df": 190,
            "pos_share": 0.35,
            "forms": ["builds"],
            "collocations": [
                {"phrase": "ci build", "pattern": "noun_compound", "count": 25, "df": 20},
            ],
            "by_source": {"gharchive": {"tf": 270, "df": 190}},
        },
    ]


def test_select_entries_keeps_primary_and_threshold_secondary() -> None:
    rows = _sample_enrichment_rows()
    ranking = {"invalidate": 1, "build": 2}
    selected = draft_curation.select_entries(
        rows, min_pos_share=0.25, ranking_order=ranking
    )
    assert [r["id"] for r in selected] == ["invalidate.v", "build.v", "build.n"]

    limited = draft_curation.select_entries(
        rows, min_pos_share=0.25, ranking_order=ranking, limit=2
    )
    assert [r["id"] for r in limited] == ["invalidate.v", "build.v"]

    by_df = draft_curation.select_entries(rows, min_pos_share=0.25)
    assert [r["id"] for r in by_df] == ["build.v", "build.n", "invalidate.v"]


def test_parse_llm_json_variants() -> None:
    bare = '{"gloss": "無効にする", "cefr": "C1"}'
    assert draft_curation.parse_llm_json(bare) == {"gloss": "無効にする", "cefr": "C1"}

    fenced = 'Sure!\n```json\n{"gloss": "構築する", "cefr": "A2"}\n```\n'
    assert draft_curation.parse_llm_json(fenced) == {"gloss": "構築する", "cefr": "A2"}

    wrapped = 'Result: {"gloss": "キャッシュ"} done.'
    assert draft_curation.parse_llm_json(wrapped) == {"gloss": "キャッシュ"}

    assert draft_curation.parse_llm_json("not json at all") is None
    assert draft_curation.parse_llm_json("[]") is None
    assert draft_curation.parse_llm_json("") is None


def test_build_cloze_matches_inflected_form_and_preserves_case() -> None:
    cloze = draft_curation.build_cloze(
        "Deploying a new release Invalidated the CDN cache immediately.",
        "invalidate",
        ["invalidated", "invalidates"],
    )
    assert cloze == {
        "prompt": "Deploying a new release ____ the CDN cache immediately.",
        "answer": "Invalidated",
    }

    assert (
        draft_curation.build_cloze(
            "The worker clears stale entries on startup.",
            "invalidate",
            ["invalidated"],
        )
        is None
    )


def test_assemble_draft_record_schema_and_guardrails() -> None:
    entry = _sample_enrichment_rows()[0]
    raw_json = json.dumps(
        {
            "gloss": "無効にする",
            "software_gloss": "キャッシュやセッションを無効化する",
            "cefr": "c1",
            "categories": ["Backend", "llm-native", "llm-native-candidate", "cloud", "unknown"],
            "example_en": "We invalidate the cache whenever a user updates their profile.",
            "example_ja": "ユーザーがプロフィールを更新するたびにキャッシュを無効化します。",
        },
        ensure_ascii=False,
    )
    rec = draft_curation.assemble_draft_record(
        entry,
        raw_json,
        model_name="Qwen/Qwen2.5-7B-Instruct",
        dataset_version="0.1.0-draft",
        metric_snapshot="combined-3source-enrich-v1",
    )

    assert rec["id"] == "invalidate.v"
    assert rec["term"] == "invalidate"
    assert rec["lemma"] == "invalidate"
    assert rec["pos"] == "verb"
    assert rec["ja"] == {
        "gloss": "無効にする",
        "software_gloss": "キャッシュやセッションを無効化する",
    }
    assert rec["cefr"] == "C1"
    # Never allows llm-native / llm-native-candidate or unknown tags.
    assert rec["categories"] == ["backend", "cloud"]
    assert rec["collocations"] == ["invalidate cache", "invalidate session"]
    assert rec["examples"] == [
        {
            "text": "We invalidate the cache whenever a user updates their profile.",
            "kind": "synthetic",
            "ja": "ユーザーがプロフィールを更新するたびにキャッシュを無効化します。",
        }
    ]
    assert rec["cloze"] == {
        "prompt": "We ____ the cache whenever a user updates their profile.",
        "answer": "invalidate",
    }
    assert rec["metrics"]["frequency"] == {
        "github": 50,
        "stackoverflow": 40,
        "docs": 30,
        "llm": None,
    }
    assert rec["metrics"]["document_frequency"] == 85
    assert rec["metrics"]["llm_lift"] is None
    assert rec["metrics"]["model_lift"] == {"claude": None, "gpt": None, "gemini": None}
    assert rec["provenance"] == {
        "dataset_version": "0.1.0-draft",
        "metric_snapshot": "combined-3source-enrich-v1",
        "sources": ["codesearchnet", "gharchive", "stackoverflow"],
    }
    assert rec["curation"] == {
        "status": "draft",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "needs_human_review": True,
        "validation_warnings": [],
    }


def test_assemble_draft_record_records_warnings_on_bad_output() -> None:
    entry = _sample_enrichment_rows()[0]
    rec = draft_curation.assemble_draft_record(
        entry,
        "invalid non-json response",
        model_name="fake-model",
        dataset_version="0.1.0-draft",
        metric_snapshot="snap-1",
    )
    assert rec["categories"] == ["core"]
    assert rec["cloze"] is None
    assert rec["curation"]["validation_warnings"] == [
        "json_parse_failed",
        "missing_gloss",
        "missing_software_gloss",
        "missing_example_en",
    ]

    missing_target = json.dumps(
        {
            "gloss": "無効にする",
            "software_gloss": "キャッシュを破棄する",
            "cefr": None,
            "categories": ["backend"],
            "example_en": "The worker clears stale entries every hour.",
            "example_ja": "ワーカーは毎時古いエントリを削除します。",
        },
        ensure_ascii=False,
    )
    rec2 = draft_curation.assemble_draft_record(
        entry,
        missing_target,
        model_name="fake-model",
        dataset_version="0.1.0-draft",
        metric_snapshot="snap-1",
    )
    assert rec2["cloze"] is None
    assert rec2["curation"]["validation_warnings"] == ["example_missing_target_term"]


def test_run_is_byte_deterministic(tmp_path: Path) -> None:
    enrich_path = tmp_path / "enrichment.jsonl"
    ranking_path = tmp_path / "ranking.jsonl"
    enrich_path.write_text(
        "\n".join(json.dumps(r) for r in _sample_enrichment_rows()) + "\n",
        encoding="utf-8",
    )
    ranking_path.write_text(
        "\n".join(
            [
                json.dumps({"term": "invalidate", "view_rank": 1}),
                json.dumps({"term": "build", "view_rank": 2}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    canned = {
        "invalidate": json.dumps(
            {
                "gloss": "無効にする",
                "software_gloss": "キャッシュを無効化する",
                "cefr": "C1",
                "categories": ["backend"],
                "example_en": "Deploying new assets invalidated the edge cache.",
                "example_ja": "新しいアセットのデプロイでエッジキャッシュが無効化された。",
            },
            ensure_ascii=False,
        ),
        "build": json.dumps(
            {
                "gloss": "構築する",
                "software_gloss": "ビルドを実行する",
                "cefr": "A2",
                "categories": ["core"],
                "example_en": "The pipeline builds the container image on every merge.",
                "example_ja": "パイプラインはマージごとにコンテナイメージをビルドする。",
            },
            ensure_ascii=False,
        ),
    }

    def fake_generator(batch_msgs: list[list[dict[str, str]]]) -> list[str]:
        outputs: list[str] = []
        for msgs in batch_msgs:
            user_prompt = msgs[1]["content"]
            if "lemma): invalidate" in user_prompt:
                outputs.append(canned["invalidate"])
            else:
                outputs.append(canned["build"])
        return outputs

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    manifest_a = draft_curation.run(
        enrich_path,
        out_a,
        "test-draft-v1",
        ranking_path=ranking_path,
        batch_size=2,
        generator=fake_generator,
    )
    manifest_b = draft_curation.run(
        enrich_path,
        out_b,
        "test-draft-v1",
        ranking_path=ranking_path,
        batch_size=2,
        generator=fake_generator,
    )

    assert manifest_a == manifest_b
    assert manifest_a["entries_drafted"] == 3
    assert manifest_a["clean_records"] == 3
    assert manifest_a["warning_counts"] == {}
    assert (out_a / "drafts.jsonl").read_bytes() == (out_b / "drafts.jsonl").read_bytes()
    assert (out_a / "manifest.json").read_bytes() == (out_b / "manifest.json").read_bytes()


def test_run_validation_errors(tmp_path: Path) -> None:
    enrich_path = tmp_path / "enrichment.jsonl"
    enrich_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot_id"):
        draft_curation.run(enrich_path, tmp_path / "out", "   ")

    with pytest.raises(ValueError, match="min_pos_share"):
        draft_curation.run(enrich_path, tmp_path / "out", "snap", min_pos_share=1.5)

    with pytest.raises(ValueError, match="batch_size"):
        draft_curation.run(enrich_path, tmp_path / "out", "snap", batch_size=0)

    with pytest.raises(ValueError, match="max_retries"):
        draft_curation.run(enrich_path, tmp_path / "out", "snap", max_retries=-1)


def test_parse_llm_json_trailing_comma() -> None:
    trailing = '{"gloss": "無効にする", "categories": ["backend",],}'
    assert draft_curation.parse_llm_json(trailing) == {
        "gloss": "無効にする",
        "categories": ["backend"],
    }


def test_run_retries_parse_failures_and_repairs_existing(tmp_path: Path) -> None:
    enrich_path = tmp_path / "enrichment.jsonl"
    enrich_path.write_text(
        "\n".join(json.dumps(r) for r in _sample_enrichment_rows()) + "\n",
        encoding="utf-8",
    )

    valid_inv = json.dumps(
        {
            "gloss": "無効にする",
            "software_gloss": "キャッシュを無効化する",
            "cefr": "C1",
            "categories": ["backend"],
            "example_en": "We invalidate the cache on deployment.",
            "example_ja": "デプロイ時にキャッシュを無効化する。",
        },
        ensure_ascii=False,
    )
    valid_build = json.dumps(
        {
            "gloss": "構築する",
            "software_gloss": "ビルドする",
            "cefr": "A2",
            "categories": ["core"],
            "example_en": "The workflow builds the release artifact.",
            "example_ja": "ワークフローはリリース成果物をビルドする。",
        },
        ensure_ascii=False,
    )

    # First run: invalidate fails on initial pass, succeeds on retry1.
    def flaky_generator(batch_msgs: list[list[dict[str, str]]]) -> list[str]:
        outs: list[str] = []
        for msgs in batch_msgs:
            prompt = msgs[1]["content"]
            if "lemma): invalidate" in prompt and "IMPORTANT:" not in prompt:
                outs.append("{broken json")
            elif "lemma): invalidate" in prompt:
                outs.append(valid_inv)
            else:
                outs.append(valid_build)
        return outs

    out_retry = tmp_path / "out_retry"
    manifest = draft_curation.run(
        enrich_path,
        out_retry,
        "retry-snap",
        batch_size=4,
        max_retries=2,
        generator=flaky_generator,
    )
    assert manifest["entries_drafted"] == 3
    assert manifest["clean_records"] == 3
    assert manifest["retried_entries"] == 1
    assert manifest["warning_counts"] == {}

    # Second scenario: first run with max_retries=0 leaves 1 failed entry,
    # then --existing repairs ONLY that failed entry without touching valid ones.
    out_partial = tmp_path / "out_partial"
    m_partial = draft_curation.run(
        enrich_path,
        out_partial,
        "partial-snap",
        batch_size=4,
        max_retries=0,
        generator=flaky_generator,
    )
    assert m_partial["warning_counts"]["json_parse_failed"] == 1

    called_prompts: list[str] = []

    def repair_generator(batch_msgs: list[list[dict[str, str]]]) -> list[str]:
        for msgs in batch_msgs:
            called_prompts.append(msgs[1]["content"])
        return [valid_inv for _ in batch_msgs]

    out_repaired = tmp_path / "out_repaired"
    m_repaired = draft_curation.run(
        enrich_path,
        out_repaired,
        "repaired-snap",
        existing_drafts_path=out_partial / "drafts.jsonl",
        batch_size=4,
        max_retries=2,
        generator=repair_generator,
    )
    assert len(called_prompts) == 1
    assert "lemma): invalidate" in called_prompts[0]
    assert m_repaired["entries_drafted"] == 3
    assert m_repaired["clean_records"] == 3
    assert m_repaired["warning_counts"] == {}

