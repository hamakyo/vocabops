"""End-to-end tests for vocabops.pipeline."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from vocabops.normalize import normalize
from vocabops.pipeline import (
    PIPELINE_VERSION,
    document_id,
    load_documents,
    main,
    run,
)

DOC_A = "The client cannot retrieve the session. Retry the call.\n"
DOC_B = "We persist the record, then invalidate the cache.\n```\npersist(x)\n```\n"


def _write_corpus(directory: Path) -> Path:
    directory.mkdir()
    (directory / "a.txt").write_text(DOC_A, encoding="utf-8")
    (directory / "b.txt").write_text(DOC_B, encoding="utf-8")
    return directory


def test_document_id_is_sha256_of_source_family_and_path():
    expected = hashlib.sha256(b"fixture/docs/a.txt").hexdigest()
    assert document_id("fixture", "docs/a.txt") == expected
    assert len(document_id("fixture", "docs/a.txt")) == 64


def test_document_id_depends_on_family_and_path():
    assert document_id("fixture", "a.txt") != document_id("stackoverflow", "a.txt")
    assert document_id("fixture", "a.txt") != document_id("fixture", "b.txt")


def test_load_documents_reads_sorted_txt_files(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    (corpus / "ignored.md").write_text("not a document", encoding="utf-8")

    documents = load_documents(corpus)

    assert [path for _, path, _ in documents] == ["a.txt", "b.txt"]
    assert documents[0][2] == normalize(DOC_A)
    assert documents[1][2] == normalize(DOC_B)


def test_run_writes_ranking_and_manifest(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    output = tmp_path / "out"

    manifest = run(corpus, output, "test-snapshot")

    ranking_path = output / "ranking.json"
    csv_path = output / "ranking.csv"
    manifest_path = output / "manifest.json"
    assert ranking_path.is_file()
    assert csv_path.is_file()
    assert manifest_path.is_file()

    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    assert ranking
    assert set(ranking[0]) == {"term", "tf", "df", "se_specificity"}

    tokens = sum(len(normalize(path.read_text(encoding="utf-8"))) for path in corpus.glob("*.txt"))
    assert manifest == {
        "snapshot_id": "test-snapshot",
        "pipeline_version": PIPELINE_VERSION,
        "sources": ["fixture"],
        "general_baseline": "wordfreq",
        "documents": 2,
        "tokens": tokens,
        "min_df": 1,
        "attestation_min_documents": 3,
        "attested_forms": 0,
    }
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    assert sum(row["tf"] for row in ranking) == tokens


def test_ranking_is_sorted_and_csv_matches_json(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    output = tmp_path / "out"
    run(corpus, output, "test-snapshot")

    ranking = json.loads((output / "ranking.json").read_text(encoding="utf-8"))
    sorted_rows = sorted(
        ranking, key=lambda row: (-row["se_specificity"], row["term"])
    )
    assert ranking == sorted_rows

    with (output / "ranking.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    assert [row["term"] for row in csv_rows] == [row["term"] for row in ranking]
    assert [int(row["tf"]) for row in csv_rows] == [row["tf"] for row in ranking]


def test_run_is_deterministic(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    first = tmp_path / "out1"
    second = tmp_path / "out2"

    run(corpus, first, "test-snapshot")
    run(corpus, second, "test-snapshot")

    for name in ("ranking.json", "ranking.csv", "manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_cli_entry_point(tmp_path, capsys):
    corpus = _write_corpus(tmp_path / "corpus")
    output = tmp_path / "out"

    exit_code = main(
        [
            "--input",
            str(corpus),
            "--output",
            str(output),
            "--snapshot-id",
            "cli-snapshot",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "documents: 2" in captured.out
    assert (output / "manifest.json").is_file()


def test_cli_rejects_empty_input_directory(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()

    exit_code = main(
        ["--input", str(empty), "--output", str(tmp_path / "out"), "--snapshot-id", "x"]
    )

    assert exit_code == 2
    assert "no documents found" in capsys.readouterr().err


def test_min_df_filters_low_document_frequency_terms(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.txt").write_text("Retrieve the cache entry.\n", encoding="utf-8")
    (corpus / "b.txt").write_text(
        "Retrieve the record, then invalidate the cache.\n", encoding="utf-8"
    )
    (corpus / "c.txt").write_text("Invalidate the fallback path.\n", encoding="utf-8")
    unfiltered = tmp_path / "all"
    filtered = tmp_path / "df2"

    run(corpus, unfiltered, "test-snapshot")
    manifest = run(corpus, filtered, "test-snapshot", min_df=2)

    all_rows = json.loads((unfiltered / "ranking.json").read_text(encoding="utf-8"))
    kept_rows = json.loads((filtered / "ranking.json").read_text(encoding="utf-8"))

    assert {row["term"] for row in all_rows if row["df"] == 1} == {
        "entry",
        "fallback",
        "path",
        "record",
    }
    assert kept_rows
    assert all(row["df"] >= 2 for row in kept_rows)
    assert {row["term"] for row in kept_rows} == {"retrieve", "cache", "invalidate"}
    assert [row["term"] for row in kept_rows] == [
        row["term"] for row in all_rows if row["df"] >= 2
    ]
    assert manifest["min_df"] == 2

    with (filtered / "ranking.csv").open(encoding="utf-8", newline="") as handle:
        csv_terms = [row["term"] for row in csv.DictReader(handle)]
    assert csv_terms == [row["term"] for row in kept_rows]


def test_min_df_default_does_not_filter(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    output = tmp_path / "out"

    manifest = run(corpus, output, "test-snapshot")

    ranking = json.loads((output / "ranking.json").read_text(encoding="utf-8"))
    assert manifest["min_df"] == 1
    assert any(row["df"] == 1 for row in ranking)


def test_cli_rejects_min_df_below_one(tmp_path, capsys):
    corpus = _write_corpus(tmp_path / "corpus")

    exit_code = main(
        [
            "--input",
            str(corpus),
            "--output",
            str(tmp_path / "out"),
            "--snapshot-id",
            "x",
            "--min-df",
            "0",
        ]
    )

    assert exit_code == 2
    assert "--min-df" in capsys.readouterr().err


def _write_jsonl(path: Path) -> Path:
    records = [
        {
            "doc_id": "a" * 64,
            "source_family": "gharchive",
            "repo": "acme/widgets",
            "text": "The worker must retrieve and persist the record.",
        },
        {
            "doc_id": "b" * 64,
            "source_family": "gharchive",
            "repo": None,
            "text": "We invalidate the cache when the schema changes.",
        },
        {
            "doc_id": "c" * 64,
            "source_family": "fixture",
            "repo": None,
            "text": "A review note about fallbacks.",
        },
    ]
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_jsonl_input_produces_ranking_and_sources(tmp_path):
    path = _write_jsonl(tmp_path / "documents.jsonl")
    output = tmp_path / "out"

    manifest = run(path, output, "jsonl-snapshot")

    assert (output / "ranking.json").is_file()
    assert (output / "ranking.csv").is_file()
    assert manifest["sources"] == ["fixture", "gharchive"]
    assert manifest["documents"] == 3
    assert manifest["tokens"] == sum(
        len(normalize(json.loads(line)["text"]))
        for line in path.read_text(encoding="utf-8").splitlines()
    )
    terms = {
        row["term"]
        for row in json.loads((output / "ranking.json").read_text(encoding="utf-8"))
    }
    assert {"retrieve", "persist", "invalidate", "cache"} <= terms


def test_jsonl_sources_come_from_the_data(tmp_path):
    path = _write_jsonl(tmp_path / "documents.jsonl")
    manifest = run(path, tmp_path / "out", "jsonl-snapshot")
    assert manifest["sources"] == ["fixture", "gharchive"]

    single = tmp_path / "single.jsonl"
    single.write_text(
        json.dumps({"source_family": "gharchive", "text": "Only one family here."}) + "\n",
        encoding="utf-8",
    )
    single_manifest = run(single, tmp_path / "out2", "jsonl-snapshot")
    assert single_manifest["sources"] == ["gharchive"]


def test_jsonl_input_without_usable_documents_is_rejected(tmp_path, capsys):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    exit_code = main(
        [
            "--input",
            str(empty),
            "--output",
            str(tmp_path / "out"),
            "--snapshot-id",
            "x",
        ]
    )

    assert exit_code == 2
    assert "no documents found" in capsys.readouterr().err


def _write_texts(directory: Path, texts: list[str]) -> Path:
    directory.mkdir()
    for index, text in enumerate(texts, start=1):
        (directory / f"{index:02d}.txt").write_text(text, encoding="utf-8")
    return directory


def _ranking_terms(output: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads((output / "ranking.json").read_text(encoding="utf-8"))
    return {row["term"]: row for row in rows}


def test_corpus_attestation_merges_rebase_inflections(tmp_path):
    # "rebase" is wordfreq 6.46e-08, below the 3e-07 lemma floor, so without
    # corpus evidence "rebased"/"rebases" can never validate. The headword
    # occurs standalone in three documents here, which is the attestation
    # threshold; the two inflections occur in one document each and are
    # therefore not attested themselves.
    corpus = _write_texts(
        tmp_path / "corpus",
        [
            "We rebase the branch before the merge.\n",
            "Rebase the branch again.\n",
            "A rebase rewrites history.\n",
            "The rebased branch is clean.\n",
            "He rebases the branch daily.\n",
        ],
    )
    output = tmp_path / "out"

    manifest = run(corpus, output, "attested")
    terms = _ranking_terms(output)

    assert int(terms["rebase"]["tf"]) == 5
    assert int(terms["rebase"]["df"]) == 5
    assert "rebased" not in terms
    assert "rebases" not in terms
    assert manifest["attestation_min_documents"] == 3
    assert int(manifest["attested_forms"]) >= 1


def test_corpus_attestation_below_threshold_does_not_merge(tmp_path):
    # The headword occurs in only two documents, so it is not attested and the
    # inflections keep their own rows, exactly as before this mechanism.
    corpus = _write_texts(
        tmp_path / "corpus",
        [
            "We rebase the branch before the merge.\n",
            "Rebase the branch again.\n",
            "The rebased branch is clean.\n",
            "He rebases the branch daily.\n",
        ],
    )
    output = tmp_path / "out"

    run(corpus, output, "unattested")
    terms = _ranking_terms(output)

    assert {"rebase", "rebased", "rebases"} <= set(terms)
    assert int(terms["rebase"]["tf"]) == 2


def test_corpus_attestation_merges_dedup_inflections(tmp_path):
    # "dedup" and "dedupe" are both wordfreq 0.0. The suffix rules propose
    # "dedup"/"dedupe" for "deduped" and "deduping"; with "dedup" attested the
    # zero-frequency tie is broken in its favour by the attestation rule.
    corpus = _write_texts(
        tmp_path / "corpus",
        [
            "Run dedup nightly.\n",
            "The dedup pass is slow.\n",
            "Dedup runs first.\n",
            "The deduping step finished.\n",
            "We deduped the archive.\n",
        ],
    )
    output = tmp_path / "out"

    run(corpus, output, "attested")
    terms = _ranking_terms(output)

    assert int(terms["dedup"]["tf"]) == 5
    assert int(terms["dedup"]["df"]) == 5
    assert "deduping" not in terms
    assert "deduped" not in terms
    assert "dedupe" not in terms



def _write_two_family_jsonl(path: Path) -> Path:
    """Two families with unequal list lengths; tokens are zero-frequency.

    fam_a lists four equal-tf terms (so ranks are term-ascending), fam_b lists
    two. All documents repeat the same text, so every term has df 2.
    """
    records = [
        {"source_family": "fam_a", "text": "zqxaa zqxab zqxac zqxad"},
        {"source_family": "fam_a", "text": "zqxaa zqxab zqxac zqxad"},
        {"source_family": "fam_b", "text": "zqxbx zqxby"},
        {"source_family": "fam_b", "text": "zqxbx zqxby"},
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_borda_fuses_percentile_ranks_and_equalizes_absence(tmp_path):
    path = _write_two_family_jsonl(tmp_path / "documents.jsonl")
    output = tmp_path / "out"

    run(path, output, "borda", min_df=2, ranking_method="borda")
    rows = json.loads((output / "ranking.json").read_text(encoding="utf-8"))

    # zqxab: rank 2 of 4 in fam_a + absent (1.0) in fam_b = 1.5
    # zqxbx: absent (1.0) in fam_a + rank 1 of 2 in fam_b = 1.5
    # Raw Borda would charge 2 + (2 + 1) = 5 and (4 + 1) + 1 = 6 here; the
    # percentile variant gives the same absence cost in every source, so the
    # two terms tie and the term-ascending rule orders them.
    assert [(row["term"], row["se_specificity"]) for row in rows] == [
        ("zqxaa", 1.25),
        ("zqxab", 1.5),
        ("zqxbx", 1.5),
        ("zqxac", 1.75),
        ("zqxad", 2.0),
        ("zqxby", 2.0),
    ]
    # tf/df stay pooled counts; the score column is the fused value.
    assert rows[0]["tf"] == 2
    assert rows[0]["df"] == 2


def test_borda_manifest_records_method_variant_and_sources(tmp_path):
    path = _write_two_family_jsonl(tmp_path / "documents.jsonl")
    output = tmp_path / "out"

    manifest = run(path, output, "borda", min_df=2, ranking_method="borda")

    assert manifest["ranking_method"] == "borda"
    assert manifest["borda_variant"] == "percentile"
    assert "lower is better" in manifest["score_semantics"]
    assert manifest["documents"] == 4
    assert manifest["tokens"] == 12
    assert manifest["per_source"] == [
        {"name": "fam_a", "documents": 2, "tokens": 8, "listed": 4},
        {"name": "fam_b", "documents": 2, "tokens": 4, "listed": 2},
    ]
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_borda_rejects_a_single_source_family(tmp_path):
    corpus = _write_corpus(tmp_path / "corpus")
    with pytest.raises(ValueError, match="at least two source families"):
        run(corpus, tmp_path / "out", "borda", ranking_method="borda")


def test_borda_rejects_documents_without_source_family(tmp_path):
    path = tmp_path / "documents.jsonl"
    path.write_text(
        json.dumps({"text": "A document with no family."}) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="source_family"):
        run(path, tmp_path / "out", "borda", ranking_method="borda")


def test_borda_cli_reports_a_single_family_error(tmp_path, capsys):
    corpus = _write_corpus(tmp_path / "corpus")

    exit_code = main(
        [
            "--input",
            str(corpus),
            "--output",
            str(tmp_path / "out"),
            "--snapshot-id",
            "x",
            "--ranking-method",
            "borda",
        ]
    )

    assert exit_code == 2
    assert "at least two source families" in capsys.readouterr().err
