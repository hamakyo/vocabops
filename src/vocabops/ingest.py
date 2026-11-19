"""Source adapters that turn raw public datasets into normalized JSONL documents.

The first adapter reads GH Archive event files. Usage::

    python -m vocabops.ingest gharchive \
        --input out/gharchive/2026-11-18-3.json.gz \
        --output out/gharchive/documents.jsonl \
        --max-docs 2000

``--input`` is either a local ``.json.gz`` / ``.json`` file or an http(s) URL
to one. The file is streamed line by line; it is never loaded into memory as
one string. Each line is one GitHub event (one JSON object).

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
    English is below ``R`` (0..1). Documents with no alphabetic tokens are
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
import io
import json
import sys
from collections.abc import Generator, Iterator, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from wordfreq import word_frequency

from vocabops.normalize import ENGLISH_WORD_MIN_FREQUENCY, tokenize

__all__ = [
    "GHARCHIVE_FAMILY",
    "DEFAULT_MAX_DOCS",
    "USER_AGENT",
    "BOT_LOGIN_SUFFIX",
    "BOT_LOGINS",
    "ENGLISH_WORD_MIN_FREQUENCY",
    "document_id",
    "english_ratio",
    "extract_document",
    "ingest",
    "is_bot_actor",
    "iter_event_lines",
    "main",
]

GHARCHIVE_FAMILY = "gharchive"
DEFAULT_MAX_DOCS = 2000
USER_AGENT = "vocabops-ingest/0.1 (+https://github.com/)"
GZIP_MAGIC = b"\x1f\x8b"

# GitHub marks app/automation accounts with a "[bot]" login suffix, but a few
# accounts are bots without it. Copilot is GitHub's Copilot bot account; it is
# listed explicitly so the suffix rule stays the general one.
BOT_LOGIN_SUFFIX = "[bot]"
BOT_LOGINS = frozenset({"Copilot"})


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

    Uses the shared :data:`vocabops.normalize.ENGLISH_WORD_MIN_FREQUENCY`
    floor, not mere nonzero presence: wordfreq lists many Spanish and
    Portuguese words at trace frequencies (``código`` 1.7e-08), and counting
    those as English let non-English documents pass the ratio filter.
    """
    return word_frequency(token, "en") >= ENGLISH_WORD_MIN_FREQUENCY


def english_ratio(text: str) -> float | None:
    """Share of alphabetic tokens that are real English words.

    A token counts when its wordfreq English frequency is at least
    :data:`ENGLISH_WORD_MIN_FREQUENCY`. Returns ``None`` when the text has no
    alphabetic tokens at all, so the caller can treat such a document as empty.
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

    Returns counters: ``events_seen``, ``documents_written``,
    ``skipped_no_body``, ``skipped_bot``, ``skipped_language``,
    ``skipped_no_tokens``, ``skipped_duplicate_text``, ``duplicates``,
    ``malformed``, ``missing_id``.

    Filter order is extraction, bot filter, language filter, event-ID checks,
    then optional exact-text deduplication, so every dropped event lands in
    exactly one counter.
    """
    if max_docs < 0:
        raise ValueError("max_docs must not be negative")
    if min_english_ratio is not None and not 0.0 <= min_english_ratio <= 1.0:
        raise ValueError("min_english_ratio must be between 0 and 1")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    counters = {
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
                    break
        finally:
            # Close the generator so the gzip reader and any HTTP response are
            # released even when we stop early at --max-docs.
            lines.close()

    return counters


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
        help="local .json.gz/.json path or http(s) URL",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_docs < 0:
        print("error: --max-docs must not be negative", file=sys.stderr)
        return 2
    if args.min_english_ratio is not None and not 0.0 <= args.min_english_ratio <= 1.0:
        print("error: --min-english-ratio must be between 0 and 1", file=sys.stderr)
        return 2
    try:
        counters = ingest(
            args.input,
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
        print(f"error: could not read {args.input}: {exc}", file=sys.stderr)
        return 2

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


if __name__ == "__main__":
    raise SystemExit(main())
