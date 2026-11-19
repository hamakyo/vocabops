"""Tests for scripts/build_views.py."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_views.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_views", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def classification(tmp_path):
    rows = [
        ("alpha", 1, "a"),
        ("bravo", 2, "b"),
        ("charlie", 3, "c"),
        ("delta", 4, "d"),
        ("echo", 5, "a"),
        ("foxtrot", 6, "b"),
    ]
    path = tmp_path / "classification.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for rank, (term, bucket) in enumerate(((t, b) for t, _, b in rows), start=1):
            handle.write(json.dumps({
                "term": term, "rank": rank, "tf": rank * 10, "df": rank,
                "score": 10.0 - rank, "bucket": bucket,
            }) + "\n")
    return path


def test_select_keeps_ranking_order_and_assigns_view_rank(classification):
    module = load_module()
    rows = module.load_classification(classification)
    vocab = module.select(rows, module.VOCAB_BUCKETS, 10)
    technical = module.select(rows, module.TECHNICAL_BUCKETS, 10)

    assert [row["term"] for row in vocab] == ["alpha", "charlie", "echo"]
    assert [row["view_rank"] for row in vocab] == [1, 2, 3]
    assert [row["rank"] for row in vocab] == [1, 3, 5]
    assert [row["bucket"] for row in vocab] == ["a", "c", "a"]
    assert [row["term"] for row in technical] == ["bravo", "foxtrot"]
    assert [row["view_rank"] for row in technical] == [1, 2]


def test_select_applies_limit_after_filtering(classification):
    module = load_module()
    rows = module.load_classification(classification)
    assert len(module.select(rows, module.VOCAB_BUCKETS, 2)) == 2
    assert len(module.select(rows, module.TECHNICAL_BUCKETS, 1)) == 1


def test_main_writes_both_views(classification, tmp_path):
    module = load_module()
    vocab = tmp_path / "vocab.jsonl"
    technical = tmp_path / "technical.jsonl"
    code = module.main([
        "--classification", str(classification),
        "--vocab-output", str(vocab),
        "--technical-output", str(technical),
    ])
    assert code == 0
    assert [json.loads(line)["term"] for line in vocab.read_text().splitlines()] == [
        "alpha", "charlie", "echo",
    ]
    assert [json.loads(line)["term"] for line in technical.read_text().splitlines()] == [
        "bravo", "foxtrot",
    ]


def test_load_rejects_non_contiguous_ranks(classification, tmp_path):
    module = load_module()
    rows = [json.loads(line) for line in classification.read_text().splitlines()]
    rows[1]["rank"] = 7
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="contiguous"):
        module.load_classification(bad)


def test_load_rejects_unknown_bucket(classification, tmp_path):
    module = load_module()
    rows = [json.loads(line) for line in classification.read_text().splitlines()]
    rows[0]["bucket"] = "z"
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="unknown bucket"):
        module.load_classification(bad)
