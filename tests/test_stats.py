"""Unit tests for vocabops.stats."""

import math

import pytest

from vocabops.stats import (
    ALPHA,
    GENERAL_RATE_FLOOR,
    document_frequency,
    rank_terms,
    se_specificity,
    term_frequency,
    vocabulary_size,
)


def test_term_frequency_counts_all_occurrences():
    documents = [["cache", "cache", "system"], ["cache", "token"]]
    tf = term_frequency(documents)
    assert tf["cache"] == 3
    assert tf["system"] == 1
    assert sum(tf.values()) == 5


def test_document_frequency_counts_documents_once_per_term():
    documents = [["cache", "cache", "system"], ["cache", "token"]]
    df = document_frequency(documents)
    assert df["cache"] == 2
    assert df["system"] == 1


def test_vocabulary_size_counts_distinct_terms():
    assert vocabulary_size(term_frequency([["a", "b"], ["b", "c"]])) == 3


def test_se_specificity_matches_the_documented_formula():
    # se_rate = (tf + 1) / (tokens + 1 * vocab_size)
    expected = math.log((3 + ALPHA) / (10 + ALPHA * 5) / 1e-4)
    actual = se_specificity(
        "cache", tf=3, total_tokens=10, vocab_size=5, general_frequency=1e-4
    )
    assert actual == pytest.approx(expected)


def test_se_specificity_floors_the_general_rate():
    actual = se_specificity(
        "nonsense", tf=1, total_tokens=10, vocab_size=5, general_frequency=0.0
    )
    expected = math.log((1 + ALPHA) / (10 + ALPHA * 5) / GENERAL_RATE_FLOOR)
    assert actual == pytest.approx(expected)


def test_domain_term_scores_higher_than_common_general_word():
    # "cache" is frequent in this corpus and rare in general English;
    # "system" is about as frequent here but common in general English.
    documents = [["cache", "cache", "cache", "system"], ["cache", "system"]]
    tf = term_frequency(documents)
    tokens = sum(tf.values())
    size = vocabulary_size(tf)

    cache_score = se_specificity("cache", tf["cache"], tokens, size)
    system_score = se_specificity("system", tf["system"], tokens, size)

    assert cache_score > system_score


def test_rank_terms_sorts_by_score_then_term():
    # "xyzzy" and "qwrtp" are absent from wordfreq, so both general rates are
    # floored and the two one-off terms tie; ties break alphabetically.
    rows = rank_terms([["xyzzy", "qwrtp"]])
    assert [row["term"] for row in rows] == ["qwrtp", "xyzzy"]
    assert rows[0]["tf"] == 1
    assert rows[0]["df"] == 1


def test_rank_terms_is_sorted_descending():
    rows = rank_terms(
        [
            ["cache", "cache", "cache", "system", "the", "server"],
            ["cache", "system"],
        ]
    )
    scores = [row["se_specificity"] for row in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0]["term"] == "cache"
