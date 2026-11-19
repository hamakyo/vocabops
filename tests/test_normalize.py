"""Unit tests for vocabops.normalize."""

from vocabops.normalize import clean_text, lemmatize, normalize, tokenize


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
