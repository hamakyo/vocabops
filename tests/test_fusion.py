"""Unit tests for the candidate ranking fusions on synthetic count tables.

The tables are deliberately tiny, so every expected value can be derived from
the ``se_specificity`` formula by hand or recomputed with the same function.
``general_frequency`` is injected, so the tests do not depend on wordfreq's
actual frequencies.
"""

from __future__ import annotations

import math

import pytest

from vocabops.fusion import (
    SourceStats,
    borda_scores,
    borda_scores_common_penalty,
    borda_scores_percentile,
    geometric_mean_specificity,
    mean_specificity,
    min_specificity,
    positive_shift,
    presence_count,
    present_in_at_least,
    source_rank,
    specificity,
)
from vocabops.stats import GENERAL_RATE_FLOOR, se_specificity

FREQUENCIES = {"alpha": 1e-3, "beta": 1e-3, "gamma": 1e-3, "delta": 1e-3, "shared": 1e-3, "bravo": 1e-3}


def frequency(term: str) -> float:
    return FREQUENCIES.get(term, 1e-8)


A = SourceStats(
    name="a",
    tf={"alpha": 10, "beta": 5, "shared": 20},
    df={"alpha": 4, "beta": 3, "shared": 5},
    total_tokens=100,
    vocab_size=10,
)
B = SourceStats(
    name="b",
    tf={"gamma": 10, "shared": 10},
    df={"gamma": 5, "shared": 4},
    total_tokens=200,
    vocab_size=10,
)
C = SourceStats(
    name="c",
    tf={"delta": 20, "shared": 10},
    df={"delta": 6, "shared": 3},
    total_tokens=400,
    vocab_size=10,
)
SOURCES = [A, B, C]


def formula(tf: int, total: int, vocab: int, term: str) -> float:
    return se_specificity(
        term=term,
        tf=tf,
        total_tokens=total,
        vocab_size=vocab,
        general_frequency=frequency(term),
    )


def test_absent_term_gets_the_smoothed_floor_score():
    # ``gamma`` does not occur in source a: tf = 0, so the formula's own floor.
    expected = formula(0, 100, 10, "gamma")
    assert specificity("gamma", A, frequency) == pytest.approx(expected)
    assert expected == pytest.approx(math.log((1 / 110) / 1e-3))
    assert specificity("gamma", A, frequency) < specificity("alpha", A, frequency)


def test_absent_term_lowers_mean_but_not_to_zero():
    mean = mean_specificity("gamma", SOURCES, frequency)
    expected = (
        formula(0, 100, 10, "gamma")
        + formula(10, 200, 10, "gamma")
        + formula(0, 400, 10, "gamma")
    ) / 3
    assert mean == pytest.approx(expected)
    assert mean == pytest.approx(
        (specificity("gamma", A, frequency) + specificity("gamma", B, frequency)
         + specificity("gamma", C, frequency)) / 3
    )


def test_mean_requires_at_least_one_source():
    with pytest.raises(ValueError):
        mean_specificity("alpha", [], frequency)


def test_min_is_the_lowest_per_source_score():
    assert min_specificity("gamma", SOURCES, frequency) == pytest.approx(
        min(specificity("gamma", s, frequency) for s in SOURCES)
    )
    # ``gamma`` is strongest in b, absent elsewhere: the minimum is an absent
    # source's floor, so a term must be specific everywhere to rank well.
    assert min_specificity("gamma", SOURCES, frequency) == pytest.approx(
        min(formula(0, 100, 10, "gamma"), formula(0, 400, 10, "gamma"))
    )


def test_min_differs_from_mean_when_one_source_is_weak():
    assert min_specificity("shared", SOURCES, frequency) < mean_specificity(
        "shared", SOURCES, frequency
    )


def test_positive_shift_maps_the_smallest_score_to_one():
    terms = ["alpha", "beta", "gamma", "delta", "shared"]
    shift = positive_shift(terms, SOURCES, frequency)
    smallest = min(specificity(t, s, frequency) for t in terms for s in SOURCES)
    assert smallest + shift == pytest.approx(1.0)
    assert all(specificity(t, s, frequency) + shift > 0 for t in terms for s in SOURCES)


def test_geometric_mean_is_the_mean_of_logs():
    shift = positive_shift(["alpha", "shared"], SOURCES, frequency)
    geo = geometric_mean_specificity("shared", SOURCES, shift, frequency)
    factors = [specificity("shared", s, frequency) + shift for s in SOURCES]
    expected = math.exp(sum(math.log(f) for f in factors) / len(factors))
    assert geo == pytest.approx(expected)
    # Geometric mean is at most the arithmetic mean of the same shifted scores.
    assert geo <= sum(factors) / len(factors) + 1e-12


def test_geometric_mean_rejects_a_shift_that_leaves_scores_nonpositive():
    with pytest.raises(ValueError):
        geometric_mean_specificity("shared", SOURCES, -10.0, frequency)


def test_geometric_mean_ignores_high_outliers_more_than_mean_does():
    shift = positive_shift(["alpha", "beta", "gamma", "delta", "shared"],
                           SOURCES, frequency)
    term = "gamma"  # strong in b, floored in a and c
    assert geometric_mean_specificity(term, SOURCES, shift, frequency) < (
        mean_specificity(term, SOURCES, frequency) + shift
    )


def test_source_rank_is_one_based_and_ties_break_by_term():
    tie = SourceStats(
        name="tie",
        tf={"bravo": 5, "alpha": 5, "charlie": 9},
        df={"bravo": 2, "alpha": 2, "charlie": 3},
        total_tokens=50,
        vocab_size=5,
    )
    ranks, listed = source_rank(tie, 1, frequency)
    assert listed == 3
    assert ranks == {"charlie": 1, "alpha": 2, "bravo": 3}


