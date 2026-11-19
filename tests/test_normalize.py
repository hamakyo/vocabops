"""Unit tests for vocabops.normalize."""

from vocabops.ingest import ENGLISH_RATIO_MIN_FREQUENCY
from vocabops.normalize import (
    ATTESTATION_MIN_DOCUMENTS,
    LEMMA_MIN_FREQUENCY,
    MIN_CANDIDATE_FREQUENCY_RATIO,
    attested_headwords,
    clean_text,
    lemmatize,
    normalize,
    tokenize,
)


def test_fenced_code_blocks_are_removed():
    text = "Before\n```python\nretrieve(token)\n```\nAfter"
    assert clean_text(text).split() == ["before", "after"]


def test_tilde_fenced_code_blocks_are_removed():
    text = "Keep\n~~~\ninvoke()\n~~~\nthis"
    assert clean_text(text).split() == ["keep", "this"]


def test_inline_code_is_removed():
    assert clean_text("Call `store.persist(x)` twice").split() == ["call", "twice"]


def test_html_tags_are_removed():
    text = '<p align="center">See the docs</p>'
    assert clean_text(text).split() == ["see", "the", "docs"]


def test_urls_are_removed():
    text = "Trace at https://example.invalid/issues/1 and www.example.org/log"
    assert clean_text(text).split() == ["trace", "at", "and"]


def test_tokenize_lowercases_and_splits_on_punctuation():
    assert tokenize("Retry, then re-run; it's fine.") == [
        "retry",
        "then",
        "re",
        "run",
        "it",
        "fine",
    ]


def test_tokenize_drops_numbers_and_underscores():
    assert tokenize("v2 42 snake_case name") == ["v2", "name"]


def test_tokenize_keeps_vocabulary_and_drops_timestamp_css_shards():
    # The Core 500 v0 audit's reproduction case: a full ISO timestamp, a CSS
    # width and three real digit-bearing terms in one sentence.
    tokens = tokenize(
        "Deployed 2026-11-18T02:07:00Z at width:390px with sha256 and arm64 and 1080p"
    )
    assert not {"18t02", "07", "00z", "390px"} & set(tokens)
    assert {"deployed", "sha256", "arm64", "1080p"} <= set(tokens)


def test_tokenize_strips_full_iso_timestamps_before_splitting():
    # Space separator, fractional seconds and numeric offsets are the other
    # ISO forms the day corpus contains.
    for stamp in (
        "2026-11-18T02:07:00Z",
        "2026-11-17 19:29:02.284",
        "2026-11-18T10:28:29+09:00",
        "2026-11-18 11:04",
    ):
        assert tokenize(f"start {stamp} end") == ["start", "end"]


def test_tokenize_strips_standalone_iso_dates_but_keeps_years():
    assert tokenize("released 2026-11-18 build") == ["released", "build"]
    # A bare year and a decimal version are not ISO dates. They are still not
    # tokens: the pre-existing rule drops pure-number tokens, and rule 1 does
    # not change that. "2.0" contributes no letter-bearing token either.
    assert tokenize("in 2026 we shipped version 2.0") == [
        "in",
        "we",
        "shipped",
        "version",
    ]


def test_tokenize_drops_css_measurement_tokens():
    assert tokenize("width 390px height 12pt size 1rem indent 2em") == [
        "width",
        "height",
        "size",
        "indent",
    ]


def test_tokenize_drops_digit_first_shards_only():
    # Digit-first with a digit after the letter part: tokenizer artifacts.
    assert tokenize("18t02 7a7e3f9f 834cf5") == []
    # Letter-first digit terms are real vocabulary and always survive.
    assert tokenize("sha256 arm64 aarch64 e2e i18n utf8 x402 python3") == [
        "sha256",
        "arm64",
        "aarch64",
        "e2e",
        "i18n",
        "utf8",
        "x402",
        "python3",
    ]
    # Digit-first with no digit after the letter part is a known residual.
    assert tokenize("1080p 500s") == ["1080p", "500s"]


def test_lemmatize_irregular_verbs():
    assert lemmatize("went") == "go"
    assert lemmatize("was") == "be"
    assert lemmatize("built") == "build"


def test_lemmatize_plurals():
    assert lemmatize("repositories") == "repository"
    assert lemmatize("boxes") == "box"
    assert lemmatize("classes") == "class"
    assert lemmatize("matches") == "match"
    assert lemmatize("tokens") == "token"
    assert lemmatize("aliases") == "alias"
    assert lemmatize("entries") == "entry"
    assert lemmatize("settings") == "setting"


def test_lemmatize_plurals_keep_silent_e():
    # The old suffix table produced "cach"; the dictionary check finds "cache".
    assert lemmatize("caches") == "cache"


