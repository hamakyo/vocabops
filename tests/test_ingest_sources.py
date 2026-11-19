"""Tests for the Stack Overflow and CodeSearchNet corpus adapters."""

import gzip
import json

import pytest

from vocabops.ingest import (
    clean_docstring_text,
    clean_stackoverflow_text,
    ingest_codesearchnet,
    ingest_stackoverflow,
    main,
    reservoir_sample,
)

LONG_TEXT = (
    "The deployment pipeline retries the upload when the remote object store "
    "returns a transient error, and it records every failed attempt in the "
    "structured event log so that operators can reproduce the problem later."
)
LONG_TEXT_2 = (
    "Caching the rendered template avoids a database round trip on every "
    "request, but the cache must be invalidated whenever the underlying "
    "configuration record changes or users will observe stale responses."
)


def _exchange_record(title, body, tags=None):
    return {"texts": [title, body], "tags": tags or ["python"]}


def _write_exchange(path, records, gzipped=False):
    payload = "".join(json.dumps(record) + "\n" for record in records).encode("utf-8")
    if gzipped:
        with gzip.open(path, "wb") as handle:
            handle.write(payload)
    else:
        path.write_bytes(payload)
    return path


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_clean_stackoverflow_strips_html_and_code_blocks():
    raw = (
        "<p>Please explain the fallback path.</p>"
        "<pre><code>raise RuntimeError('boom')</code></pre>"
        "<code>inline_call()</code>"
        "<p>Escaped block: &lt;pre&gt;&lt;code&gt;secret()&lt;/code&gt;&lt;/pre&gt;</p>"
    )
    cleaned = clean_stackoverflow_text(raw)
    assert "fallback path" in cleaned
    assert "RuntimeError" not in cleaned
    assert "inline_call" not in cleaned
    assert "secret" not in cleaned
    assert "<" not in cleaned


def test_clean_docstring_strips_markup_and_urls():
    cleaned = clean_docstring_text(
        "<b>Return</b> the parsed value.\n\nSee https://example.com/docs for details."
    )
    assert cleaned == "Return the parsed value.\n\nSee for details."


