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