def test_lemmatize_past_tense_restores_final_e():
    assert lemmatize("retrieved") == "retrieve"
    assert lemmatize("propagated") == "propagate"
    assert lemmatize("invalidated") == "invalidate"
    assert lemmatize("invoked") == "invoke"
    assert lemmatize("persisted") == "persist"
    assert lemmatize("reproduced") == "reproduce"
    assert lemmatize("typed") == "type"
    assert lemmatize("moved") == "move"
    assert lemmatize("served") == "serve"
    assert lemmatize("passed") == "pass"


def test_lemmatize_present_participle():
    assert lemmatize("retrieving") == "retrieve"
    assert lemmatize("propagating") == "propagate"
    assert lemmatize("invalidating") == "invalidate"
    assert lemmatize("invoking") == "invoke"
    assert lemmatize("reproducing") == "reproduce"
    assert lemmatize("running") == "run"
    assert lemmatize("matching") == "match"


def test_lemmatize_past_tense_is_dictionary_validated():
    # Each of these used to come out as a non-word (merg, requir, enforc, ...).
    assert lemmatize("merged") == "merge"
    assert lemmatize("required") == "require"
    assert lemmatize("enforced") == "enforce"
    assert lemmatize("declared") == "declare"
    assert lemmatize("defined") == "define"
    assert lemmatize("repeated") == "repeat"
    assert lemmatize("changed") == "change"


def test_lemmatize_present_participle_is_dictionary_validated():
    # "repeating" used to become "repeate"; "caching" -> "cach".
    assert lemmatize("merging") == "merge"
    assert lemmatize("repeating") == "repeat"
    assert lemmatize("defining") == "define"
    assert lemmatize("caching") == "cache"


def test_lemmatize_requires_keeps_the_lemma_not_the_inflection():
    assert lemmatize("requires") == "require"


def test_lemmatize_leaves_unchanged_alone_instead_of_inventing_a_stem():
    # "unchange" is not a word, so the original token survives.
    assert lemmatize("unchanged") == "unchanged"


def test_lemmatize_floor_is_pinned_and_distinct_from_the_ratio_floor():
    # The lemmatizer asks "is this candidate a plausible headword?"; the ingest
    # ratio test asks "is this token evidence that the document is English?".
    # They are separate constants and must not collapse back into one value.
    assert LEMMA_MIN_FREQUENCY == 3e-07
    assert ENGLISH_RATIO_MIN_FREQUENCY == 1e-06
    assert LEMMA_MIN_FREQUENCY != ENGLISH_RATIO_MIN_FREQUENCY


def test_lemmatize_merges_inflections_below_the_old_floor():
    # The lemmatizer floor is 3e-07. These lemmas were below the old 1e-06
    # floor ("fallback" 4.57e-07, "retry" 3.72e-07, "credential" 5.62e-07,
    # "encode" 8.91e-07), so their inflections used to survive as separate rows.
    assert lemmatize("fallbacks") == "fallback"
    assert lemmatize("encoded") == "encode"
    assert lemmatize("credentials") == "credential"
    assert lemmatize("retries") == "retry"


def test_lemmatize_blocks_bare_stem_merges_by_frequency_ratio():
    # These used to be accepted because wordfreq lists the bare stem just
    # above the lemma floor. The ratio guard rejects them: the candidate keeps
    # far less than 0.02 of the token's frequency.
    assert lemmatize("always") == "always"  # alway ratio 0.0007
    assert lemmatize("speed") == "speed"  # spe ratio 0.006
    assert lemmatize("ceiling") == "ceiling"  # ceil ratio 0.005
    # Non-goal, unchanged: both are real words, so the ratio is 2.04.
    assert lemmatize("unbounded") == "unbound"


def test_guard_constants_are_pinned():
    assert MIN_CANDIDATE_FREQUENCY_RATIO == 0.02
    assert LEMMA_MIN_FREQUENCY == 3e-07


def test_lemmatize_target_terms_stay_in_base_form():
    for term in [
        "retrieve",
        "persist",
        "invoke",
        "propagate",
        "reproduce",
        "invalidate",
        "fallback",
        "underlying",
    ]:
        assert lemmatize(term) == term


def test_lemmatize_never_returns_a_known_damaged_form():
    damaged = {
        "merg",
        "requir",
        "enforc",
        "declar",
        "defin",
        "repeate",
        "unchange",
        "cach",
        "propagat",
        "invok",
        "retriev",
    }
    tokens = [
        "merged",
        "merging",
        "required",
        "requires",
        "enforced",
        "declared",
        "defined",
        "defining",
        "repeating",
        "repeated",
        "unchanged",
        "caches",
        "caching",
        "propagated",
        "invoking",
        "retrieved",
        "persisted",
        "invalidated",
    ]
    assert not damaged & {lemmatize(token) for token in tokens}


def test_lemmatize_leaves_short_words_intact():
    assert lemmatize("string") == "string"
    assert lemmatize("bus") == "bus"
    assert lemmatize("go") == "go"


