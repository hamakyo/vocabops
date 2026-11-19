"""Source adapters that turn raw public datasets into normalized JSONL documents.

The first adapter reads GH Archive event files. Usage::

    python -m vocabops.ingest gharchive \
        --input out/gharchive/2026-11-18-3.json.gz \
        --output out/gharchive/documents.jsonl \
        --max-docs 2000

``--input`` is either a local ``.json.gz`` / ``.json`` file or an http(s) URL
to one. It may be given more than once; the files are then processed in sorted
path order, as one run. Each file is streamed line by line and is never loaded
into memory as one string. Each line is one GitHub event (one JSON object).
Counters and the event-ID / exact-text dedup state span all files, so the run
is independent of the order the ``--input`` flags are given in.

Only events that carry human-written prose become documents:

===============================  ==========================================
event type                       text
===============================  ==========================================
``IssueCommentEvent``            ``payload.comment.body``
``IssuesEvent``                  ``payload.issue.title`` (first line, when
                                 present) then ``payload.issue.body``
``PullRequestEvent``             ``payload.pull_request.title`` (first line,
                                 when present) then
                                 ``payload.pull_request.body``
``PullRequestReviewCommentEvent`` ``payload.comment.body``
``PullRequestReviewEvent``       ``payload.review.body`` (when non-empty)
===============================  ==========================================

Everything else is skipped. Bodies that are empty or whitespace-only are
skipped. Two opt-in ingest filters remove automated and non-English text:

``--exclude-bots``
    Drop documents whose event actor login ends with ``[bot]``, plus the small
    explicit :data:`BOT_LOGINS` set (GitHub's ``Copilot`` account, which has no
    suffix). Off by default; without the flag the output is unchanged apart
    from the added ``actor`` field.

``--min-english-ratio R``
    Drop documents whose share of alphabetic tokens known to ``wordfreq`` as
    English is below ``R`` (0..1). A token counts as English at
    :data:`ENGLISH_RATIO_MIN_FREQUENCY` (1e-06), which is deliberately
    stricter than the lemmatizer's ``LEMMA_MIN_FREQUENCY`` (3e-07): the two
    answer different questions. Documents with no alphabetic tokens are
    skipped as empty. Off by default (``None``).

Filter order is fixed: event-type/body extraction, then bot filter, then
language filter, then event-ID checks, then optional exact-text deduplication.
Each dropped event is counted under exactly one reason.

``--dedup-text``
    Drop a document whose stripped full text is byte-identical to the text of
    a document already kept in this run (``sha256`` of the stripped text; the
    first occurrence in file order wins). Off by default. This is exact
    duplication only: near-duplicates and templated prose that share a long
    prefix but differ in the tail are not detected.

Each output line is one document::

    {"doc_id": ..., "source_family": "gharchive", "repo": ..., "actor": ...,
     "text": ...}

``actor`` is the event actor's login, or ``null`` when absent. ``doc_id`` is
``sha256(source_family + "/" + event id)``, matching the document-identity
rule in ``docs/pipeline-conventions.md``. Event IDs are deduplicated, so a
repeated event produces one document. Ingest stops after ``--max-docs``
documents (default 2000).

The downloaded archive and the generated JSONL are working data. Keep them in
``out/`` or ``/tmp``; neither is committed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import io
import json
import random
import re
import sqlite3
import sys
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from wordfreq import word_frequency

from vocabops.normalize import tokenize

__all__ = [
    "GHARCHIVE_FAMILY",
    "STACKOVERFLOW_FAMILY",
    "CODESEARCHNET_FAMILY",
    "DEFAULT_MAX_DOCS",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_SAMPLE_SEED",
    "DEFAULT_MIN_CHARS",
    "DEFAULT_MIN_ENGLISH_RATIO",
    "USER_AGENT",
    "BOT_LOGIN_SUFFIX",
    "BOT_LOGINS",
    "ENGLISH_RATIO_MIN_FREQUENCY",
    "clean_stackoverflow_text",
    "clean_docstring_text",
    "document_id",
    "english_ratio",
    "extract_document",
    "ingest",
    "ingest_codesearchnet",
    "ingest_many",
    "ingest_stackoverflow",
    "is_bot_actor",
    "iter_event_lines",
    "main",
    "reservoir_sample",
]

GHARCHIVE_FAMILY = "gharchive"
STACKOVERFLOW_FAMILY = "stackoverflow"
CODESEARCHNET_FAMILY = "codesearchnet"
DEFAULT_MAX_DOCS = 2000

# Corpus-expansion sampling design (docs/corpus-sources.md). Each new source
# contributes the same number of documents as the GH Archive day corpus
# (out/gharchive/documents-day-v3.jsonl, 17,390 documents), so that a combined
# ranking differs by source vocabulary rather than by source weight.
DEFAULT_SAMPLE_SIZE = 17_390
DEFAULT_SAMPLE_SEED = 20261118
DEFAULT_MIN_CHARS = 100
DEFAULT_MIN_ENGLISH_RATIO = 0.6
USER_AGENT = "vocabops-ingest/0.1 (+https://github.com/)"
GZIP_MAGIC = b"\x1f\x8b"

# GitHub marks app/automation accounts with a "[bot]" login suffix, but a few
# accounts are bots without it. Copilot is GitHub's Copilot bot account; it is
# listed explicitly so the suffix rule stays the general one.
BOT_LOGIN_SUFFIX = "[bot]"
BOT_LOGINS = frozenset({"Copilot"})

# The document-level language test's floor: a token counts as evidence that the
# document is English only when its wordfreq English frequency is at or above
# this value. It answers a different question from the lemmatizer's
# ``vocabops.normalize.LEMMA_MIN_FREQUENCY`` ("is this candidate a plausible
# headword?", 3e-07) and is deliberately stricter.
#
# The two questions must not share a value. Round 8 measured why: at the
# lemmatizer's 3e-07, wordfreq's English list already counts Spanish and
# French tokens such as ``esta`` 6.9e-07 and ``cette`` 1.8e-07, so the ratio
# test admitted 284 extra FR/ES documents, and non-English rows in the top 500
# rose from 14 to 78. At 1e-06 the test behaved as measured in round 5: every
# Spanish and Portuguese document dropped from the 1-hour corpus.
ENGLISH_RATIO_MIN_FREQUENCY = 1e-06


def document_id(source_family: str, identifier: str) -> str:
    """Stable document ID: sha256 of ``source_family + "/" + identifier``.

    Same formula as :func:`vocabops.pipeline.document_id`; the identifier is
    the source's own event ID rather than a file path.
    """
    digest = hashlib.sha256()
    digest.update(f"{source_family}/{identifier}".encode("utf-8"))
    return digest.hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def extract_document(event: Mapping[str, object]) -> str | None:
    """Return the document text for one GH Archive event, or ``None``.

    A document requires a non-empty body. A title, when present, becomes the
    first line of the text.
    """
    event_type = event.get("type")
    payload = _mapping(event.get("payload"))

    body = ""
    title = ""

    if event_type == "IssueCommentEvent":
        body = _text(_mapping(payload.get("comment")).get("body"))
    elif event_type == "IssuesEvent":
        issue = _mapping(payload.get("issue"))
        body = _text(issue.get("body"))
        title = _text(issue.get("title"))
    elif event_type == "PullRequestEvent":
        pull_request = _mapping(payload.get("pull_request"))
        body = _text(pull_request.get("body"))
        title = _text(pull_request.get("title"))
    elif event_type == "PullRequestReviewCommentEvent":
        body = _text(_mapping(payload.get("comment")).get("body"))
    elif event_type == "PullRequestReviewEvent":
        body = _text(_mapping(payload.get("review")).get("body"))
    else:
        return None

    if not body:
        return None
    return f"{title}\n{body}" if title else body


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in {"http", "https"}


def is_bot_actor(login: str | None) -> bool:
    """Whether an actor login is a known bot account.

    A ``[bot]`` *suffix* marks automation; a login that merely contains
    ``bot`` (``botanist``, ``robotfan``) is a human account and is kept.
    """
    if not login:
        return False
    return login.endswith(BOT_LOGIN_SUFFIX) or login in BOT_LOGINS


@lru_cache(maxsize=None)
def _is_english_word(token: str) -> bool:
    """Whether ``wordfreq`` knows ``token`` as a real English word (cached).

    Uses :data:`ENGLISH_RATIO_MIN_FREQUENCY`, not mere nonzero presence and not
    the lemmatizer's floor: wordfreq lists many Spanish, French and Portuguese
    words at trace frequencies (``código`` 1.7e-08) and also between 3e-07 and
    1e-06 (``esta`` 6.9e-07), and counting those as English let non-English
    documents pass the ratio filter.
    """
    return word_frequency(token, "en") >= ENGLISH_RATIO_MIN_FREQUENCY


def english_ratio(text: str) -> float | None:
    """Share of alphabetic tokens that are real English words.

    A token counts when its wordfreq English frequency is at least
    :data:`ENGLISH_RATIO_MIN_FREQUENCY` (1e-06), a stricter test than the
    lemmatizer's :data:`vocabops.normalize.LEMMA_MIN_FREQUENCY` (3e-07).
    Returns ``None`` when the text has no alphabetic tokens at all, so the
    caller can treat such a document as empty.
    """
    tokens = [token for token in tokenize(text) if token.isalpha()]
    if not tokens:
        return None
    return sum(1 for token in tokens if _is_english_word(token)) / len(tokens)


def _actor_login(event: Mapping[str, object]) -> str | None:
    login = _mapping(event.get("actor")).get("login")
    if isinstance(login, str) and login.strip():
        return login.strip()
    return None


def _iter_lines(reader: object) -> Iterator[str]:
    for raw in reader:  # type: ignore[union-attr]
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace")
        else:
            line = raw
        line = line.strip()
        if line:
            yield line


def iter_event_lines(
    source: str | Path, *, timeout: float = 120.0
) -> Generator[str, None, None]:
    """Yield non-empty JSON lines from a local or remote archive.

    gzip is detected from the leading magic bytes, so the URL does not need a
    ``.gz`` suffix. The stream is consumed line by line.
    """
    source = str(source)
    if _is_url(source):
        request = Request(source, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            yield from _decoded_lines(response)
    else:
        handle = Path(source)
        if not handle.is_file():
            raise FileNotFoundError(f"input not found: {handle}")
        with handle.open("rb") as binary:
            yield from _decoded_lines(binary)


def _decoded_lines(binary: object) -> Iterator[str]:
    buffered = binary if hasattr(binary, "peek") else io.BufferedReader(binary)  # type: ignore[arg-type]
    if buffered.peek(2)[:2] == GZIP_MAGIC:  # type: ignore[union-attr]
        with gzip.GzipFile(fileobj=buffered) as reader:  # type: ignore[arg-type]
            yield from _iter_lines(reader)
    else:
        yield from _iter_lines(buffered)


def _text_digest(text: str) -> str:
    """sha256 of the stripped document text, used for exact-text dedup."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def ingest(
    source: str | Path,
    output_path: Path,
    max_docs: int = DEFAULT_MAX_DOCS,
    source_family: str = GHARCHIVE_FAMILY,
    *,
    exclude_bots: bool = False,
    min_english_ratio: float | None = None,
    dedup_text: bool = False,
) -> dict[str, int]:
    """Stream ``source`` and write up to ``max_docs`` documents to JSONL.

    Returns counters: ``input_files``, ``events_seen``, ``documents_written``,
    ``skipped_no_body``, ``skipped_bot``, ``skipped_language``,
    ``skipped_no_tokens``, ``skipped_duplicate_text``, ``duplicates``,
    ``malformed``, ``missing_id``.

    Filter order is extraction, bot filter, language filter, event-ID checks,
    then optional exact-text deduplication, so every dropped event lands in
    exactly one counter.
    """
    return ingest_many(
        [source],
        output_path,
        max_docs=max_docs,
        source_family=source_family,
        exclude_bots=exclude_bots,
        min_english_ratio=min_english_ratio,
        dedup_text=dedup_text,
    )


