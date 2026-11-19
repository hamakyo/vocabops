"""End-to-end tests for vocabops.pipeline."""

import csv
import hashlib
import json
from pathlib import Path

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
    assert "no .txt documents" in capsys.readouterr().err
