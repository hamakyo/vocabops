# Ranking evaluation — candidate methods for the three-source corpus

**Status: offline measurement and a recommendation. No pipeline change.**
Part 8 of [core500-evaluation.md](core500-evaluation.md#part-8--combined-corpus-and-source-bias)
measured the negative result: concatenating GH Archive, Stack Overflow and
CodeSearchNet produces a combined top 100 that is an API signature directory
(`param`, `ioexception`, `rtype`, `dataframe`, `getelementbyid`, `kwarg`), and
seven of the eight tracked target terms fall. This round implements five
candidate ranking methods on the same corpus and scores all six (the baseline
plus five) on metrics fixed before any number was computed.

The result: **Borda fusion (M3) wins the target, view-recovery and top-100
character metrics outright, and suppresses five of six artifacts**, and is
recommended as the ranking basis for the next round. It is not free — `param`
stays at rank 31 and half its top 100 is still technical-noun vocabulary. Both
facts are quantified below.

## Setup: per-source counts

One normalization pass over the three fixed document files:

| source | documents | tokens | types | `df >= 10` terms |
| --- | ---: | ---: | ---: | ---: |
| gharchive | 17,390 | 2,181,317 | 53,982 | 6,138 |
| stackoverflow | 17,390 | 1,476,830 | 72,982 | 5,166 |
| codesearchnet | 17,390 | 521,906 | 30,478 | 2,526 |
| **total** | **52,170** | **4,180,053** | union 131,966 | 9,463 |

The token total matches `out/combined-rank-v1-df10/manifest.json` exactly
(4,180,053). Normalization uses the project's own pipeline: `clean_text` →
`tokenize` → `normalize_tokens`, with the attested headword set built from the
**combined** corpus (28,894 attested forms, matching the combined manifest), so
the lemmas are the ones the combined ranking was produced from. Counts are
written to `out/ranking-eval/source-counts.json` (scratch, git-ignored). Two
runs are byte-identical (`sha256 9f8724bdcf94ac1843bcafa54eac747201c92c1157a1bdb74b9efaf0ec1bd1d8`),
and two evaluation runs on the artifact produce byte-identical metrics and
report; the count build takes about 20 seconds.

### Sanity check before evaluation

`scripts/evaluate_rankings.py` refuses to evaluate if the pooled counts do not
reproduce `out/combined-rank-v1-df10/ranking.json`. On the real data:

- all 100 top terms: `tf` and `df` **exact**;
- every one of the 9,463 rows: `se_specificity` equal after rounding to the six
  decimals the pipeline emits;
- the full ordering is **identical** (9,463 terms, same positions).

No mismatch. The baseline is therefore a genuine recomputation, not a re-read.

## Score definition

Every per-source score replicates [stats.py](../src/vocabops/stats.py) verbatim:

```
score_s(t) = ln( ((tf_s(t) + 1.0) / (T_s + 1.0 * V_s))
                 / max(word_frequency(t, "en"), 1e-8) )
```

`T_s` is that source's token count and `V_s` its number of distinct lemma types
(53,982 / 72,982 / 30,478). The smoothing denominator is per source, because the
score is a distribution over that source's tokens; using the union vocabulary
size instead would make the three sources' floors incomparable for no reason.
The general-English term and the `1e-8` floor are shared across methods.

**Absent-term handling.** A term with `tf_s = 0` gets no special case: the
formula already yields `ln( 1.0 / (T_s + V_s) / general_rate )`, a finite floor
score that is low but not zero. M1 and M2 include that floor for absent
sources; M5 shifts it positive; M3 uses a rank penalty instead; M4 excludes the
term from the corpus.

## Methods, exactly

All methods use the combined ranking's `df >= 10` pooled eligibility except M4,
which defines its own. Ordering is score descending then term ascending; Borda
is sum ascending then term ascending. Ties therefore never depend on input
order.

| method | definition | rows |
| --- | --- | ---: |
| **M0 pooled** | Existing combined ranking, recomputed from the counts. One count table over the concatenation, scored with the formula above. | 9,463 |
| **M1 mean** | Arithmetic mean of the three per-source scores. A term absent from a source contributes that source's floor score. | 9,463 |
| **M2 min** | Minimum of the three per-source scores: a term must be specific to every source. An absent term is capped by the floor. | 9,463 |
| **M3 Borda** | For each source, rank its own `df >= 10` terms by that source's score (ties by term ascending). Sum the three ranks. A term absent from a source's list receives `listed + 1`, i.e. below every listed term and tied with every other absent term; with listed counts of 6,138 / 5,166 / 2,526 the absence penalties are 6,139 / 5,167 / 2,527. | 9,463 |
| **M4 pooled + presence** | Pooled score, restricted to terms with `df > 0` in at least 2 of 3 sources **and** pooled `df >= 10`. Ineligible terms are removed, not demoted. | 8,377 |
| **M5 geometric** | Geometric mean of the three per-source scores after a positive shift. Shift = `1.0 - min(score)` over the whole union vocabulary and all three sources = **8.623521**, so the smallest observed score maps to exactly 1.0 and every factor is >= 1. | 9,463 |

Why the shift: `se_specificity` is a log ratio and is negative for
general-English words; a geometric mean requires positive factors. The shift is
derived from the data, not tuned — it is the smallest constant that makes every
factor positive.

Eligibility by presence among the 9,463 pooled-eligible terms: 6,034 occur in
all three sources, 2,343 in two, 1,086 in one.

## Metrics (fixed before measurement)

1. **Targets**: ranks of the eight tracked terms, their median, and how many
   reach the top 500.
2. **View recovery**: how many of `data/core500-vocab-v2.jsonl`'s 500 terms
   land in the method's top 500 and top 1,020. This measures survival of the
   GH-curated vocabulary, not absolute quality — a method can score well here by
   staying close to the old GH ranking.
3. **Artifact suppression**: ranks of `param`, `rtype`, `ioexception`,
   `getelementbyid`, `kwarg`, `dataframe`.
4. **Top-100 character**: how many of the top 100 carry bucket (a) or (c) in
   `data/ranking-v6-classification.jsonl`, falling back to
   `data/ranking-v5-classification.jsonl` for terms the v6 file does not cover;
   terms in neither file are counted as unclassified, not guessed.

## Results

### Target terms

| term | M0 pooled | M1 mean | M2 min | M3 Borda | M4 pooled+presence | M5 geometric |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `retrieve` | 2,878 | 2,719 | 3,741 | **802** | 2,123 | 2,754 |
| `persist` | 2,983 | 2,876 | 2,476 | **459** | 2,221 | 2,852 |
| `invoke` | 2,555 | 2,245 | 2,145 | **305** | 1,840 | 2,230 |
| `propagate` | 3,650 | 3,191 | 3,052 | **686** | 2,850 | 3,165 |
| `reproduce` | 2,480 | 3,858 | 6,097 | **878** | 1,771 | 4,073 |
| `invalidate` | 3,195 | 2,992 | 2,586 | **527** | 2,424 | 2,968 |
| `fallback` | 905 | 1,494 | 1,076 | **109** | 627 | 1,459 |
| `underlying` | 5,744 | 5,095 | 4,965 | **3,082** | 4,817 | 5,102 |
| **median** | 2,930.5 | 2,934.0 | 2,819.0 | **606.5** | 2,172.0 | 2,910.0 |
| **in top 500** | 0 | 0 | 0 | **3** | 0 | 0 |

Borda is the only method that brings any target into the top 500
(`fallback` 109, `invoke` 305, `persist` 459) and it improves all eight targets
against pooled, including `underlying` (5,744 → 3,082). M1 and M5
improve most targets but make `reproduce` worse: its CodeSearchNet `df` is 1, so
the mean is dragged by one source's floor. M2 and M4 barely move the median.

### View recovery

| method | top 500 | top 1,020 |
| --- | ---: | ---: |
| M0 pooled | 63 | 98 |
| M1 mean | 82 | 125 |
| M2 min | 117 | 217 |
| **M3 Borda** | **168** | **219** |
| M4 pooled+presence | 71 | 126 |
| M5 geometric | 83 | 130 |

M0's 63 / 98 reproduces Part 8's measurement exactly, which is the second
independent check that the count table and formula are faithful. Borda recovers
2.7x as many GH-curated terms at depth 500 as the pooled baseline — expected in
part, because those terms are the GH vocabulary, but Borda also leads at 1,020,
where the plain presence filter (M4) has already saturated.

### Artifact suppression

| term | M0 | M1 | M2 | M3 Borda | M4 | M5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `param` | 1 | 10 | 246 | **31** | 1 | 14 |
| `rtype` | 4 | 193 | 1,834 | **5,844** | 3 | 334 |
| `ioexception` | 3 | 15 | 2,026 | **1,005** | 2 | 23 |
| `getelementbyid` | 6 | 149 | 1,439 | **2,491** | 5 | 213 |
| `kwarg` | 8 | 3 | **61** | 1,008 | 7 | 3 |
| `dataframe` | 5 | 7 | **219** | 1,003 | 4 | 9 |

Borda pushes five of six artifacts out of the top 1,000 — `rtype` from 4 to
5,844, `getelementbyid` from 6 to 2,491, `ioexception` from 3 to 1,005. The
exception is `param`, which stays at **31**, and `kwarg` / `dataframe` land just
outside 1,000 rather than deep. M2 is the only method that suppresses `param`
hard (246) but it pays for that everywhere else.

### Top-100 character

| method | a | c | a+c | b | d | e | unclassified |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M0 pooled | 5 | 10 | 15 | 27 | 0 | 0 | 58 |
| M1 mean | 12 | 16 | 28 | 33 | 0 | 0 | 39 |
| M2 min | 18 | 17 | 35 | 40 | 0 | 0 | 25 |
| **M3 Borda** | **28** | **27** | **55** | 41 | 1 | 0 | 3 |
| M4 pooled+presence | 6 | 10 | 16 | 25 | 1 | 0 | 58 |
| M5 geometric | 12 | 20 | 32 | 36 | 0 | 0 | 32 |

M0's 15 a+c and 58 unclassified are the baseline this round was reacting to:
the pooled top 100 is mostly terms the GH review never classified. Borda has the
most transferable-vocabulary rows (55) and almost no unclassified
rows (3): its head is drawn from terms the GH review already classified. It also
has the most bucket (b) rows (41), so its head is still close to half technical
nouns.

### Source presence in the top 100

| method | 1 source | 2 sources | 3 sources |
| --- | ---: | ---: | ---: |
| M0 pooled | 23 | 29 | 48 |
| M1 mean | 0 | 7 | 93 |
| M2 min | 0 | 0 | 100 |
| **M3 Borda** | **0** | **0** | **100** |
| M4 pooled+presence | 0 | 40 | 60 |
| M5 geometric | 0 | 5 | 95 |

Every top-100 term of M2 and M3 occurs in all three sources. That is the
strongest single result in this evaluation: the fix for source bias is to
require a term to be *listed* by every source, not merely present in the pooled
counts (M4 keeps 40 two-source terms in its top 100 because the pooled score
still lets one source's volume carry a term).

## Top 20 per method

**M0 pooled** — `param`, `worktree`, `ioexception`, `rtype`, `dataframe`,
`getelementbyid`, `webhook`, `kwarg`, `illegalargumentexception`, `yml`,
`sha256`, `dtype`, `docstring`, `allowlist`, `tableview`, `arm64`, `typeerror`,
`javax`, `invalidargumentexception`, `writeline`.

**M1 mean** — `dtype`, `base64`, `kwarg`, `webhook`, `substr`, `typeerror`,
`dataframe`, `valueerror`, `yml`, `param`, `sha256`, `i18n`, `paginate`,
`deserialize`, `ioexception`, `serializer`, `illegalargumentexception`,
`protobuf`, `nullpointerexception`, `classloader`.

**M2 min** — `i18n`, `base64`, `webhook`, `paginate`, `dockerfile`, `dtype`,
`sha256`, `stderr`, `float32`, `substr`, `upsert`, `stdout`, `json`, `traceback`,
`grpc`, `yaml`, `basename`, `typeerror`, `yml`, `serialize`.

**M3 Borda** — `base64`, `dtype`, `substr`, `typeerror`, `serializer`,
`paginate`, `valueerror`, `traceback`, `deserialize`, `oauth2`, `json`,
`sha256`, `float32`, `util`, `datasource`, `argv`, `stdout`, `stderr`,
`datetime`, `serialize`.

**M4 pooled+presence** — `param`, `ioexception`, `rtype`, `dataframe`,
`getelementbyid`, `webhook`, `kwarg`, `illegalargumentexception`, `yml`,
`sha256`, `dtype`, `docstring`, `arm64`, `typeerror`, `javax`,
`invalidargumentexception`, `writeline`, `base64`, `ndarray`, `textview`.

**M5 geometric** — `dtype`, `base64`, `kwarg`, `webhook`, `substr`,
`typeerror`, `yml`, `valueerror`, `dataframe`, `sha256`, `i18n`, `paginate`,
`deserialize`, `param`, `serializer`, `protobuf`, `illegalargumentexception`,
`dockerfile`, `int64`, `classloader`.

M3's head is still an API/type glossary (`base64`, `dtype`, `substr`,
`typeerror`, `serializer`, `oauth2`). It is a *cross-source* glossary instead of
a per-source one, which is the improvement the numbers register; it is not yet
the general software-engineering English the product wants.

## Reading the results

**Borda wins because the targets are cross-source words, not because it is
lenient.** All eight targets occur in all three sources, so a method that
requires every source to list a term rewards them. The artifacts are mixed:
`rtype`, `ioexception` and `getelementbyid` occur in two sources and fall;
`param`, `kwarg` and `dataframe` occur in all three and survive. Presence alone
(M4) barely moves the baseline (a+c 16 vs 15) precisely because the worst
artifact, `param`, is present everywhere. Source *concentration* is the signal,
and only rank fusion uses it.

**What Borda sacrifices.** Three costs, all visible above:

1. **`param` at rank 31.** `param` occurs in 10,367 CodeSearchNet documents
   against 263 in Stack Overflow and 76 in GH. Rank fusion compresses that gap
   and counts it as "listed" in the other two, so it lands in the top 100. Any
   method that penalizes a weak source (mean, min, geometric) does better here
   and worse everywhere else.
2. **41 of the top 100 are bucket (b)** technical nouns, and `kwarg` (1,008) and
   `dataframe` (1,003) sit just outside the first thousand. Borda is better than
   the baseline, not clean.
3. **The absent-term penalty is not symmetric.** Absence costs `listed + 1`:
   6,139 for GH, 5,167 for SO, 2,527 for CSN. A term concentrated in
   CodeSearchNet is penalized 2.4x more than an equally concentrated GH term.
   That is a structural preference for the larger, older list, not a neutral
   "must be common" rule. It is also why the view-recovery numbers are flattered:
   the measure is GH-vocabulary survival and the penalty arithmetic is kindest
   to GH-only terms.

Rank fusion also discards score magnitude: a term at a source's rank 1 and one
at rank 2 differ by one point, even when the scores differ by five nats.

**Surprises stated plainly.**

- `M4` (pooled + presence) is almost identical to `M0` (a+c 16 vs 15, view
  recovery 71/126 vs 63/98). Excluding terms that appear in only one source does
  not remove `param`, `ioexception`, `rtype`, `dataframe`,
  `getelementbyid` or `kwarg`: they all appear in at least two sources.
- `M1` and `M5` make `reproduce` **worse** (2,480 → 3,858 / 4,073) while
  improving most other targets, because CodeSearchNet has `df` 1 for it and the
  floor of one source dominates the average.
- `M2` pushes `param` 215 ranks lower than Borda (246 vs 31) yet has *more*
  bucket (b) rows in its top 100 (40), and only `fallback` (1,076) of the eight
  targets is inside 2,000; the next best is `invoke` at 2,145. Its apparent
  rigor is mostly a uniform shift toward mid-frequency API vocabulary.

## Recommendation

**Adopt M3 (Borda fusion) as the ranking basis for the next round, subject to
one correction before it is used to build a view.**

Reasoning, in the order the metrics were fixed:

- Targets: the only method with targets in the top 500 (3) and the best median
  by a factor of ~3.6 (606.5 vs 2,172 for the runner-up).
- View recovery: best at both depths (168 / 219).
- Artifacts: five of six pushed outside the top 1,000; the strongest suppression of the
  two-source artifacts (`rtype` 5,844, `getelementbyid` 2,491,
  `ioexception` 1,005).
- Top-100 character: most (a)+(c) rows (55) and fewest unclassified (3).

The correction: **equalize the absence penalty before implementation.** Raw
`listed + 1` encodes the unequal list lengths (6,139 / 5,167 / 2,527). Using a
common penalty, or a percentile rank, would remove the structural GH preference
without changing the method's character. That is a design change with its own
measurement, so it belongs to the implementation round, not this one.

If the owner prefers not to touch the penalty, the fallback is M2 (min
specificity): it is the most conservative on artifacts (`param` 246) and its
top 100 is also 100% three-source, but only one of eight targets reaches the top
2,000 (`fallback`, 1,076) and the rest would have to be accepted as
not-what-this-corpus-ranks-highly. That is a product decision, not a statistical
one.

**Not recommended:** M1, M5 and M4. M1/M5 improve the aggregate without fixing
the head and are sensitive to a single source's floor on individual terms; M4's
presence gate is measured to be nearly a no-op on the artifacts that motivated
this round.

## Reproduction

```bash
# 1. per-source counts (one pass over the three document files, ~20 s)
.venv/bin/python scripts/source_counts.py \
    --output out/ranking-eval/source-counts.json

# 2. sanity check, rankings, metrics and this report's tables
.venv/bin/python scripts/evaluate_rankings.py \
    --counts out/ranking-eval/source-counts.json \
    --combined out/combined-rank-v1-df10/ranking.json \
    --output out/ranking-eval/metrics.json \
    --markdown out/ranking-eval/report.md
```

The evaluation step aborts with exit code 3 if the pooled counts fail the
combined-ranking check. The fusion functions live in
`src/vocabops/fusion.py` and are unit-tested on synthetic tables in
`tests/test_fusion.py`; nothing in `pipeline.py` changed.

## Limits

- The corpus is one snapshot of three samples; no confidence intervals are
  reported and none of the differences here have been tested for significance.
  The metrics are descriptive, fixed in advance to stop method-shopping.
- View recovery is explicitly a GH-vocabulary survival measure. It should not
  be read as "the method finds better words", only as "the method preserves the
  vocabulary the GH view was reviewed on".
- The classification files cover GH ranking positions, not this corpus. The
  3 unclassified terms in Borda's top 100 and 58 in M0's are counted, not
  guessed.
- This document is a decision, not an implementation. No view was rebuilt, no
  threshold was changed, and no corpus work was done.