def ingest_many(
    sources: Sequence[str | Path],
    output_path: Path,
    max_docs: int = DEFAULT_MAX_DOCS,
    source_family: str = GHARCHIVE_FAMILY,
    *,
    exclude_bots: bool = False,
    min_english_ratio: float | None = None,
    dedup_text: bool = False,
) -> dict[str, int]:
    """Stream several archives as one run, in sorted path order.

    Files are sorted by their string path before reading, so the output and
    the dedup winners do not depend on the order the sources are passed in.
    All counters and both dedup sets span the whole run; ``--max-docs`` caps
    the total number of documents written across all files.
    """
    if max_docs < 0:
        raise ValueError("max_docs must not be negative")
    if min_english_ratio is not None and not 0.0 <= min_english_ratio <= 1.0:
        raise ValueError("min_english_ratio must be between 0 and 1")
    if not sources:
        raise ValueError("at least one input source is required")

    sources = sorted(sources, key=str)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    counters = {
        "input_files": len(sources),
        "events_seen": 0,
        "documents_written": 0,
        "skipped_no_body": 0,
        "skipped_bot": 0,
        "skipped_language": 0,
        "skipped_no_tokens": 0,
        "skipped_duplicate_text": 0,
        "duplicates": 0,
        "malformed": 0,
        "missing_id": 0,
    }
    seen: set[str] = set()
    seen_text: set[str] = set()

    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        if max_docs == 0:
            return counters
        full = False
        for source in sources:
            if full:
                break
            lines = iter_event_lines(source)
            try:
                for line in lines:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        counters["malformed"] += 1
                        continue
                    if not isinstance(event, Mapping):
                        counters["malformed"] += 1
                        continue

                    counters["events_seen"] += 1
                    text = extract_document(event)
                    if text is None:
                        counters["skipped_no_body"] += 1
                        continue

                    actor = _actor_login(event)
                    if exclude_bots and is_bot_actor(actor):
                        counters["skipped_bot"] += 1
                        continue

                    if min_english_ratio is not None:
                        ratio = english_ratio(text)
                        if ratio is None:
                            counters["skipped_no_tokens"] += 1
                            continue
                        if ratio < min_english_ratio:
                            counters["skipped_language"] += 1
                            continue

                    event_id = event.get("id")
                    if event_id is None or str(event_id).strip() == "":
                        counters["missing_id"] += 1
                        continue

                    doc_id = document_id(source_family, str(event_id).strip())
                    if doc_id in seen:
                        counters["duplicates"] += 1
                        continue
                    seen.add(doc_id)

                    if dedup_text:
                        digest = _text_digest(text)
                        if digest in seen_text:
                            counters["skipped_duplicate_text"] += 1
                            continue
                        seen_text.add(digest)

                    record = {
                        "doc_id": doc_id,
                        "source_family": source_family,
                        "repo": _mapping(event.get("repo")).get("name") or None,
                        "actor": actor,
                        "text": text,
                    }
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    counters["documents_written"] += 1
                    if counters["documents_written"] >= max_docs:
                        full = True
                        break
            finally:
                # Close the generator so the gzip reader and any HTTP response
                # are released even when we stop early at --max-docs.
                lines.close()

    return counters