def test_underlying_is_preserved_as_a_term():
    assert lemmatize("underlying") == "underlying"
    assert lemmatize("underlies") == "underlying"


def test_normalize_removes_stopwords_but_keeps_content_words():
    assert normalize("The cache is on the server.") == ["cache", "server"]


def test_normalize_removes_stopwords_before_lemmatizing_side_effects():
    # "during" and "anything" would be mangled by the suffix rules; the raw
    # token check removes them first.
    assert normalize("During the retry anything can fail") == ["retry", "fail"]


def test_normalize_end_to_end_on_markup_and_code():
    text = (
        "The client <b>cannot</b> retrieve the session.\n"
        "```\nsession = store.retrieve(token)\n```\n"
        "See https://example.invalid/1 for `details`."
    )
    assert normalize(text) == ["client", "retrieve", "session", "see"]


def test_attestation_threshold_is_three_documents():
    assert ATTESTATION_MIN_DOCUMENTS == 3


def test_attested_headwords_needs_three_documents():
    two = [tokenize("rebase it"), tokenize("rebase again")]
    assert attested_headwords(two) == frozenset()

    three = two + [tokenize("rebase now")]
    assert attested_headwords(three) == frozenset({"rebase"})


def test_attested_headwords_counts_documents_not_occurrences():
    # Four occurrences in two documents is not corpus evidence: repetition
    # inside one document must not attest its own form.
    repeated = [tokenize("rebase rebase rebase"), tokenize("rebase"), tokenize("other")]
    assert attested_headwords(repeated) == frozenset()


def test_lemmatize_without_corpus_is_unchanged():
    # The corpus pre-pass is opt-in: the pure single-token behavior must not
    # change for callers that pass no attested set.
    assert lemmatize("rebased") == "rebased"
    assert lemmatize("rebases") == "rebases"
    assert lemmatize("deduping") == "deduping"


def test_lemmatize_accepts_an_attested_low_frequency_headword():
    attested = frozenset({"rebase"})  # wordfreq 6.46e-08
    assert lemmatize("rebased", attested) == "rebase"
    assert lemmatize("rebases", attested) == "rebase"


def test_lemmatize_prefers_wordfreq_valid_candidate_over_attested_one():
    # "merg" is attested here but is not a word; "merge" is wordfreq-valid and
    # more frequent, so attestation must not win the race.
    assert lemmatize("merged", frozenset({"merg"})) == "merge"


def test_attested_dedup_merges_its_inflections():
    # "dedup" and "dedupe" are both wordfreq 0.0; the suffix rules generate both
    # for "deduped"/"deduping", so attestation is the only thing that can
    # decide. Alphabetical order breaks the zero-frequency tie.
    attested = frozenset({"dedup"})
    assert lemmatize("deduped", attested) == "dedup"
    assert lemmatize("deduping", attested) == "dedup"
    assert lemmatize("dedups", attested) == "dedup"


def test_attestation_does_not_override_the_ratio_guard():
    # "ceil" is a real corpus form (a function name) and an attested candidate
    # for "ceiling". Attestation must not turn it into a lemma: the ratio guard
    # governs every acceptance.
    texts = [
        "Use ceil for rounding up.",
        "They call ceil here.",
        "Ceil again in the parser.",
        "The ceiling is low.",
    ]
    token_documents = [tokenize(clean_text(text)) for text in texts]
    attested = attested_headwords(token_documents)
    assert "ceil" in attested
    assert lemmatize("ceiling", attested) == "ceiling"


def test_guard_keeps_real_merges_on_both_validation_paths():
    # Wordfreq-valid merges above the threshold still merge.
    assert lemmatize("credentials") == "credential"
    assert lemmatize("embedded") == "embed"
    assert lemmatize("fallbacks") == "fallback"
    assert lemmatize("detached") == "detach"
    assert lemmatize("encrypted") == "encrypt"
    # Attested-only merges still merge: nonzero token frequency with a healthy
    # ratio (rebased -> rebase 2.19), and the zero-frequency bypass
    # (deduped -> dedup, both 0.0).
    assert lemmatize("rebased", frozenset({"rebase"})) == "rebase"
    assert lemmatize("deduped", frozenset({"dedup"})) == "dedup"


def test_guard_leaves_no_producer_of_alway():
    # Before the guard the wordfreq path produced "alway" from "always". After
    # it, no path produces "alway", attested or not.
    texts = [
        "It is always the same rebase.",
        "Always rebase before merging.",
        "The rebased branch always passes.",
        "We deduped and rebased the tree.",
    ]
    token_documents = [tokenize(clean_text(text)) for text in texts]
    attested = attested_headwords(token_documents)
    producers = {
        token
        for tokens in token_documents
        for token in tokens
        if lemmatize(token, attested) == "alway"
    }
    assert producers == set()
