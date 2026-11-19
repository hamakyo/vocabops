"""Candidate ranking fusions over per-source ``se_specificity`` scores.

The combined ranking in ``out/combined-rank-v1-df10`` scores the concatenated
corpus, so one source's token volume dominates the score of every term. These
functions are the offline alternatives measured in
``docs/ranking-evaluation.md``. They are pure functions of per-source count
tables and a general-English frequency function; nothing here is wired into
:mod:`vocabops.pipeline`.

Score definition (replicated from :func:`vocabops.stats.se_specificity`)::

    score_s(t) = ln( ((tf_s(t) + alpha) / (T_s + alpha * V_s))
                     / max(word_frequency(t, "en"), 1e-8) )

with ``alpha = 1.0``, ``T_s`` the source's token count, and ``V_s`` the number
of distinct lemma types in that source. A term absent from a source has
``tf_s = 0``, so the per-source score is the source's smoothed floor
``ln( alpha / (T_s + alpha * V_s) / general_rate )`` — a finite, low score. That
floor is exactly what the formula yields for ``df = 0``; no special case is
needed or applied.

Ranking methods:

``pooled``
    The existing combined ranking: one count table over the concatenation.
``mean``
    Mean of the three per-source scores.
``min``
    Minimum per-source score (a term must be specific to every source).
``borda``
    Sum of per-source ranks; a term below a source's ``min_df`` threshold is
    ranked below every listed term of that source.
``geometric``
    Geometric mean of shifted per-source scores, ``shift`` chosen so the
    smallest observed score maps to 1.0.
``restrict``
    Pooled score, with terms present (``df > 0``) in fewer than
    ``min_sources`` sources removed rather than demoted.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from wordfreq import word_frequency

from .stats import ALPHA, GENERAL_RATE_FLOOR, se_specificity

__all__ = [
    "SourceStats",
    "specificity",
    "mean_specificity",
    "min_specificity",
    "positive_shift",
    "geometric_mean_specificity",
    "source_rank",
    "borda_scores",
    "borda_scores_common_penalty",
    "borda_scores_percentile",
    "presence_count",
    "present_in_at_least",
]

GeneralFrequency = Callable[[str], float]


def _default_general_frequency(term: str) -> float:
    return word_frequency(term, "en")


@dataclass(frozen=True)
class SourceStats:
    """Per-source counts for one corpus.

    ``tf`` and ``df`` may hold only the terms the source uses; a missing key is
    a zero count. ``total_tokens`` and ``vocab_size`` are the smoothing
    denominator's two parts for this source.
    """

    name: str
    tf: Mapping[str, int]
    df: Mapping[str, int]
    total_tokens: int
    vocab_size: int
    documents: int = 0


def specificity(
    term: str,
    source: SourceStats,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> float:
    """That source's ``se_specificity`` for ``term`` (floor score if absent)."""
    return se_specificity(
        term=term,
        tf=source.tf.get(term, 0),
        total_tokens=source.total_tokens,
        vocab_size=source.vocab_size,
        alpha=ALPHA,
        general_frequency=max(general_frequency(term), GENERAL_RATE_FLOOR),
    )


def _require_sources(sources: Sequence[SourceStats]) -> None:
    if not sources:
        raise ValueError("at least one source is required")


