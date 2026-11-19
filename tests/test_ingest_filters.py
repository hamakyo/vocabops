"""Tests for the opt-in bot and English-ratio filters in vocabops.ingest.

The fixtures are written by hand and contain no third-party text.
"""

import json

from wordfreq import word_frequency

from vocabops import ingest as ingest_module
from vocabops import normalize as normalize_module
from vocabops.ingest import (
    BOT_LOGINS,
    ENGLISH_RATIO_MIN_FREQUENCY,
    english_ratio,
    ingest,
    is_bot_actor,
    main,
)

JAPANESE = "キャッシュの無効化パスが壊れています。修正してください。"
CHINESE = "这一项筛选结果不正确，请修复缓存失效的问题。"
# Spanish sentence whose only "English" tokens under the old rule were words
# that wordfreq lists at trace frequencies (código 1.7e-08, validación,
# necesitamos) or that double as English function words (de, y, las).
SPANISH = "Necesitamos revisar el código y las pruebas antes de la validación."
# Spanish sentence that passed the 0.6 document cut at the old shared 3e-07
# floor (8/12 = 0.667) because `esta` is listed at 6.9e-07, and must drop at
# the ingest floor of 1e-06 (7/12 = 0.583). This is the round-8 regression
# fixture: one word between the two floors is enough to flip the decision.
SPANISH_AT_OLD_FLOOR = "Esta rama contiene un error de configuración, hay que revisar el archivo."


def _event(event_id, body, actor=None, event_type="IssueCommentEvent"):
    event = {
        "id": str(event_id),
        "type": event_type,
        "repo": {"name": "acme/widgets"},
        "payload": {"comment": {"body": body}},
    }
    if actor is not None:
        event["actor"] = {"login": actor}
    return event


def _write_events(path, events):
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    return path


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_actor_is_written_and_null_when_absent(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, "Please persist the record before responding.", "octocat"),
            _event(2, "The fallback path needs another test."),
        ],
    )
    output = tmp_path / "documents.jsonl"

    ingest(source, output, max_docs=10)

    documents = _read_jsonl(output)
    assert [doc["actor"] for doc in documents] == ["octocat", None]


def test_is_bot_actor_requires_the_suffix_or_the_named_set():
    assert is_bot_actor("github-actions[bot]") is True
    assert is_bot_actor("coderabbitai[bot]") is True
    assert is_bot_actor("Copilot") is True
    assert "Copilot" in BOT_LOGINS
    # A login that merely contains "bot" is a human account.
    assert is_bot_actor("botanist") is False
    assert is_bot_actor("robotfan") is False
    assert is_bot_actor(None) is False
    assert is_bot_actor("") is False


def test_bot_events_are_kept_without_the_flag(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, "The cache invalidation path is broken.", "github-actions[bot]"),
            _event(2, "We should persist jobs before retrying.", "octocat"),
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10)

    assert counters["documents_written"] == 2
    assert counters["skipped_bot"] == 0
    assert [doc["actor"] for doc in _read_jsonl(output)] == [
        "github-actions[bot]",
        "octocat",
    ]


def test_exclude_bots_skips_suffix_and_copilot_but_not_human_bot_names(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, "Automated review comment.", "github-actions[bot]"),
            _event(2, "Copilot suggestion text.", "Copilot"),
            _event(3, "I planted the botanist module yesterday.", "botanist"),
            _event(4, "This adds a fallback when the call fails.", "octocat"),
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10, exclude_bots=True)

    assert counters["documents_written"] == 2
    assert counters["skipped_bot"] == 2
    documents = _read_jsonl(output)
    assert [doc["actor"] for doc in documents] == ["botanist", "octocat"]


def test_english_ratio_separates_english_from_cjk():
    english = english_ratio("The cache invalidation path is broken.")
    japanese = english_ratio(JAPANESE)
    chinese = english_ratio(CHINESE)

    assert english is not None and english >= 0.8
    # "invalidation" is 1.7e-07 in wordfreq, below the 1e-06 ratio floor, so
    # this sentence scores 5/6 rather than 1.0. It still passes the 0.6
    # document filter comfortably; CJK text stays below 0.1.
    assert japanese is not None and japanese < 0.1
    assert chinese is not None and chinese < 0.1
    assert english_ratio("1234 5678 !!!") is None


def test_english_ratio_floor_is_pinned_to_ingest():
    # The document-level language test has its own constant at 1e-06: it asks
    # "is this token evidence that the document is English?", which is a
    # stricter question than the lemmatizer's "is this a plausible headword?".
    assert ingest_module.ENGLISH_RATIO_MIN_FREQUENCY == 1e-06


def test_english_ratio_floor_is_not_the_lemmatizer_floor():
    # Round 8: sharing the lemmatizer's 3e-07 floor here let 284 French and
    # Spanish documents through the ratio test. The values must stay distinct.
    assert ingest_module.ENGLISH_RATIO_MIN_FREQUENCY > (
        normalize_module.LEMMA_MIN_FREQUENCY
    )
    assert normalize_module.LEMMA_MIN_FREQUENCY == 3e-07


