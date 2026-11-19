"""Corpus statistics for the VocabOps prototype.

Term frequency
    ``tf`` is the number of lemma occurrences across all documents in the
    corpus. Documents are lists of normalized lemmas (see
    :mod:`vocabops.normalize`).

Document frequency
    ``df`` is the number of documents that contain the term at least once.

se_specificity
    A smoothed log-frequency ratio between the software-engineering corpus and
    a general-English baseline (``wordfreq``). For a term ``t``::

        se_rate(t)      = (tf(t) + alpha) / (total_se_tokens + alpha * vocab_size)
        general_rate(t) = max(word_frequency(t, "en"), 1e-8)
        se_specificity  = ln(se_rate(t) / general_rate(t))

    ``alpha`` is 1.0 (add-one smoothing). ``vocab_size`` is the number of
    distinct lemma types in the corpus, so the smoothed corpus distribution
    sums to one. The general rate is floored at 1e-8 so unseen terms produce a
    finite score instead of a division by zero. Natural log is used, so the
    score is in nats: positive values mean the term is more frequent in the
    corpus than in general English.

The formula is documented for readers in ``docs/prototype.md``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence

from wordfreq import word_frequency

__all__ = [
    "ALPHA",
    "GENERAL_RATE_FLOOR",
    "term_frequency",
    "document_frequency",
    "vocabulary_size",
    "se_specificity",
    "corpus_rates",
    "rank_terms",
]

ALPHA = 1.0
GENERAL_RATE_FLOOR = 1e-8


def term_frequency(documents: Iterable[Sequence[str]]) -> Counter[str]:
    """Count lemma occurrences across all documents."""
    counts: Counter[str] = Counter()
    for document in documents:
        counts.update(document)
    return counts


def document_frequency(documents: Iterable[Sequence[str]]) -> Counter[str]:
    """Count in how many documents each lemma occurs at least once."""
    counts: Counter[str] = Counter()
    for document in documents:
        counts.update(set(document))
    return counts


def vocabulary_size(tf: Counter[str] | dict[str, int]) -> int:
    """Number of distinct terms in the corpus."""
    return len(tf)


def corpus_rates(tf: Counter[str], alpha: float = ALPHA) -> dict[str, float]:
    """Smoothed corpus probability of every term.

    Shares one denominator across terms, so the distribution is normalized by
    the total token count plus the smoothing mass ``alpha * vocab_size``.
    """
    total = sum(tf.values())
    denominator = total + alpha * vocabulary_size(tf)
    return {term: (count + alpha) / denominator for term, count in tf.items()}


def se_specificity(
    term: str,
    tf: int,
    total_tokens: int,
    vocab_size: int,
    alpha: float = ALPHA,
    general_frequency: float | None = None,
) -> float:
    """Smoothed log-frequency ratio of corpus rate against general English.

    ``general_frequency`` overrides the ``wordfreq`` lookup and exists for
    testing and for callers that already have a baseline value. The value is
    floored at :data:`GENERAL_RATE_FLOOR`.
    """
    se_rate = (tf + alpha) / (total_tokens + alpha * vocab_size)
    if general_frequency is None:
        general_frequency = word_frequency(term, "en")
    general_rate = max(general_frequency, GENERAL_RATE_FLOOR)
    return math.log(se_rate / general_rate)


def rank_terms(
    documents: Sequence[Sequence[str]],
    alpha: float = ALPHA,
) -> list[dict[str, float | int | str]]:
    """Rank every corpus term by ``se_specificity``.

    Rows are sorted by specificity descending, then term ascending, which keeps
    the output stable across runs and platforms.
    """
    tf = term_frequency(documents)
    df = document_frequency(documents)
    total_tokens = sum(tf.values())
    size = vocabulary_size(tf)

    rows: list[dict[str, float | int | str]] = []
    for term, count in tf.items():
        score = se_specificity(
            term=term,
            tf=count,
            total_tokens=total_tokens,
            vocab_size=size,
            alpha=alpha,
        )
        rows.append(
            {
                "term": term,
                "tf": count,
                "df": df[term],
                "se_specificity": score,
            }
        )

    rows.sort(key=lambda row: (-float(row["se_specificity"]), str(row["term"])))
    return rows
