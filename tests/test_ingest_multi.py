"""Tests for multi-file GH Archive ingest / ``--input`` given several times.

The fixtures are written by hand and contain no third-party text.
"""

import json

from vocabops.ingest import document_id, ingest_many, main

SHARED_BODY = "Retry logic should persist jobs before responding."

# ``part-a`` and ``part-b`` are sorted by path, so part-a is read first even
# when the CLI receives part-b first.
PART_A = [
    {
        "id": "3001",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": "The cache invalidation path is broken."}},
    },
    {
        "id": "3002",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": SHARED_BODY}},
    },
    {
        "id": "3003",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": "   \n\t "}},
    },
    # Duplicate event ID across files: the part-b copy must be dropped.
    {
        "id": "3004",
        "type": "IssuesEvent",
        "repo": {"name": "acme/api"},
        "payload": {"issue": {"title": "Add fallback path", "body": "A fallback path."}},
    },
]

PART_B = [
    {
        "id": "3004",
        "type": "IssuesEvent",
        "repo": {"name": "acme/api"},
        "payload": {"issue": {"title": "Add fallback path", "body": "A fallback path."}},
    },
    # Different event ID, byte-identical text: only --dedup-text drops it.
    {
        "id": "3005",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": SHARED_BODY}},
    },
    {
        "id": "3006",
        "type": "PullRequestReviewCommentEvent",
        "repo": {"name": "acme/api"},
        "payload": {"comment": {"body": "Please propagate the error upward."}},
    },
]


def _write(path, events):
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    return path


def _fixtures(tmp_path):
    return (
        _write(tmp_path / "part-a.json", PART_A),
        _write(tmp_path / "part-b.json", PART_B),
    )


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_events_split_across_files_are_all_ingested(tmp_path):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    counters = ingest_many([first, second], output, max_docs=100)

    assert counters["input_files"] == 2
    assert counters["events_seen"] == len(PART_A) + len(PART_B)
    assert counters["skipped_no_body"] == 1
    # 3004 appears once in each file.
    assert counters["duplicates"] == 1
    assert counters["documents_written"] == 5
    assert [doc["doc_id"] for doc in _read_jsonl(output)] == [
        document_id("gharchive", event_id)
        for event_id in ("3001", "3002", "3004", "3005", "3006")
    ]


def test_doc_id_seen_in_both_files_is_written_once(tmp_path):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    ingest_many([first, second], output, max_docs=100)

    doc_ids = [doc["doc_id"] for doc in _read_jsonl(output)]
    assert doc_ids.count(document_id("gharchive", "3004")) == 1
    # The first file in sorted order wins; both copies are identical here.
    assert [doc["repo"] for doc in _read_jsonl(output)].count("acme/api") == 2


def test_dedup_text_spans_files_and_keeps_the_first(tmp_path):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    counters = ingest_many([first, second], output, max_docs=100, dedup_text=True)

    assert counters["documents_written"] == 4
    assert counters["skipped_duplicate_text"] == 1
    assert counters["duplicates"] == 1
    documents = _read_jsonl(output)
    assert [doc["doc_id"] for doc in documents] == [
        document_id("gharchive", event_id)
        for event_id in ("3001", "3002", "3004", "3006")
    ]
    assert [doc["text"] for doc in documents].count(SHARED_BODY) == 1


def test_counters_aggregate_across_files(tmp_path):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    counters = ingest_many(
        [first, second],
        output,
        max_docs=100,
        min_english_ratio=0.6,
        dedup_text=True,
    )

    # Every event lands in exactly one counter, across both files.
    assert sum(
        counters[key]
        for key in (
            "documents_written",
            "skipped_no_body",
            "skipped_bot",
            "skipped_language",
            "skipped_no_tokens",
            "skipped_duplicate_text",
            "duplicates",
            "missing_id",
        )
    ) == counters["events_seen"]
    assert counters["events_seen"] == 7
    assert counters["documents_written"] == 4


def test_input_order_does_not_change_output(tmp_path):
    first, second = _fixtures(tmp_path)
    forward = tmp_path / "forward.jsonl"
    reversed_order = tmp_path / "reversed.jsonl"

    ingest_many([first, second], forward, max_docs=100, dedup_text=True)
    second_counters = ingest_many(
        [second, first], reversed_order, max_docs=100, dedup_text=True
    )

    assert forward.read_bytes() == reversed_order.read_bytes()
    assert second_counters["documents_written"] == 4


def test_max_docs_caps_the_total_across_files(tmp_path):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    counters = ingest_many([first, second], output, max_docs=2)

    assert counters["documents_written"] == 2
    assert len(_read_jsonl(output)) == 2
    assert counters["events_seen"] == 2  # stops before reading part-b


def test_cli_accepts_repeated_input_and_reports_file_count(tmp_path, capsys):
    first, second = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    exit_code = main(
        [
            "gharchive",
            "--input",
            str(second),
            "--input",
            str(first),
            "--output",
            str(output),
            "--max-docs",
            "100",
            "--dedup-text",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "input files:        2" in out
    assert "events seen:        7" in out
    assert "documents written:  4" in out
    assert "skipped:            1 (duplicate text)" in out
    assert _read_jsonl(output)[0]["doc_id"] == document_id("gharchive", "3001")


def test_cli_single_input_still_reports_one_file(tmp_path, capsys):
    first, _ = _fixtures(tmp_path)
    output = tmp_path / "documents.jsonl"

    exit_code = main(
        ["gharchive", "--input", str(first), "--output", str(output), "--max-docs", "100"]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "input files:        1" in out
    assert "documents written:  3" in out
