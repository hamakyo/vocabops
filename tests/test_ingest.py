"""Tests for vocabops.ingest using a hand-written GH Archive fixture."""

import gzip
import hashlib
import json

from vocabops.ingest import document_id, extract_document, ingest, main

# A tiny synthetic GH Archive hour. Written by hand; not real event data.
EVENTS = [
    {
        "id": "1001",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": "The cache invalidation path is broken."}},
    },
    {
        "id": "1002",
        "type": "IssuesEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {
            "issue": {
                "title": "Retry logic",
                "body": "We should persist jobs before retrying.",
            }
        },
    },
    {
        "id": "1003",
        "type": "PullRequestEvent",
        "repo": {"name": "acme/api"},
        "payload": {
            "pull_request": {
                "title": "Add fallback path",
                "body": "This adds a fallback when the primary call fails.",
            }
        },
    },
    {
        "id": "1004",
        "type": "PullRequestReviewCommentEvent",
        "repo": {"name": "acme/api"},
        "payload": {"comment": {"body": "Please propagate the error upward."}},
    },
    {
        "id": "1005",
        "type": "PushEvent",
        "repo": {"name": "acme/api"},
        "payload": {"commits": [{"message": "fix: stuff"}]},
    },
    # Duplicate of event 1001: same top-level id, must be deduplicated.
    {
        "id": "1001",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": "The cache invalidation path is broken."}},
    },
    {
        "id": "1006",
        "type": "IssueCommentEvent",
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": "   \n\t "}},
    },
    {
        "id": "1007",
        "type": "PullRequestReviewEvent",
        "repo": {"name": "acme/api"},
        "payload": {"review": {"body": ""}},
    },
    {
        "id": "1008",
        "type": "PullRequestReviewEvent",
        "repo": {"name": "acme/api"},
        "payload": {"review": {"body": "Reproduce the bug before merging."}},
    },
]

EXPECTED_TEXTS = {
    "1001": "The cache invalidation path is broken.",
    "1002": "Retry logic\nWe should persist jobs before retrying.",
    "1003": "Add fallback path\nThis adds a fallback when the primary call fails.",
    "1004": "Please propagate the error upward.",
    "1008": "Reproduce the bug before merging.",
}


def _write_events(path, events=EVENTS, gzipped=False):
    payload = "".join(json.dumps(event) + "\n" for event in events).encode("utf-8")
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


def test_document_id_is_sha256_of_family_and_event_id():
    expected = hashlib.sha256(b"gharchive/1001").hexdigest()
    assert document_id("gharchive", "1001") == expected
    assert len(expected) == 64


def test_extract_document_covers_supported_event_types():
    by_id = {event["id"]: extract_document(event) for event in EVENTS}
    for event_id, text in EXPECTED_TEXTS.items():
        assert by_id[event_id] == text, event_id


def test_extract_document_skips_unsupported_and_empty_bodies():
    assert extract_document(EVENTS[4]) is None  # PushEvent
    assert extract_document(EVENTS[6]) is None  # whitespace-only body
    assert extract_document(EVENTS[7]) is None  # empty review body
    assert extract_document({"id": "1", "type": "IssuesEvent"}) is None
    assert extract_document({"id": "1", "type": "IssuesEvent", "payload": {}}) is None


def test_ingest_extracts_deduplicates_and_skips(tmp_path):
    source = _write_events(tmp_path / "events.json")
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=100)

    assert counters["events_seen"] == len(EVENTS)
    assert counters["documents_written"] == len(EXPECTED_TEXTS)
    assert counters["skipped_no_body"] == 3
    assert counters["duplicates"] == 1
    assert counters["malformed"] == 0

    documents = _read_jsonl(output)
    assert [doc["doc_id"] for doc in documents] == [
        document_id("gharchive", event_id) for event_id in EXPECTED_TEXTS
    ]
    assert [doc["text"] for doc in documents] == list(EXPECTED_TEXTS.values())
    assert set(documents[0]) == {"doc_id", "source_family", "repo", "text"}
    assert all(doc["source_family"] == "gharchive" for doc in documents)
    assert documents[0]["repo"] == "acme/widgets"


def test_ingest_doc_ids_are_stable_across_runs(tmp_path):
    source = _write_events(tmp_path / "events.json")
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    ingest(source, first, max_docs=100)
    ingest(source, second, max_docs=100)

    assert first.read_bytes() == second.read_bytes()
    assert [doc["doc_id"] for doc in _read_jsonl(first)] == [
        document_id("gharchive", event_id) for event_id in EXPECTED_TEXTS
    ]


def test_ingest_reads_gzipped_input(tmp_path):
    source = _write_events(tmp_path / "events.json.gz", gzipped=True)
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=100)

    assert counters["documents_written"] == len(EXPECTED_TEXTS)
    assert output.is_file()


def test_ingest_respects_max_docs(tmp_path):
    source = _write_events(tmp_path / "events.json")
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=2)

    documents = _read_jsonl(output)
    assert counters["documents_written"] == 2
    assert len(documents) == 2
    assert [doc["text"] for doc in documents] == list(EXPECTED_TEXTS.values())[:2]


def test_ingest_handles_missing_repo_and_malformed_lines(tmp_path):
    source = tmp_path / "events.json"
    source.write_text(
        '{"id": "1", "type": "IssueCommentEvent", '
        '"payload": {"comment": {"body": "No repo key here."}}}\n'
        "not json\n",
        encoding="utf-8",
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10)

    assert counters["documents_written"] == 1
    assert counters["malformed"] == 1
    documents = _read_jsonl(output)
    assert documents[0]["repo"] is None
    assert documents[0]["text"] == "No repo key here."


def test_cli_prints_summary(tmp_path, capsys):
    source = _write_events(tmp_path / "events.json.gz", gzipped=True)
    output = tmp_path / "documents.jsonl"

    exit_code = main(
        ["gharchive", "--input", str(source), "--output", str(output), "--max-docs", "100"]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"events seen:        {len(EVENTS)}" in out
    assert "documents written:  5" in out
    assert "documents skipped:  3 (no body)" in out
    assert output.is_file()


def test_cli_rejects_missing_input(tmp_path, capsys):
    exit_code = main(
        [
            "gharchive",
            "--input",
            str(tmp_path / "nope.json.gz"),
            "--output",
            str(tmp_path / "documents.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "input not found" in capsys.readouterr().err


def test_cli_rejects_negative_max_docs(tmp_path, capsys):
    source = _write_events(tmp_path / "events.json")

    exit_code = main(
        ["gharchive", "--input", str(source), "--output", str(tmp_path / "out.jsonl"), "--max-docs", "-1"]
    )

    assert exit_code == 2
    assert "--max-docs" in capsys.readouterr().err