# --- corpus-expansion adapters -------------------------------------------
#
# Stack Overflow (flax-sentence-embeddings/stackexchange_title_body_jsonl) and
# CodeSearchNet (code-search-net/code_search_net) feed the Phase 1 combined
# corpus. Both adapters follow the GH Archive conventions above: stream the
# source, count every drop under exactly one reason, and write JSONL documents
# with ``doc_id``/``source_family``/``repo``/``actor``/``text``.
#
# Unlike the GH adapter, these adapters sample: each source contributes exactly
# ``DEFAULT_SAMPLE_SIZE`` documents (parity with the 17,390-document GH Archive
# day corpus). Gate order is extraction, minimum cleaned length, English ratio,
# exact-text dedup, then reservoir sampling. Exact-text dedup uses a temporary
# SQLite index because the sources have millions of rows; a Python set of every
# digest would not fit in memory. The first occurrence in fixed file order wins,
# so the result is deterministic.

_CODE_BLOCK_RE = re.compile(r"<pre\b[^>]*>.*?</pre\s*>", re.IGNORECASE | re.DOTALL)
_INLINE_CODE_TAG_RE = re.compile(
    r"<code\b[^>]*>.*?</code\s*>", re.IGNORECASE | re.DOTALL
)
_FENCE_RE = re.compile(r"(?:```|~~~).*?(?:(?:```|~~~)|\Z)", re.DOTALL)
_MARKUP_TAG_RE = re.compile(r"<[^>]+>")
_MARKUP_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EXTRA_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_markup(text: str) -> str:
    """Unescape HTML, drop code blocks/tags/URLs, and collapse blank lines.

    Stack Exchange redistribution text stores markup HTML-escaped
    (``&lt;pre&gt;``), so unescaping runs before the block patterns. Code
    blocks that reached the redistribution without markup cannot be identified
    and remain in the text; the real-run report records how often that happens.
    """
    text = html.unescape(text)
    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_TAG_RE.sub(" ", text)
    text = _FENCE_RE.sub(" ", text)
    text = _MARKUP_TAG_RE.sub(" ", text)
    text = _MARKUP_URL_RE.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n", "\n", text)
    text = re.sub(r"\n +", "\n", text)
    text = _EXTRA_BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def clean_stackoverflow_text(text: str) -> str:
    """Clean one Stack Overflow title or body for the corpus."""
    return _strip_markup(text)


