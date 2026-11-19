"""Text normalization for the VocabOps corpus pipeline.

The prototype deliberately uses a small, dependency-free normalization layer so
that every step is inspectable and reproducible:

1. drop fenced code blocks (```` ``` ```` and ``~~~`` fences)
2. drop inline code spans (`like this`)
3. drop HTML tags
4. drop URLs
5. lowercase
6. tokenize on word characters
7. lemmatize with an irregular map, suffix-rule candidates and a wordfreq
   dictionary check
8. remove English stopwords

The lemmatizer is dictionary-validated rather than a full morphological
analyzer: suffix rules only *propose* candidate lemmas, and a candidate is
accepted only when ``wordfreq`` knows it as an English word. See
``docs/prototype.md`` for the remaining limitations.
"""

from __future__ import annotations

import re
from functools import lru_cache

from wordfreq import word_frequency

__all__ = [
    "STOPWORDS",
    "IRREGULAR_LEMMAS",
    "ENGLISH_WORD_MIN_FREQUENCY",
    "clean_text",
    "tokenize",
    "lemmatize",
    "normalize",
]

# Fenced code blocks, including an unterminated fence at end of document.
_FENCED_CODE_RE = re.compile(r"(?:```|~~~).*?(?:(?:```|~~~)|\Z)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_HTML_TAG_RE = re.compile(r"<[^>\n]+>")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Words whose lemma cannot be derived with suffix rules.
IRREGULAR_LEMMAS: dict[str, str] = {
    "am": "be",
    "are": "be",
    "been": "be",
    "being": "be",
    "is": "be",
    "was": "be",
    "were": "be",
    "did": "do",
    "does": "do",
    "doing": "do",
    "done": "do",
    "had": "have",
    "has": "have",
    "having": "have",
    "goes": "go",
    "went": "go",
    "gone": "go",
    "got": "get",
    "gotten": "get",
    "made": "make",
    "said": "say",
    "saw": "see",
    "seen": "see",
    "took": "take",
    "taken": "take",
    "thought": "think",
    "brought": "bring",
    "built": "build",
    "found": "find",
    "held": "hold",
    "kept": "keep",
    "left": "leave",
    "lost": "lose",
    "ran": "run",
    "sent": "send",
    # "underlying" is a target term in the prototype; keep it intact instead of
    # letting the -ing rule turn it into "underly".
    "underlie": "underlying",
    "underlies": "underlying",
    "underlay": "underlying",
    "underlying": "underlying",
    "data": "data",
}

# Standard English stopwords. Kept deliberately conservative: function words
# only, so content words in the fixture corpus stay available for ranking.
STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any anyone anything
    are aren't as at be because been before being below between both but by can
    can't cannot could couldn't did didn't do does doesn't doing don't down
    during each everything few for from further had hadn't has hasn't have
    haven't having he he'd he'll he's her here here's hers herself him himself
    his how how's i i'd i'll i'm i've if in into is isn't it it's its itself
    just let's me more most mustn't my myself neither no nobody nor not nothing
    of off on once only or other ought our ours ourselves out over own same
    shan't she she'd she'll she's should shouldn't so some someone something
    such than that that's the their theirs them themselves then there there's
    these they they'd they'll they're they've this those through to too under
    until up very was wasn't we we'd we'll we're we've were weren't what what's
    when when's where where's which while who who's whom why why's will with
    won't would wouldn't you you'd you'll you're you've your yours yourself
    yourselves
    """.split()
)

_VOWELS = frozenset("aeiou")

# The shared "real English word" floor: a token or generated lemma counts as
# English only when its wordfreq English frequency is at or above this value.
# Both the lemmatizer below and the English-ratio filter in ``ingest.py`` use
# this one constant, so the two thresholds cannot drift apart.
#
# The value sits well above wordfreq's noise floor for non-words (e.g. "merg"
# 1.6e-08, "cach" 2.5e-08, "requir" 3.3e-08, "código" 1.7e-08) and at or below
# every technical lemma this corpus needs (e.g. "propagate" and "invalidate" at
# 1e-06, "invoke" 2.1e-06).
ENGLISH_WORD_MIN_FREQUENCY = 1e-06


def clean_text(text: str) -> str:
    """Strip code, markup and URLs, then lowercase.

    Fenced code blocks are removed before inline spans so that a fence's
    backticks are never mistaken for inline code markers.
    """
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    return text.lower()


def tokenize(text: str) -> list[str]:
    """Return lowercase word-character tokens.

    Punctuation, underscores and pure-number tokens are dropped; a token must
    contain at least one letter.
    """
    tokens = []
    for raw in _TOKEN_RE.findall(text):
        token = raw.strip("_").lower()
        if not token or "_" in token:
            continue
        if not any(ch.isalpha() for ch in token):
            continue
        if len(token) == 1 and token not in {"a", "i"}:
            continue
        tokens.append(token)
    return tokens


def _strip_doubled_consonant(stem: str) -> str:
    # "ss" is excluded so "passed" stays "pass" and "missing" stays "miss"
    # instead of collapsing to "pas" / "mis".
    if (
        len(stem) > 2
        and stem[-1] == stem[-2]
        and stem[-1] not in _VOWELS
        and stem[-1] != "s"
    ):
        return stem[:-1]
    return stem


@lru_cache(maxsize=None)
def _frequency(word: str) -> float:
    """English frequency of ``word`` according to wordfreq (cached)."""
    return word_frequency(word, "en")


def _derived_candidates(token: str) -> set[str]:
    """Suffix-rule candidate lemmas for an inflected token.

    Every rule contributes its output to a set instead of returning one guess,
    so a silent "e" no longer has to be predicted from a suffix table: both the
    bare stem and the stem with a restored "e" are offered, and the dictionary
    check in :func:`lemmatize` decides which one is a word.
    """
    candidates: set[str] = set()

    # Plurals / third-person singular.
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        candidates.add(token[:-1])
        if token.endswith("ies") and len(token) > 4:
            candidates.add(token[:-3] + "y")
        if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
            # "boxes" -> "box", "matches" -> "match".
            candidates.add(token[:-2])
        if len(token) > 4 and token.endswith("ses"):
            # Lemma already ends in "s": "aliases" -> "alias".
            candidates.add(token[:-2])

    # Past tense / past participle.
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        candidates.update({stem, stem + "e"})
        undone = _strip_doubled_consonant(stem)
        candidates.update({undone, undone + "e"})
        if token.endswith("ied"):
            candidates.add(token[:-3] + "y")

    # Present participle.
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        if len(stem) >= 4:
            # Avoid destroying short words such as "string" -> "str".
            candidates.update({stem, stem + "e"})
            undone = _strip_doubled_consonant(stem)
            candidates.update({undone, undone + "e"})

    candidates.discard(token)
    return candidates


@lru_cache(maxsize=None)
def lemmatize(token: str) -> str:
    """Reduce an inflected English word to a dictionary-validated lemma.

    Order of operations: irregular map, candidate generation from the suffix
    rules, then validation against ``wordfreq``. A candidate is accepted only
    when its English frequency is at least :data:`ENGLISH_WORD_MIN_FREQUENCY`
    (the same "real English word" floor the ingest English-ratio filter uses);
    among accepted candidates the most frequent wins. If no candidate survives,
    the original token is returned, because a real inflected word is always a
    safer answer than an invented stem.

    The original token is never compared against the candidates: an inflected
    form can be more frequent than its lemma (``required`` 1.05e-04 vs
    ``require`` 6.03e-05), which would otherwise keep the inflection.

    Rules only fire on lowercase alphabetic tokens of length > 3 so short words
    such as "is" or "bus" are left alone.
    """
    token = token.lower()
    if token in IRREGULAR_LEMMAS:
        return IRREGULAR_LEMMAS[token]
    if len(token) <= 3 or not token.isalpha():
        return token

    best: str | None = None
    best_frequency = 0.0
    for candidate in sorted(_derived_candidates(token)):
        frequency = _frequency(candidate)
        if frequency >= ENGLISH_WORD_MIN_FREQUENCY and frequency > best_frequency:
            best = candidate
            best_frequency = frequency
    return best if best is not None else token


def normalize(text: str, remove_stopwords: bool = True) -> list[str]:
    """Full normalization pipeline for one document.

    Returns the ordered list of lemma tokens. Stopword removal checks both the
    raw token and the lemma: the raw check catches stopwords such as
    "anything"/"during" whose heuristic lemma would otherwise survive, and the
    lemma check catches inflected forms such as "being" -> "be".
    """
    tokens = tokenize(clean_text(text))
    lemmas = [lemmatize(token) for token in tokens]
    if remove_stopwords:
        lemmas = [
            lemma
            for token, lemma in zip(tokens, lemmas)
            if token not in STOPWORDS and lemma not in STOPWORDS
        ]
    return lemmas
