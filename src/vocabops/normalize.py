"""Text normalization for the VocabOps corpus pipeline.

The prototype deliberately uses a small, dependency-free normalization layer so
that every step is inspectable and reproducible:

1. drop fenced code blocks (```` ``` ```` and ``~~~`` fences)
2. drop inline code spans (`like this`)
3. drop HTML tags
4. drop URLs
5. lowercase
6. tokenize on word characters
7. lemmatize with an irregular map, suffix-rule candidates, a wordfreq
   dictionary check and a frequency-ratio guard against bare stems
8. remove English stopwords

The lemmatizer is dictionary-validated rather than a full morphological
analyzer: suffix rules only *propose* candidate lemmas, and a candidate is
accepted only when ``wordfreq`` knows it as an English word. See
``docs/prototype.md`` for the remaining limitations.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import lru_cache

from wordfreq import word_frequency

__all__ = [
    "STOPWORDS",
    "IRREGULAR_LEMMAS",
    "LEMMA_MIN_FREQUENCY",
    "MIN_CANDIDATE_FREQUENCY_RATIO",
    "ATTESTATION_MIN_DOCUMENTS",
    "clean_text",
    "tokenize",
    "attested_headwords",
    "lemmatize",
    "normalize_tokens",
    "normalize",
]

# Fenced code blocks, including an unterminated fence at end of document.
_FENCED_CODE_RE = re.compile(r"(?:```|~~~).*?(?:(?:```|~~~)|\Z)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_HTML_TAG_RE = re.compile(r"<[^>\n]+>")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# --- digit-bearing token rules -------------------------------------------
#
# The Core 500 v0 audit found 82 fragments in the top 500
# (``data/core500-v0-audit.jsonl`` bucket ``d``; see
# ``docs/core500-evaluation.md``). The single biggest cause was the bare
# ``\w+`` tokenizer: an ISO timestamp such as ``2026-11-18T02:07:00Z`` became
# ``18t02`` / ``07`` / ``00z`` and those shards entered the ranking as if they
# were vocabulary (25 rows in the top 500). CSS measurements (``390px``,
# ``320px``, ``1280px``), version shards (``v006``) and hex-like strings
# (``7a7e3f9f``) add the rest. The three rules below remove that class while
# keeping real letter-first technical terms (``sha256``, ``arm64``, ``aarch64``,
# ``e2e``, ``i18n``, ``utf8``, ``x402``, ``python3``, ``1080p``).
#
# They live in ``tokenize`` rather than in ``clean_text`` on purpose: both the
# pipeline (via ``normalize``) and the ingest English-ratio filter call
# ``tokenize`` directly, so the two paths see identical tokens.

# Rule 1: strip ISO-8601 timestamps before tokenizing. The full datetime form
# must run before the bare-date form, otherwise the date half is removed and
# the time half (``t02``, ``07``, ``00z``) is left behind. A bare year such as
# "in 2026" or "version 2.0" is not an ISO date and is unaffected.
_ISO_DATETIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Rule 2: CSS/measurement values are not vocabulary (``390px``, ``12pt``).
_MEASUREMENT_RE = re.compile(r"^\d+(?:px|pt|rem|em)$")

# Rule 3: digit-first shards. A token that starts with a digit and has another
# digit after at least one letter is a tokenizer artifact of a timestamp,
# identifier or hex string (``18t02``, ``7a7e3f9f``). Letter-first tokens are
# never dropped here, so ``sha256``, ``arm64`` and ``e2e`` survive. Digit-first
# tokens with no digit after the letter part (``1080p``, ``500s``, and also
# letter-first version shards such as ``v006``) are a documented residual.
_DIGIT_FIRST_SHARD_RE = re.compile(r"^\d.*[A-Za-z].*\d")

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

# The lemmatizer's "is this candidate a plausible English headword?" floor: a
# generated lemma counts as real only when its wordfreq English frequency is at
# or above this value.
#
# This is *not* the same question as the ingest English-ratio test ("is this
# token evidence that the document is English?"), which has its own constant,
# ``vocabops.ingest.ENGLISH_RATIO_MIN_FREQUENCY``. Sharing one value between
# the two questions caused the round-8 regression: at 3e-07 the document test
# accepted French and Spanish words and 284 extra FR/ES documents entered the
# day corpus, taking non-English rows in the top 500 from 14 to 78.
#
# The value sits an order of magnitude above wordfreq's noise floor for
# non-words (e.g. "merg" 1.6e-08, "cach" 2.5e-08, "requir" 3.3e-08, "código"
# 1.7e-08) and at or below the technical lemmas this corpus needs, including
# ones the old 1e-06 floor wrongly excluded ("fallback" 4.57e-07, "retry"
# 3.72e-07, "credential" 5.62e-07, "endpoint" 8.51e-07, "encode" 8.91e-07).
# Measured against the 24-hour GH Archive day corpus, the old floor turned 925
# of 66,045 distinct raw tokens (1.4% of types, 0.3% of occurrences) into the
# wrong lemma. Lowering it fixed 22 of the 25 highest-frequency cases but also
# ``3e-07`` admits a few candidates that wordfreq happens to list just above
# 3e-07: "always" -> "alway" (3.89e-07), "speed" -> "spe" (5.75e-07) and
# "unbounded" -> "unbound" (7.08e-07). The first two are stem fragments and are
# rejected by the ratio guard below; "unbounded" -> "unbound" is two real words
# and stays a documented non-goal (see ``MIN_CANDIDATE_FREQUENCY_RATIO``).
LEMMA_MIN_FREQUENCY = 3e-07

# How much rarer than the token a candidate may be before it is rejected as a
# bare stem.
#
# A suffix rule that strips an ending can land on a fragment that wordfreq
# still lists: "always" -> "alway" (obsolete word, 3.89e-07), "speed" -> "spe"
# (5.75e-07), "ceiling" -> "ceil" (7.24e-08, a function name; reached through
# corpus attestation after the suffix rule proposes it). Frequency alone cannot
# separate those from real lemmas, but the *ratio* between candidate and token
# can: a real merge keeps a substantial share of the inflected form's
# frequency, while a fragment keeps almost none.
#
# Calibration on wordfreq English frequencies, measured for this corpus:
#
#   good merges    credentials -> credential  0.102  (the minimum)
#                  embedded    -> embed        0.112
#                  detached    -> detach       0.158
#                  encrypted   -> encrypt       0.219
#                  all other observed good merges >= 0.32
#   bad merges     always      -> alway        0.0007
#                  speed       -> spe          0.006
#                  ceiling     -> ceil         0.005
#
# ``0.02`` sits roughly 3x above the worst bad case and 5x below the weakest
# good case, so it is a gap cut, not a tuned one. A token with wordfreq 0
# bypasses the ratio test: the zero-frequency dedup family ("deduped" ->
# "dedup", both 0.0) has no ratio to judge, and attestation governs there.
#
# The guard applies to every candidate acceptance, including attested ones:
# corpus attestation must not override it, because ``ceil`` is attested as a
# function name for the same reason it is a bad lemma for ``ceiling``.
#
# Known non-goal: "unbounded" -> "unbound" has ratio 2.04 because both are real
# words; the guard cannot and should not block it.
MIN_CANDIDATE_FREQUENCY_RATIO = 0.02

# How many documents must contain a raw form before the corpus itself counts as
# evidence that the form is a real headword of this domain.
#
# The wordfreq floor is a general-English judgement and it fails technical
# headwords that the corpus uses all the time: ``rebase`` is wordfreq 6.46e-08,
# ``dedup`` and ``dedupe`` are 0.0. Their inflections therefore never validate,
# even though the headword is a ranking row attested across the corpus (the Core
# 500 review found ``rebase``/``rebased``/``rebases`` as three rows for one
# lemma). Three documents is the smallest count that is still corpus evidence
# rather than one author's repetition: the day corpus is 17,390 documents, so a
# form in three of them is a shared term, not a typo or a template artefact.
# Attestation only admits a candidate the suffix rules already propose, so it
# cannot invent a lemma; it can only let an existing candidate win where no
# wordfreq-valid candidate exists.
ATTESTATION_MIN_DOCUMENTS = 3


def attested_headwords(
    token_documents: Iterable[Sequence[str]],
    min_documents: int = ATTESTATION_MIN_DOCUMENTS,
) -> frozenset[str]:
    """Raw forms that occur standalone in at least ``min_documents`` documents.

    ``token_documents`` holds the raw tokens of each document (the output of
    :func:`tokenize`, before lemmatization). A form counts once per document, so
    repetition inside one document cannot attest itself. The result is a set, so
    document order and iteration order cannot change it: the same corpus yields
    the same attested set and therefore byte-identical output.
    """
    document_counts: Counter[str] = Counter()
    for tokens in token_documents:
        document_counts.update(set(tokens))
    return frozenset(
        form for form, count in document_counts.items() if count >= min_documents
    )


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
    contain at least one letter. Digit-bearing artifacts are removed by three
    rules applied in order (see the module-level comment): ISO-8601 timestamps
    are stripped from the text before tokenizing, CSS/measurement tokens are
    dropped, and digit-first shards with a digit after their letter part are
    dropped. Real letter-first technical terms keep their digit suffixes.
    """
    # Rule 1: remove ISO datetimes, then bare ISO dates, before ``\w+`` can
    # split them into timestamp shards.
    text = _ISO_DATETIME_RE.sub(" ", text)
    text = _ISO_DATE_RE.sub(" ", text)

    tokens = []
    for raw in _TOKEN_RE.findall(text):
        token = raw.strip("_").lower()
        if not token or "_" in token:
            continue
        if not any(ch.isalpha() for ch in token):
            continue
        if len(token) == 1 and token not in {"a", "i"}:
            continue
        # Rule 2: CSS/measurement values such as "390px" are not vocabulary.
        if _MEASUREMENT_RE.match(token):
            continue
        # Rule 3: digit-first shards such as "18t02" or "7a7e3f9f". Letter-first
        # tokens (sha256, arm64, e2e) never match this pattern.
        if _DIGIT_FIRST_SHARD_RE.match(token):
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
def lemmatize(token: str, attested: frozenset[str] = frozenset()) -> str:
    """Reduce an inflected English word to a validated lemma.

    Order of operations: irregular map, candidate generation from the suffix
    rules, then validation. A candidate is accepted when its English frequency
    is at least :data:`LEMMA_MIN_FREQUENCY`, or when the corpus attests it (it
    occurs standalone in at least :data:`ATTESTATION_MIN_DOCUMENTS` documents,
    passed in as ``attested``). Every accepted candidate must also pass the
    bare-stem ratio guard: when the token itself has a nonzero wordfreq, the
    candidate's frequency must be at least
    :data:`MIN_CANDIDATE_FREQUENCY_RATIO` of it. Among surviving candidates the
    most frequent wins, so a wordfreq-valid candidate always beats an
    attested-only one with lower frequency; attestation only decides when no
    wordfreq-valid candidate exists. If no candidate survives, the original
    token is returned, because a real inflected word is always a safer answer
    than an invented stem.

    ``attested`` defaults to the empty set, which reproduces the pure
    single-token behaviour for callers without a corpus: the corpus pre-pass is
    opt-in and cannot change a result unless a candidate is both attested and
    not wordfreq-valid.

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
    best_frequency = -1.0
    token_frequency = _frequency(token)
    for candidate in sorted(_derived_candidates(token)):
        frequency = _frequency(candidate)
        if frequency >= LEMMA_MIN_FREQUENCY or candidate in attested:
            # Bare-stem guard: a candidate far rarer than the token it came
            # from is a fragment, not a lemma. Tokens at wordfreq 0 have no
            # ratio to test; attestation decides for that family.
            if (
                token_frequency > 0
                and frequency / token_frequency < MIN_CANDIDATE_FREQUENCY_RATIO
            ):
                continue
            if frequency > best_frequency:
                best = candidate
                best_frequency = frequency
    return best if best is not None else token


def normalize_tokens(
    tokens: Iterable[str],
    remove_stopwords: bool = True,
    attested: frozenset[str] = frozenset(),
) -> list[str]:
    """Lemmatize raw tokens, optionally dropping stopwords.

    Split out from :func:`normalize` so the pipeline can tokenize once, build
    the attested set from those raw tokens, and then lemmatize the same tokens
    with corpus evidence.
    """
    tokens = list(tokens)
    lemmas = [lemmatize(token, attested) for token in tokens]
    if remove_stopwords:
        lemmas = [
            lemma
            for token, lemma in zip(tokens, lemmas)
            if token not in STOPWORDS and lemma not in STOPWORDS
        ]
    return lemmas


def normalize(
    text: str,
    remove_stopwords: bool = True,
    attested: frozenset[str] = frozenset(),
) -> list[str]:
    """Full normalization pipeline for one document.

    Returns the ordered list of lemma tokens. Stopword removal checks both the
    raw token and the lemma: the raw check catches stopwords such as
    "anything"/"during" whose heuristic lemma would otherwise survive, and the
    lemma check catches inflected forms such as "being" -> "be".

    ``attested`` carries corpus evidence from :func:`attested_headwords`; it
    defaults to the empty set, so the pure single-document behaviour is
    unchanged for callers that have no corpus.
    """
    tokens = tokenize(clean_text(text))
    return normalize_tokens(tokens, remove_stopwords=remove_stopwords, attested=attested)