def clean_docstring_text(text: str) -> str:
    """Clean one CodeSearchNet docstring for the corpus."""
    return _strip_markup(text)


def reservoir_sample(
    values: Iterable[object], size: int, seed: int
) -> list[object]:
    """Uniform reservoir sample of ``size`` items from a stream (Algorithm R).

    The input is consumed once. A fixed ``seed`` makes the selection
    reproducible; the caller sorts the result by document ID before writing, so
    output bytes do not depend on reservoir slot order.
    """
    if size < 0:
        raise ValueError("sample size must not be negative")
    rng = random.Random(seed)
    reservoir: list[object] = []
    for index, value in enumerate(values):
        if index < size:
            reservoir.append(value)
        else:
            slot = rng.randrange(index + 1)
            if slot < size:
                reservoir[slot] = value
    return reservoir


class _DedupIndex:
    """Disk-backed exact-text dedup index.

    A SQLite primary key on the 16-byte text digest keeps memory bounded while
    streaming millions of documents. ``seen`` returns ``True`` when the digest
    was already inserted, so the first occurrence in stream order wins.
    """

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self._path = path
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA cache_size=-65536")
        self._connection.execute("PRAGMA temp_store=FILE")
        self._connection.execute(
            "CREATE TABLE seen (digest BLOB PRIMARY KEY) WITHOUT ROWID"
        )
        self._pending = 0

    def seen(self, digest: bytes) -> bool:
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO seen (digest) VALUES (?)", (digest,)
        )
        duplicate = cursor.rowcount == 0
        self._pending += 1
        if self._pending >= 10_000:
            self._connection.commit()
            self._pending = 0
        return duplicate

    def close(self) -> None:
        self._connection.commit()
        self._connection.close()
        self._path.unlink(missing_ok=True)