def test_trace_frequency_tokens_no_longer_count_as_english():
    # código is in wordfreq's English list only at its noise floor.
    assert 0 < word_frequency("código", "en") < ENGLISH_RATIO_MIN_FREQUENCY
    # The old "> 0" rule scored this sentence at 0.6 and kept it; the ratio
    # floor scores it at 0.4, below the 0.6 cut.
    spanish_ratio = english_ratio(SPANISH)
    assert spanish_ratio is not None and spanish_ratio < 0.6
    # An ordinary English document still clears the 0.6 filter even though
    # "invalidation" (1.7e-07) is below the floor.
    english = english_ratio("The cache invalidation path is broken.")
    assert english is not None and english >= 0.8


def test_spanish_that_passed_the_old_floor_now_drops(tmp_path):
    # `esta` is 6.9e-07: above the lemmatizer's 3e-07, below the ingest 1e-06.
    assert 3e-07 <= word_frequency("esta", "en") < ENGLISH_RATIO_MIN_FREQUENCY
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, SPANISH_AT_OLD_FLOOR, "octocat"),
            _event(2, "The cache invalidation path is broken.", "octocat"),
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10, min_english_ratio=0.6)

    assert counters["documents_written"] == 1
    assert counters["skipped_language"] == 1
    assert [doc["text"] for doc in _read_jsonl(output)] == [
        "The cache invalidation path is broken."
    ]


def test_english_floor_drops_spanish_and_keeps_english(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, SPANISH, "octocat"),
            _event(2, "The cache invalidation path is broken.", "octocat"),
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10, min_english_ratio=0.6)

    assert counters["documents_written"] == 1
    assert counters["skipped_language"] == 1
    assert counters["skipped_no_tokens"] == 0
    assert [doc["text"] for doc in _read_jsonl(output)] == [
        "The cache invalidation path is broken."
    ]


def test_language_filter_drops_non_english_and_counts_reasons(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, "We should persist jobs before retrying.", "octocat"),
            _event(2, JAPANESE, "octocat"),
            _event(3, "Automated review comment.", "github-actions[bot]"),
            _event(4, "   \n\t ", "octocat"),  # no body
        ],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(
        source, output, max_docs=10, exclude_bots=True, min_english_ratio=0.6
    )

    assert counters["events_seen"] == 4
    assert counters["documents_written"] == 1
    assert counters["skipped_no_body"] == 1
    assert counters["skipped_bot"] == 1
    assert counters["skipped_language"] == 1
    assert counters["skipped_no_tokens"] == 0
    assert [doc["text"] for doc in _read_jsonl(output)] == [
        "We should persist jobs before retrying."
    ]


def test_language_filter_keeps_documents_at_the_threshold(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [_event(1, "Retry logic and fallback paths.", "octocat")],
    )
    output = tmp_path / "documents.jsonl"

    # Threshold 0.0 keeps every document that has alphabetic tokens.
    counters = ingest(source, output, max_docs=10, min_english_ratio=0.0)

    assert counters["documents_written"] == 1


def test_documents_without_alphabetic_tokens_are_skipped_as_empty(tmp_path):
    source = _write_events(
        tmp_path / "events.json",
        [_event(1, "1234 5678 !!! ###", "octocat")],
    )
    output = tmp_path / "documents.jsonl"

    counters = ingest(source, output, max_docs=10, min_english_ratio=0.6)

    assert counters["documents_written"] == 0
    assert counters["skipped_no_tokens"] == 1
    assert counters["skipped_language"] == 0
    assert _read_jsonl(output) == []


def test_cli_summary_reports_each_skip_reason(tmp_path, capsys):
    source = _write_events(
        tmp_path / "events.json",
        [
            _event(1, "We should persist jobs before retrying.", "octocat"),
            _event(2, JAPANESE, "octocat"),
            _event(3, "Automated review comment.", "github-actions[bot]"),
            _event(4, "  ", "octocat"),
        ],
    )
    output = tmp_path / "documents.jsonl"

    exit_code = main(
        [
            "gharchive",
            "--input",
            str(source),
            "--output",
            str(output),
            "--max-docs",
            "10",
            "--exclude-bots",
            "--min-english-ratio",
            "0.6",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "documents written:  1" in out
    assert "1 (no body)" in out
    assert "1 (bot actor)" in out
    assert "1 (below english ratio)" in out


def test_cli_rejects_out_of_range_english_ratio(tmp_path, capsys):
    source = _write_events(tmp_path / "events.json", [_event(1, "hello world")])

    exit_code = main(
        [
            "gharchive",
            "--input",
            str(source),
            "--output",
            str(tmp_path / "out.jsonl"),
            "--min-english-ratio",
            "1.5",
        ]
    )

    assert exit_code == 2
    assert "--min-english-ratio" in capsys.readouterr().err