def test_source_rank_drops_terms_below_min_df_and_penalizes_absence():
    ranks, listed = source_rank(A, 4, frequency)
    assert ranks == {"shared": 1, "alpha": 2}
    assert listed == 2
    ranks_b, listed_b = source_rank(B, 4, frequency)
    ranks_c, listed_c = source_rank(C, 4, frequency)
    scores = borda_scores(["alpha", "gamma", "shared"], SOURCES, 4, frequency)
    # Absence is worth ``listed + 1`` in that source: below every listed term.
    assert scores["alpha"] == ranks["alpha"] + (listed_b + 1) + (listed_c + 1)
    assert scores["gamma"] == (listed + 1) + ranks_b["gamma"] + (listed_c + 1)
    assert scores["alpha"] > scores["shared"]


def test_borda_absent_terms_tie_below_every_listed_term():
    # With a df>=10 cut nothing is listed, so every term gets 0+1 per source;
    # all totals tie and the caller breaks the tie by term.
    scores = borda_scores(["b", "a"], SOURCES, 10, frequency)
    assert scores == {"a": 3, "b": 3}


def test_borda_lower_is_better_for_terms_listed_in_more_sources():
    scores = borda_scores(["shared", "gamma"], SOURCES, 3, frequency)
    assert scores["shared"] < scores["gamma"]


def test_common_penalty_is_the_same_for_every_absent_source():
    ranks_a, listed_a = source_rank(A, 4, frequency)
    ranks_b, listed_b = source_rank(B, 4, frequency)
    ranks_c, listed_c = source_rank(C, 4, frequency)
    penalty = max(listed_a, listed_b, listed_c) + 1
    scores = borda_scores_common_penalty(
        ["alpha", "gamma", "shared"], SOURCES, 4, frequency
    )
    # ``alpha`` is absent from b and c: both absences cost ``penalty``, even
    # though b's and c's own lists have different lengths.
    assert scores["alpha"] == ranks_a["alpha"] + 2 * penalty
    assert scores["gamma"] == 2 * penalty + ranks_b["gamma"]
    assert scores["shared"] == (
        ranks_a["shared"] + ranks_b["shared"] + penalty
    )
    assert penalty == 3


def test_common_penalty_differs_from_raw_borda_on_unequal_lists():
    ranks_a, listed_a = source_rank(A, 4, frequency)
    ranks_b, listed_b = source_rank(B, 4, frequency)
    ranks_c, listed_c = source_rank(C, 4, frequency)
    raw = borda_scores(["gamma"], SOURCES, 4, frequency)["gamma"]
    common = borda_scores_common_penalty(["gamma"], SOURCES, 4, frequency)["gamma"]
    # gamma is absent from a and c; raw charges each list's own length, E1 a
    # single common penalty (the longest list + 1).
    assert raw == (listed_a + 1) + ranks_b["gamma"] + (listed_c + 1)
    assert common == 2 * (max(listed_a, listed_b, listed_c) + 1) + ranks_b["gamma"]
    assert raw != common


def test_percentile_borda_is_rank_over_listed_and_one_for_absence():
    ranks_a, listed_a = source_rank(A, 4, frequency)
    ranks_b, listed_b = source_rank(B, 4, frequency)
    ranks_c, listed_c = source_rank(C, 4, frequency)
    scores = borda_scores_percentile(
        ["alpha", "gamma", "shared"], SOURCES, 4, frequency
    )
    assert scores["shared"] == pytest.approx(
        ranks_a["shared"] / listed_a
        + ranks_b["shared"] / listed_b
        + 1.0
    )
    assert scores["gamma"] == pytest.approx(
        1.0 + ranks_b["gamma"] / listed_b + 1.0
    )
    assert scores["alpha"] == pytest.approx(
        ranks_a["alpha"] / listed_a + 1.0 + 1.0
    )
    # Lower is better; the term listed by two sources wins, and a term that is
    # absent everywhere else cannot score above 3.0.
    assert scores["shared"] < scores["alpha"]
    assert scores["alpha"] == pytest.approx(3.0)


def test_percentile_contribution_is_bounded_regardless_of_list_length():
    # Every per-source contribution lies in (0, 1]: a listed term at rank r of
    # n contributes r/n, an absent term exactly 1.0. No source's list length can
    # add a fixed number of points, which is the asymmetry E1 corrects.
    long_source = SourceStats(
        name="long",
        tf={"x": 5, **{f"t{i}": 1 for i in range(30)}},
        df={"x": 2, **{f"t{i}": 2 for i in range(30)}},
        total_tokens=200,
        vocab_size=40,
    )
    absent = borda_scores_percentile(["missing"], [long_source], 2, frequency)
    assert absent["missing"] == pytest.approx(1.0)
    listed = borda_scores_percentile(["x"], [long_source], 2, frequency)["x"]
    assert 0.0 < listed <= 1.0


def test_percentile_borda_requires_a_listed_term_per_source():
    with pytest.raises(ValueError):
        borda_scores_percentile(["alpha"], SOURCES, 10, frequency)


def test_presence_count_and_filter():
    assert presence_count("gamma", SOURCES) == 1
    assert presence_count("shared", SOURCES) == 3
    assert present_in_at_least(
        ["shared", "gamma", "alpha"], SOURCES, 2
    ) == ["shared"]


def test_floor_is_applied_to_injected_zero_frequency():
    # A zero general rate is raised to GENERAL_RATE_FLOOR inside the formula.
    expected = se_specificity(
        term="alpha",
        tf=10,
        total_tokens=100,
        vocab_size=10,
        general_frequency=GENERAL_RATE_FLOOR,
    )
    assert specificity("alpha", A, lambda _term: 0.0) == pytest.approx(expected)