def mean_specificity(
    term: str,
    sources: Sequence[SourceStats],
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> float:
    """Arithmetic mean of the per-source scores, absent sources included."""
    _require_sources(sources)
    return sum(specificity(term, s, general_frequency) for s in sources) / len(sources)


def min_specificity(
    term: str,
    sources: Sequence[SourceStats],
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> float:
    """Lowest per-source score; one weak source caps the term."""
    _require_sources(sources)
    return min(specificity(term, s, general_frequency) for s in sources)


def positive_shift(
    terms: Iterable[str],
    sources: Sequence[SourceStats],
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> float:
    """Shift that maps the smallest score over ``terms`` to exactly 1.0.

    Geometric means need positive factors. ``se_specificity`` is a log ratio
    and is routinely negative for general-English words, so the scores are
    shifted by ``1.0 - min_score``. The constant is derived from the data
    rather than tuned: it is the smallest value that makes every factor >= 1.
    """
    _require_sources(sources)
    smallest = min(
        specificity(term, source, general_frequency)
        for term in terms
        for source in sources
    )
    return 1.0 - smallest


def geometric_mean_specificity(
    term: str,
    sources: Sequence[SourceStats],
    shift: float,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> float:
    """Geometric mean of ``score + shift`` across sources."""
    _require_sources(sources)
    factors = [specificity(term, s, general_frequency) + shift for s in sources]
    if any(factor <= 0 for factor in factors):
        raise ValueError("shift must make every per-source score positive")
    return math.exp(sum(math.log(factor) for factor in factors) / len(factors))


def source_rank(
    source: SourceStats,
    min_df: int,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> tuple[dict[str, int], int]:
    """Rank a source's own ``df >= min_df`` terms by its specificity.

    Returns ``(ranks, listed)`` where ``ranks`` is 1-based and ``listed`` is the
    number of ranked terms. Ties break by term ascending, the same rule
    :func:`vocabops.stats.rank_terms` uses.
    """
    listed = [term for term, df in source.df.items() if df >= min_df]
    listed.sort(key=lambda term: (-specificity(term, source, general_frequency), term))
    return {term: index for index, term in enumerate(listed, start=1)}, len(listed)


def borda_scores(
    terms: Iterable[str],
    sources: Sequence[SourceStats],
    min_df: int,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> dict[str, int]:
    """Sum of per-source ranks; lower is better.

    A term below a source's ``df >= min_df`` cut is absent from that source's
    list and receives ``listed + 1``: below every listed term, tied with every
    other absent term. Ties in the total are resolved by the caller with a
    term-ascending sort.
    """
    _require_sources(sources)
    per_source = [source_rank(s, min_df, general_frequency) for s in sources]
    scores: dict[str, int] = {}
    for term in terms:
        scores[term] = sum(
            ranks.get(term, listed + 1) for ranks, listed in per_source
        )
    return scores


def borda_scores_common_penalty(
    terms: Iterable[str],
    sources: Sequence[SourceStats],
    min_df: int,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> dict[str, int]:
    """Borda sum where absence costs the same in every source.

    The penalty is ``max(listed) + 1`` over the sources, so an absent term sits
    below every listed term of every source and the list-length asymmetry of
    :func:`borda_scores` disappears (E1). Lower is better.
    """
    _require_sources(sources)
    per_source = [source_rank(s, min_df, general_frequency) for s in sources]
    penalty = max(listed for _, listed in per_source) + 1
    scores: dict[str, int] = {}
    for term in terms:
        scores[term] = sum(
            ranks.get(term, penalty) for ranks, _ in per_source
        )
    return scores


def borda_scores_percentile(
    terms: Iterable[str],
    sources: Sequence[SourceStats],
    min_df: int,
    general_frequency: GeneralFrequency = _default_general_frequency,
) -> dict[str, float]:
    """Percentile Borda: each source contributes ``rank / listed`` or ``1.0``.

    A listed term's contribution is its fractional position in that source's
    list; an absent term contributes the maximum, 1.0. The three contributions
    are summed, so a term at the top of every source approaches 0 and one
    listed nowhere scores 3.0. Scale-free in list length (E2). Lower is better.
    """
    _require_sources(sources)
    per_source = [source_rank(s, min_df, general_frequency) for s in sources]
    for _, listed in per_source:
        if listed == 0:
            raise ValueError("percentile Borda needs at least one listed term")
    scores: dict[str, float] = {}
    for term in terms:
        scores[term] = sum(
            ranks[term] / listed if term in ranks else 1.0
            for ranks, listed in per_source
        )
    return scores


def presence_count(term: str, sources: Sequence[SourceStats]) -> int:
    """Number of sources in which the term occurs at least once."""
    return sum(1 for source in sources if source.df.get(term, 0) > 0)


def present_in_at_least(
    terms: Iterable[str], sources: Sequence[SourceStats], min_sources: int
) -> list[str]:
    """Terms occurring in at least ``min_sources`` sources, input order kept."""
    return [term for term in terms if presence_count(term, sources) >= min_sources]