def test_stackoverflow_length_gate_and_schema(tmp_path):
    source = _write_exchange(
        tmp_path / "posts.jsonl.gz",
        [
            _exchange_record("Short", "Too short."),
            _exchange_record("Deploy retries", LONG_TEXT, ["deployment", "retry"]),
        ],
        gzipped=True,
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest_stackoverflow([source], output, sample_size=10, seed=7)

    assert counters["records_seen"] == 2
    assert counters["skipped_too_short"] == 1
    assert counters["passed_gates"] == 1
    assert counters["sampled"] == 1

    documents = _read_jsonl(output)
    assert len(documents) == 1
    document = documents[0]
    assert set(document) == {"doc_id", "source_family", "repo", "actor", "tags", "text"}
    assert document["source_family"] == "stackoverflow"
    assert document["repo"] is None
    assert document["actor"] is None
    assert document["tags"] == ["deployment", "retry"]
    assert document["text"] == f"Deploy retries\n{LONG_TEXT}"
    assert len(document["doc_id"]) == 64


def test_stackoverflow_exact_text_dedup_keeps_one_copy(tmp_path):
    source = _write_exchange(
        tmp_path / "posts.jsonl",
        [
            _exchange_record("Deploy retries", LONG_TEXT),
            _exchange_record("Deploy retries", LONG_TEXT),
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest_stackoverflow([source], output, sample_size=10, seed=7)

    assert counters["passed_gates"] == 1
    assert counters["skipped_duplicate_text"] == 1
    assert len(_read_jsonl(output)) == 1


def test_stackoverflow_sampling_is_deterministic(tmp_path):
    records = [
        _exchange_record(f"Question {index}", f"{LONG_TEXT} Variant {index}.")
        for index in range(40)
    ]
    source = _write_exchange(tmp_path / "posts.jsonl", records)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    other = tmp_path / "other.jsonl"

    ingest_stackoverflow([source], first, sample_size=10, seed=42)
    ingest_stackoverflow([source], second, sample_size=10, seed=42)
    ingest_stackoverflow([source], other, sample_size=10, seed=43)

    assert first.read_bytes() == second.read_bytes()
    first_texts = {document["text"] for document in _read_jsonl(first)}
    other_texts = {document["text"] for document in _read_jsonl(other)}
    assert len(first_texts) == 10
    assert first_texts != other_texts


def test_reservoir_sample_is_uniform_shape_and_seeded():
    values = list(range(100))
    assert reservoir_sample(values, 10, 5) == reservoir_sample(values, 10, 5)
    assert reservoir_sample(values, 10, 5) != reservoir_sample(values, 10, 6)
    assert len(reservoir_sample(values, 10, 5)) == 10


def test_cli_reports_sample_counters(tmp_path, capsys):
    source = _write_exchange(
        tmp_path / "posts.jsonl", [_exchange_record("Deploy retries", LONG_TEXT)]
    )
    output = tmp_path / "documents.jsonl"

    exit_code = main(
        [
            "stackoverflow",
            "--input",
            str(source),
            "--output",
            str(output),
            "--sample-size",
            "10",
            "--seed",
            "7",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "documents passed:   1 (all gates)" in out
    assert "documents written:  1 (sampled)" in out
    assert "seed:               7" in out


def _write_parquet(path, rows):
    pyarrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    table = pyarrow.table(
        {
            "repository_name": [row["repo"] for row in rows],
            "func_path_in_repository": [row["path"] for row in rows],
            "func_name": [row["name"] for row in rows],
            "func_documentation_string": [row["docstring"] for row in rows],
            "language": [row["language"] for row in rows],
        }
    )
    parquet.write_table(table, path)
    return path


def test_codesearchnet_extracts_docstrings_and_metadata(tmp_path):
    source = _write_parquet(
        tmp_path / "python-train.parquet",
        [
            {
                "repo": "acme/widgets",
                "path": "widgets/cache.py",
                "name": "invalidate",
                "docstring": LONG_TEXT,
                "language": "python",
            },
            {
                "repo": "acme/widgets",
                "path": "widgets/cache.py",
                "name": "short",
                "docstring": "Short.",
                "language": "python",
            },
        ],
    )
    output = tmp_path / "documents-csn.jsonl"

    counters = ingest_codesearchnet([source], output, sample_size=10, seed=7)

    assert counters["records_seen"] == 2
    assert counters["skipped_too_short"] == 1
    assert counters["passed_gates"] == 1

    documents = _read_jsonl(output)
    assert len(documents) == 1
    document = documents[0]
    assert set(document) == {
        "doc_id",
        "source_family",
        "repo",
        "actor",
        "language",
        "text",
    }
    assert document["source_family"] == "codesearchnet"
    assert document["language"] == "python"
    assert document["repo"] == "acme/widgets"
    assert document["text"] == LONG_TEXT


def test_codesearchnet_reads_a_directory_in_sorted_order(tmp_path):
    first = _write_parquet(
        tmp_path / "a-train.parquet",
        [
            {
                "repo": "acme/a",
                "path": "a.py",
                "name": "a",
                "docstring": LONG_TEXT,
                "language": "python",
            }
        ],
    )
    _write_parquet(
        tmp_path / "b-train.parquet",
        [
            {
                "repo": "acme/b",
                "path": "b.py",
                "name": "b",
                "docstring": LONG_TEXT_2,
                "language": "python",
            }
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest_codesearchnet([tmp_path], output, sample_size=10, seed=7)

    assert counters["input_files"] == 2
    assert counters["sampled"] == 2
    assert {doc["repo"] for doc in _read_jsonl(output)} == {"acme/a", "acme/b"}
    assert first.is_file()