def _text_digest_bytes(text: str) -> bytes:
    return hashlib.blake2b(text.strip().encode("utf-8"), digest_size=16).digest()


def _passes_gates(
    text: str,
    counters: dict[str, int],
    min_chars: int,
    min_english_ratio: float,
) -> bool:
    """Apply the empty, length and English-ratio gates in fixed order.

    Each rejection increments exactly one counter. Shared by the sequential
    adapter path and the parallel real-run harness so both see the same gates.
    """
    text = text.strip()
    if not text:
        counters["skipped_empty"] += 1
        return False
    if len(text) < min_chars:
        counters["skipped_too_short"] += 1
        return False

    ratio = english_ratio(text)
    if ratio is None:
        counters["skipped_no_tokens"] += 1
        return False
    if ratio < min_english_ratio:
        counters["skipped_language"] += 1
        return False
    return True


def _sample_to_jsonl(
    records: Iterable[dict[str, object]],
    output_path: Path,
    counters: dict[str, int],
    *,
    sample_size: int,
    seed: int,
    min_chars: int,
    min_english_ratio: float,
) -> dict[str, int]:
    """Apply the shared gates, sample, and write one JSONL document per line."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dedup = _DedupIndex(output_path.with_name(output_path.name + ".dedup.sqlite"))
    reservoir: list[dict[str, object]] = []
    rng = random.Random(seed)
    try:
        for record in records:
            text = str(record.get("text") or "").strip()
            if not _passes_gates(text, counters, min_chars, min_english_ratio):
                continue

            if dedup.seen(_text_digest_bytes(text)):
                counters["skipped_duplicate_text"] += 1
                continue

            counters["passed_gates"] += 1
            record["text"] = text
            index = counters["passed_gates"] - 1
            if index < sample_size:
                reservoir.append(record)
            else:
                slot = rng.randrange(index + 1)
                if slot < sample_size:
                    reservoir[slot] = record
    finally:
        dedup.close()

    reservoir.sort(key=lambda item: str(item["doc_id"]))
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in reservoir:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    counters["sampled"] = len(reservoir)
    counters["sample_size"] = sample_size
    return counters


def _iter_stackoverflow_records(
    sources: Sequence[str | Path], counters: dict[str, int]
) -> Iterator[dict[str, object]]:
    for source in sorted(sources, key=str):
        lines = iter_event_lines(source)
        try:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    counters["malformed"] += 1
                    continue
                if not isinstance(record, Mapping):
                    counters["malformed"] += 1
                    continue

                counters["records_seen"] += 1
                texts = record.get("texts")
                if not isinstance(texts, list) or not texts:
                    counters["skipped_empty"] += 1
                    continue
                cleaned = [
                    clean_stackoverflow_text(value)
                    for value in texts
                    if isinstance(value, str)
                ]
                text = "\n".join(part for part in cleaned if part).strip()
                if not text:
                    counters["skipped_empty"] += 1
                    continue

                tags_value = record.get("tags")
                tags = (
                    [tag for tag in tags_value if isinstance(tag, str)]
                    if isinstance(tags_value, list)
                    else []
                )
                identifier = _text_digest_bytes(text).hex()
                yield {
                    "doc_id": document_id(STACKOVERFLOW_FAMILY, identifier),
                    "source_family": STACKOVERFLOW_FAMILY,
                    "repo": None,
                    "actor": None,
                    "tags": tags,
                    "text": text,
                }
        finally:
            lines.close()


def ingest_stackoverflow(
    sources: Sequence[str | Path],
    output_path: Path,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SAMPLE_SEED,
    min_chars: int = DEFAULT_MIN_CHARS,
    min_english_ratio: float = DEFAULT_MIN_ENGLISH_RATIO,
) -> dict[str, int]:
    """Stream Stack Exchange posts and write a deterministic sample as JSONL.

    The input is the ``texts``/``tags`` JSONL redistribution: ``texts[0]`` is
    the question title and ``texts[1:]`` the body. Documents are
    ``title + "\\n" + body``. One document per post.
    """
    if sample_size < 0:
        raise ValueError("sample_size must not be negative")
    if not sources:
        raise ValueError("at least one input source is required")
    if not 0.0 <= min_english_ratio <= 1.0:
        raise ValueError("min_english_ratio must be between 0 and 1")

    counters = {
        "input_files": len(sources),
        "records_seen": 0,
        "skipped_empty": 0,
        "skipped_too_short": 0,
        "skipped_language": 0,
        "skipped_no_tokens": 0,
        "skipped_duplicate_text": 0,
        "passed_gates": 0,
        "sampled": 0,
        "malformed": 0,
    }
    records = _iter_stackoverflow_records(sources, counters)
    return _sample_to_jsonl(
        records,
        Path(output_path),
        counters,
        sample_size=sample_size,
        seed=seed,
        min_chars=min_chars,
        min_english_ratio=min_english_ratio,
    )


def _resolve_parquet_sources(sources: Sequence[str | Path]) -> list[Path]:
    paths: list[Path] = []
    for source in sources:
        path = Path(source)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.parquet")))
        elif path.is_file():
            paths.append(path)
        else:
            raise FileNotFoundError(f"input not found: {path}")
    if not paths:
        raise FileNotFoundError("no .parquet files found in the given inputs")
    return sorted(paths, key=str)


def _iter_codesearchnet_records(
    paths: Sequence[Path], counters: dict[str, int]
) -> Iterator[dict[str, object]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised by CLI only
        raise RuntimeError(
            "the codesearchnet adapter needs pyarrow; install it with "
            "`pip install -e \".[ingest]\"`"
        ) from exc

    columns = [
        "repository_name",
        "func_path_in_repository",
        "func_name",
        "func_documentation_string",
        "language",
    ]
    for path in paths:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4096, columns=columns):
            data = batch.to_pydict()
            for row_index in range(batch.num_rows):
                counters["records_seen"] += 1
                docstring = data["func_documentation_string"][row_index]
                if not isinstance(docstring, str):
                    counters["skipped_empty"] += 1
                    continue
                text = clean_docstring_text(docstring)
                if not text:
                    counters["skipped_empty"] += 1
                    continue

                repository = data["repository_name"][row_index] or ""
                func_path = data["func_path_in_repository"][row_index] or ""
                func_name = data["func_name"][row_index] or ""
                language = data["language"][row_index] or path.name.split("-")[0]
                identifier = f"{repository}/{func_path}#{func_name}"
                if identifier.strip("#/") == "":
                    identifier = f"{path.name}/{row_index}"
                yield {
                    "doc_id": document_id(CODESEARCHNET_FAMILY, identifier),
                    "source_family": CODESEARCHNET_FAMILY,
                    "repo": repository or None,
                    "actor": None,
                    "language": language,
                    "text": text,
                }


def ingest_codesearchnet(
    sources: Sequence[str | Path],
    output_path: Path,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SAMPLE_SEED,
    min_chars: int = DEFAULT_MIN_CHARS,
    min_english_ratio: float = DEFAULT_MIN_ENGLISH_RATIO,
) -> dict[str, int]:
    """Stream CodeSearchNet train parquet files and write a sample as JSONL.

    The document text is ``func_documentation_string`` (the docstring). The
    programming language is recorded in ``language`` and the source repository
    in ``repo``. Files are read in sorted path order, one parquet batch at a
    time.
    """
    if sample_size < 0:
        raise ValueError("sample_size must not be negative")
    if not 0.0 <= min_english_ratio <= 1.0:
        raise ValueError("min_english_ratio must be between 0 and 1")

    paths = _resolve_parquet_sources(sources)
    counters = {
        "input_files": len(paths),
        "records_seen": 0,
        "skipped_empty": 0,
        "skipped_too_short": 0,
        "skipped_language": 0,
        "skipped_no_tokens": 0,
        "skipped_duplicate_text": 0,
        "passed_gates": 0,
        "sampled": 0,
        "malformed": 0,
    }
    records = _iter_codesearchnet_records(paths, counters)
    return _sample_to_jsonl(
        records,
        Path(output_path),
        counters,
        sample_size=sample_size,
        seed=seed,
        min_chars=min_chars,
        min_english_ratio=min_english_ratio,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vocabops.ingest",
        description="Convert public source datasets into JSONL documents.",
    )
    subparsers = parser.add_subparsers(dest="source", required=True)

    gharchive = subparsers.add_parser(
        "gharchive", help="GH Archive hourly event files (.json.gz or .json)"
    )
    gharchive.add_argument(
        "--input",
        required=True,
        action="append",
        dest="inputs",
        metavar="PATH",
        help=(
            "local .json.gz/.json path or http(s) URL; repeat for several files, "
            "which are processed as one run in sorted path order"
        ),
    )
    gharchive.add_argument(
        "--output",
        required=True,
        type=Path,
        help="path of the JSONL file to write",
    )
    gharchive.add_argument(
        "--max-docs",
        type=int,
        default=DEFAULT_MAX_DOCS,
        help=f"stop after this many documents (default: {DEFAULT_MAX_DOCS})",
    )
    gharchive.add_argument(
        "--exclude-bots",
        action="store_true",
        help="skip events whose actor login ends with [bot] or is a known bot",
    )
    gharchive.add_argument(
        "--min-english-ratio",
        type=float,
        default=None,
        metavar="R",
        help="skip documents whose English token share is below R (0..1); off by default",
    )
    gharchive.add_argument(
        "--dedup-text",
        action="store_true",
        help="skip documents whose full text exactly matches an already-kept document",
    )

    def add_sample_arguments(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--input",
            required=True,
            action="append",
            dest="inputs",
            metavar="PATH",
            help=(
                "local source path or http(s) URL; repeat for several files, "
                "which are processed as one run in sorted path order"
            ),
        )
        subparser.add_argument(
            "--output",
            required=True,
            type=Path,
            help="path of the sampled JSONL file to write",
        )
        subparser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help=f"reservoir sample size (default: {DEFAULT_SAMPLE_SIZE})",
        )
        subparser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SAMPLE_SEED,
            help=f"reservoir sampling seed (default: {DEFAULT_SAMPLE_SEED})",
        )
        subparser.add_argument(
            "--min-chars",
            type=int,
            default=DEFAULT_MIN_CHARS,
            help=f"drop cleaned text shorter than this (default: {DEFAULT_MIN_CHARS})",
        )
        subparser.add_argument(
            "--min-english-ratio",
            type=float,
            default=DEFAULT_MIN_ENGLISH_RATIO,
            metavar="R",
            help=(
                "drop documents whose English token share is below R (0..1) "
                f"(default: {DEFAULT_MIN_ENGLISH_RATIO})"
            ),
        )

    stackoverflow = subparsers.add_parser(
        "stackoverflow",
        help="Stack Exchange posts JSONL (texts/tags), sampled",
    )
    add_sample_arguments(stackoverflow)

    codesearchnet = subparsers.add_parser(
        "codesearchnet",
        help="CodeSearchNet train parquet docstrings, sampled",
    )
    add_sample_arguments(codesearchnet)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.source == "gharchive":
        if args.max_docs < 0:
            print("error: --max-docs must not be negative", file=sys.stderr)
            return 2
        if args.min_english_ratio is not None and not 0.0 <= args.min_english_ratio <= 1.0:
            print("error: --min-english-ratio must be between 0 and 1", file=sys.stderr)
            return 2
        try:
            counters = ingest_many(
                args.inputs,
                args.output,
                max_docs=args.max_docs,
                exclude_bots=args.exclude_bots,
                min_english_ratio=args.min_english_ratio,
                dedup_text=args.dedup_text,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:  # network and gzip failures
            print(
                f"error: could not read {', '.join(args.inputs)}: {exc}", file=sys.stderr
            )
            return 2

        print(f"input files:        {counters['input_files']}")
        print(f"events seen:        {counters['events_seen']}")
        print(f"documents written:  {counters['documents_written']}")
        print(f"documents skipped:  {counters['skipped_no_body']} (no body)")
        if args.exclude_bots:
            print(f"skipped:            {counters['skipped_bot']} (bot actor)")
        if args.min_english_ratio is not None:
            print(f"skipped:            {counters['skipped_language']} (below english ratio)")
            if counters["skipped_no_tokens"]:
                print(f"skipped:            {counters['skipped_no_tokens']} (no alphabetic tokens)")
        if args.dedup_text:
            print(f"skipped:            {counters['skipped_duplicate_text']} (duplicate text)")
        if counters["duplicates"]:
            print(f"duplicates skipped: {counters['duplicates']}")
        if counters["missing_id"]:
            print(f"missing event id:   {counters['missing_id']}")
        if counters["malformed"]:
            print(f"malformed lines:    {counters['malformed']}")
        print(f"output:             {args.output}")
        return 0

    if args.sample_size < 0:
        print("error: --sample-size must not be negative", file=sys.stderr)
        return 2
    if args.min_chars < 0:
        print("error: --min-chars must not be negative", file=sys.stderr)
        return 2
    if not 0.0 <= args.min_english_ratio <= 1.0:
        print("error: --min-english-ratio must be between 0 and 1", file=sys.stderr)
        return 2

    try:
        if args.source == "stackoverflow":
            counters = ingest_stackoverflow(
                args.inputs,
                args.output,
                sample_size=args.sample_size,
                seed=args.seed,
                min_chars=args.min_chars,
                min_english_ratio=args.min_english_ratio,
            )
        else:
            counters = ingest_codesearchnet(
                args.inputs,
                args.output,
                sample_size=args.sample_size,
                seed=args.seed,
                min_chars=args.min_chars,
                min_english_ratio=args.min_english_ratio,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # network, gzip and parquet failures
        print(
            f"error: could not read {', '.join(args.inputs)}: {exc}", file=sys.stderr
        )
        return 2

    print(f"input files:        {counters['input_files']}")
    print(f"records seen:       {counters['records_seen']}")
    print(f"documents passed:   {counters['passed_gates']} (all gates)")
    print(f"documents written:  {counters['sampled']} (sampled)")
    print(f"skipped:            {counters['skipped_empty']} (empty)")
    print(f"skipped:            {counters['skipped_too_short']} (under min chars)")
    print(f"skipped:            {counters['skipped_language']} (below english ratio)")
    if counters["skipped_no_tokens"]:
        print(f"skipped:            {counters['skipped_no_tokens']} (no alphabetic tokens)")
    print(f"skipped:            {counters['skipped_duplicate_text']} (duplicate text)")
    if counters["malformed"]:
        print(f"malformed lines:    {counters['malformed']}")
    print(f"sample:             {counters['sampled']} of {counters['sample_size']} requested")
    print(f"seed:               {args.seed}")
    print(f"output:             {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
