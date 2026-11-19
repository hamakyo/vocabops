# Phase 1 Prototype

The Phase 1 prototype is the smallest end-to-end pipeline that tests the VocabOps hypothesis: can corpus statistics, compared against a general-English baseline, surface software-engineering vocabulary worth learning?

It uses a tiny fixture corpus that we wrote ourselves. It does not download or redistribute any third-party text.

## What it does

```text
data/fixtures/sample_corpus/*.txt
        |
        v
normalize   strip fenced/inline code, HTML tags, URLs
            lowercase, tokenize, lemmatize, drop stopwords
        |
        v
statistics  term frequency, document frequency
            se_specificity against the wordfreq baseline
        |
        v
ranking.json / ranking.csv / manifest.json
```

Each `.txt` file is one document with `source_family = "fixture"`. Documents keep their boundaries: term frequency is counted per document and document frequency counts documents, not occurrences. Each document also gets a stable ID, `sha256("fixture/" + file name)`.

## Setup and run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest -q

.venv/bin/python -m vocabops.pipeline \
  --input data/fixtures/sample_corpus \
  --output out/human-se-v0.1-proto \
  --snapshot-id human-se-v0.1-proto
```

Outputs (gitignored under `out/`):

- `ranking.json` — list of `{term, tf, df, se_specificity}`, sorted by `se_specificity` descending, then `term` ascending
- `ranking.csv` — the same rows, same order
- `manifest.json` — `snapshot_id`, `pipeline_version`, `sources`, `general_baseline`, `documents`, `tokens`

The pipeline writes no timestamps, so two runs on the same inputs produce byte-identical files.

## se_specificity

`se_specificity` is a smoothed log-frequency ratio. For a term `t`:

```text
se_rate(t)      = (tf(t) + alpha) / (total_se_tokens + alpha * vocab_size)
general_rate(t) = max(word_frequency(t, "en"), 1e-8)
se_specificity  = ln(se_rate(t) / general_rate(t))
```

- `tf(t)` — occurrences of the lemma across the corpus
- `total_se_tokens` — all normalized tokens in the corpus
- `vocab_size` — distinct lemma types, so the smoothed corpus distribution sums to one
- `alpha = 1.0` — add-one smoothing
- `word_frequency` — `wordfreq` English frequency per token
- the general rate is floored at `1e-8` so unseen terms give a finite score
- the natural log puts the score in nats: `0` means the term is as frequent in this corpus as in general English, positive means more frequent here

The implementation and the same formula live in the docstring of `src/vocabops/stats.py`.

## Lemmatization

`src/vocabops/normalize.py` keeps a small irregular-verb map (`went` → `go`, `built` → `build`) and otherwise lets suffix rules *propose* candidate lemmas instead of predicting one. A candidate is accepted only when `wordfreq` knows it as an English word.

Candidates for `-ed` / `-ing` tokens: the bare stem, the stem with a restored final `e`, and the doubled-consonant-undone form of both (`merged` → `merg`, `merge`; `running` → `runn`, `runne`, `run`, `rune`). Candidates for `-s` forms: the plain `-s` strip, `-ies` → `-y`, `-sses` / `-shes` / `-ches` / `-xes` / `-zes` / `-ses` minus `-es`, plus the stem and `stem + "e"` variants where they apply (`caches` → `cach`, `cache`; `aliases` → `aliase`, `alias`).

A derived candidate counts as real when `word_frequency(candidate, "en") >= 3e-07` (the lemmatizer's own `LEMMA_MIN_FREQUENCY`; it was `1e-06` before the day-corpus floor change documented below); among accepted candidates the most frequent wins. Since the v5 round every acceptance also passes a bare-stem ratio guard: when the original token has a nonzero wordfreq, the candidate must keep at least `MIN_CANDIDATE_FREQUENCY_RATIO = 0.02` of it. The guard is what stops `always` → `alway` (ratio 0.00068) and `speed` → `spe` (0.0058), and it also blocks the attested `ceiling` → `ceil` (0.0048). It does not catch `unbounded` → `unbound` (ratio 2.04, two real words), which remains a documented defect. At `3e-07` the plurals and inflections of `fallback` and `encode` merge into their lemmas (`fallbacks` → `fallback`, `encoded` / `encoding` → `encode`). The ingest English-ratio filter does **not** use this constant: it has its own `ENGLISH_RATIO_MIN_FREQUENCY = 1e-06`, because the two roles ask different questions (see [decoupled floors](#decoupled-floors-and-the-v3-day-corpus)). Sharing one value between them caused the round-8 language regression. The original token is never in that comparison, because an inflected form can be more frequent than its lemma (`required` 1.05e-04 vs `require` 6.03e-05). If no candidate passes, the token is returned unchanged: `unchanged` stays `unchanged` instead of becoming `unchange`. Short tokens (length ≤ 3), non-alphabetic tokens, and `-ing` stems shorter than four characters are left alone, so `string` and `bus` survive.

| token | candidates | result |
| --- | --- | --- |
| `merged` | `merg`, `merge` | `merge` |
| `required` | `requir`, `require` | `require` |
| `repeating` | `repeate`, `repeat` | `repeat` |
| `unchanged` | `unchange` (0.0) | `unchanged` |
| `caches` | `cach`, `cache` | `cache` |
| `propagated` | `propagat`, `propagate` | `propagate` |
| `aliases` | `aliase`, `alias` | `alias` |

## Fixture corpus

Five short documents, all original prose:

- `01-bug-report.txt` — a cache/session bug report with a fenced log block and a URL
- `02-code-review-thread.txt` — a review thread about retries and fallbacks
- `03-readme-excerpt.txt` — a storage-layer README excerpt with inline code and an HTML tag
- `04-incident-note.txt` — a post-deploy incident note
- `05-api-design-note.txt` — an API error-model design note

They deliberately repeat `retrieve`, `persist`, `invoke`, `propagate`, `reproduce`, `invalidate`, `fallback`, and `underlying` across different documents, alongside ordinary general English so the ranking has contrast.

On the current fixtures (5 documents, 276 tokens, 148 ranked terms) seven of those eight terms land in the top 20. `underlying` ranks lower because it is comparatively common in general English, which is the effect the baseline is supposed to capture.

Moving from the suffix-guessing lemmatizer to the dictionary-validated one changed the fixture ranking in exactly one place: `added` now lemmatizes to `add` instead of `ad`, so the one-row `ad` term disappears and `add` absorbs it (`tf` 1 → 2, `df` 1 → 2). The vocabulary drops from 149 to 148 terms, so every `se_specificity` value shifts by the same small amount through the smoothing denominator. The term order is otherwise unchanged; `add` moves up as its frequency doubles.

## GH Archive adapter and a bounded real run

`src/vocabops/ingest.py` is the first real source adapter. It streams GH Archive hourly event files (local `.json.gz` / `.json` or an http(s) URL) line by line, keeps the human-written prose, and writes one JSON document per line. `--input` may be repeated; the files are then read as one run in sorted path order, with counters, event-ID dedup and exact-text dedup spanning all of them:

```bash
.venv/bin/python -m vocabops.ingest gharchive \
  --input out/gharchive/2026-11-18-3.json.gz \
  --output out/gharchive/documents.jsonl \
  --max-docs 2000
```

Which events become documents:

| event type | text |
| --- | --- |
| `IssueCommentEvent` | `payload.comment.body` |
| `IssuesEvent` | `payload.issue.title` (first line) then `payload.issue.body` |
| `PullRequestEvent` | `payload.pull_request.title` (first line) then `payload.pull_request.body` |
| `PullRequestReviewCommentEvent` | `payload.comment.body` |
| `PullRequestReviewEvent` | `payload.review.body` |

Every other event type is skipped. A document requires a non-empty body; empty and whitespace-only bodies are skipped. Each record is `{doc_id, source_family, repo, actor, text}`, where `doc_id = sha256("gharchive/" + event id)`, `actor` is the event actor's login (or `null`), and duplicate event IDs are dropped. The adapter stops at `--max-docs` (default 2000).

The pipeline reads such a JSONL file directly:

```bash
.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents.jsonl \
  --output out/gharchive-rank \
  --snapshot-id gharchive-2026-11-18-3-proto

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents.jsonl \
  --output out/gharchive-rank-df3 \
  --snapshot-id gharchive-2026-11-18-3-proto \
  --min-df 3
```

Each JSONL line is one document; its `doc_id` and `source_family` are carried through, and `manifest.json` records the distinct source families actually present (`["gharchive"]` here). `--min-df N` (default 1) removes terms that occur in fewer than `N` documents from `ranking.json` and `ranking.csv`. Frequencies and scores are still computed over the whole corpus; only the emitted rows are filtered.

### Real-run summary

Input: `https://data.gharchive.org/2026-11-18-3.json.gz`, 3,989,290 bytes, sha256 `6b81f9e6cbab53ac6d4f1beba58b0a547d9d052e5d6290bf80312fe92a8af836`.

- events seen: 3,319
- documents written: 1,445 (the archive holds fewer text-bearing events than `--max-docs 2000`)
- documents skipped: 1,874 (no body); 0 malformed lines, 0 duplicate event IDs, 0 missing IDs
- corpus: 1,445 documents, 199,202 normalized tokens
- ranking: 21,872 terms at `min_df = 1`, 4,235 terms at `min_df = 3`

Re-running the ingest and the ranking produced byte-identical files.

This first ranking came from the suffix-guessing lemmatizer and is kept as the baseline for the comparison below. Its first ten `min_df = 3` rows are `unchange`, `xhigh`, `coderabbit`, `merg`, `requir`, `enforc`, `aliase`, `sha256`, `declar`, `unresolv`. Three separate effects are visible:

- Bots and automation: `coderabbit` (a review bot, 102 occurrences in 47 documents) and `18t03` are review-bot boilerplate, not human prose.
- Lemma artifacts: `unchange`, `merg`, `requir`, `enforc`, `declar`, `resolv`, `defin`, `repeate`, `reache` are suffix-rule lemmatizer damage.
- Non-English and token noise: CJK fragments (`また`, `初筛`), `xhigh` (a numeric-config token), `pukujan`, `aprè`.

Of the eight fixture target terms, none reaches the top 800 of either ranking; `fallback` is the best of them at 825th (`min_df = 3`). In the full ranking (`min_df = 1`, 21,872 terms) they rank: `fallback` 3,559; `reproduce` 15,658; `invoke` 16,670; `invalidate` 16,842; `persist` 16,863; `propagate` 16,907; `retrieve` 18,921; `underlying` 20,018. With `min_df = 3` (4,235 terms) they rank: `fallback` 825; `reproduce` 1,388; `invoke` 1,793; `invalidate` 1,870; `persist` 1,879; `propagate` 1,903; `retrieve` 2,942; `underlying` 3,461. They are present but far from the top: one hour of issue and pull-request prose is small and dominated by product-specific tokens and automation.

#### Re-ranking after the dictionary-validated lemmatizer

The same `out/gharchive/documents.jsonl`, snapshot id `gharchive-2026-11-18-3-proto` and `--min-df 3` were re-run into a new directory, leaving the earlier output untouched:

```bash
.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents.jsonl \
  --output out/gharchive-rank-df3-lemma2 \
  --snapshot-id gharchive-2026-11-18-3-proto \
  --min-df 3
```

The corpus is identical (1,445 documents, 199,202 tokens). The `min_df = 3` ranking shrinks from 4,235 to 4,146 rows: 303 old terms disappear and 214 new ones appear, dominated by damaged stems being replaced by their real words (`resolv` → `resolve` / `unresolved`, `aliase` → `alias`, `docstr` → `docstring`, `referenc` → `reference`, `encod` → `encoded` / `encoding`). Re-running produced byte-identical files.

| # | old top 10 | new top 10 |
| --- | --- | --- |
| 1 | `unchange` | `xhigh` |
| 2 | `xhigh` | `coderabbit` |
| 3 | `coderabbit` | `sha256` |
| 4 | `merg` | `18t03` |
| 5 | `requir` | `opencode` |
| 6 | `enforc` | `pukujan` |
| 7 | `aliase` | `vercel` |
| 8 | `sha256` | `また` |
| 9 | `declar` | `worktree` |
| 10 | `unresolv` | `初筛` |

None of `merg`, `requir`, `enforc`, `declar`, `defin`, `repeate`, `unchange` (the `unchanged` artifact), `cach`, `propagat`, `invok` or `retriev` appears anywhere in the new ranking. In the old one they held positions 4, 5, 6, 9, 14, 21, 1, 870, and `propagat` / `invok` / `retriev` did not occur at all. The former damaged rows are now real lemmas: `merge` (`tf` 370 → 520), `require` (112 → 348), `enforce` (11 → 81), `declare` (126 → 239), `define` (26 → 109), `repeat` (40 → 74), `cache` (72 → 76), `alias` (new, 67), and `unchanged` (new, 160). What is left at the top is bot and automation text, product and tool names, non-English fragments and config tokens; no lemma artifact remains in the top 30.

Target-term positions with `min_df = 3` (4,235 → 4,146 rows):

| term | old | new | tf (old → new) |
| --- | --- | --- | --- |
| `fallback` | 825 | 713 | 124 → 119 |
| `reproduce` | 1,388 | 1,255 | 86 → 86 |
| `invoke` | 1,793 | 1,667 | 14 → 14 |
| `invalidate` | 1,870 | 1,744 | 5 → 5 |
| `persist` | 1,879 | 1,753 | 19 → 19 |
| `propagate` | 1,903 | 1,777 | 6 → 6 |
| `retrieve` | 2,942 | 2,851 | 4 → 4 |
| `underlying` | 3,461 | 3,374 | 5 → 5 |

Most terms keep their frequency and move up only because the vocabulary is smaller. `fallback` loses five occurrences because `fallbacks` no longer merges into it: `fallback` itself is below the `1e-06` validation threshold (4.57e-07), so its plural is returned unchanged and appears as its own row (`fallbacks`, `tf` 5, `df` 3).

## Bot, non-English and duplicate-text filters at ingest

Three opt-in ingest flags remove automation, non-English prose and exact duplicate text before anything reaches the pipeline. All are off by default, so the plain command still writes every text-bearing event.

- `--exclude-bots` — drop the event when the actor login ends with `[bot]`, or when it is in the explicit `BOT_LOGINS` set. That set currently holds only `Copilot`, GitHub's Copilot bot account, which carries no suffix. A login that merely contains `bot` (`botanist`, `robotfan`) is a human account and is kept.
- `--min-english-ratio R` — tokenize the extracted text with the normalizer's `tokenize()`, keep alphabetic tokens only, and compute `known / total`. A token is known only when `word_frequency(token, "en") >= 1e-06`, the ingest's own `ENGLISH_RATIO_MIN_FREQUENCY` constant defined in `src/vocabops/ingest.py`. It is deliberately **not** the lemmatizer's `LEMMA_MIN_FREQUENCY` (3e-07): the lemmatizer asks whether a candidate is a plausible headword, while this test asks whether a token is evidence that the document is English, and round 8 measured that `3e-07` is too loose for the second question (284 French/Spanish documents passed). Keep the document when the ratio is `>= R`; drop it when the ratio is lower. A document with zero alphabetic tokens is skipped as empty. `R` must be in 0..1.
- `--dedup-text` — after the other filters, drop a document whose stripped full text is byte-identical to a document already kept in the run. Comparison is `sha256` of `text.strip()` and the first occurrence in file order wins. Off by default. This is exact duplication only: near-duplicates, and templated documents that share a long prefix but differ in the tail, are not detected.

Both filters run at fixed positions: event-type/body extraction, then bot filter, then language filter, then event-ID checks, then optional exact-text deduplication, then `--max-docs`. Every dropped event lands in exactly one counter, and `ingest()` returns them all: `input_files`, `events_seen`, `documents_written`, `skipped_no_body`, `skipped_bot`, `skipped_language`, `skipped_no_tokens`, `skipped_duplicate_text`, `duplicates`, `malformed`, `missing_id`. Neither flag touches normalization, the lemmatizer, `se_specificity`, or the ranking; exclusion happens only here.

### Filtered real run (old token rule)

This run used the original `word_frequency(token, "en") > 0` test and is kept as the comparison baseline. The current rule is applied in the clean run below.

```bash
.venv/bin/python -m vocabops.ingest gharchive \
  --input out/gharchive/2026-11-18-3.json.gz \
  --output out/gharchive/documents-filtered.jsonl \
  --max-docs 2000 --exclude-bots --min-english-ratio 0.6

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-filtered.jsonl \
  --output out/gharchive-rank-df3-filtered \
  --snapshot-id gharchive-2026-11-18-3-proto --min-df 3
```

Counters over the same 3,319 events:

| counter | count |
| --- | --- |
| events seen | 3,319 |
| documents written | 740 |
| skipped: no body | 1,874 |
| skipped: bot actor | 603 (583 `[bot]` logins + 20 `Copilot`) |
| skipped: below english ratio | 101 |
| skipped: no alphabetic tokens | 1 |

The totals close: 3,319 − 1,874 − 603 − 101 − 1 = 740. The filtered corpus is 740 documents and 118,572 normalized tokens; the `min_df = 3` ranking has 2,938 rows (10,529 at `min_df = 1`), down from 4,146. Re-running ingest and pipeline produced byte-identical files.

The old top 10 was mostly automation, non-English text and config noise. `xhigh` (old 1), `coderabbit` (old 2), `opencode` (old 5), `pukujan` (old 6), `また` (old 8) and `初筛` (old 10) are all absent; `18t03` falls from 4 to 19 (`tf` 47 → 11) and `vercel` from 7 to 35 (`tf` 9). The two survivors from that top 10 are genuine infrastructure vocabulary: `sha256` (3 → 1) and `worktree` (9 → 3). The rest of the top 30 is product and infrastructure vocabulary (`frontmatter`, `stacksjs`, `namespace`, `docstring`) plus Latin-script non-English, discussed below.

Top 30 of the filtered `min_df = 3` ranking, with the position the same term held in `out/gharchive-rank-df3-lemma2` (`-` means it was below the 4,146-row cut):

| # | term | tf | df | old # |
| --- | --- | --- | --- | --- |
| 1 | `sha256` | 50 | 7 | 3 |
| 2 | `frontmatter` | 25 | 25 | 12 |
| 3 | `worktree` | 24 | 13 | 9 |
| 4 | `stacksjs` | 23 | 18 | 15 |
| 5 | `repositório` | 21 | 4 | 19 |
| 6 | `004b` | 20 | 20 | 21 |
| 7 | `groupable` | 20 | 20 | 22 |
| 8 | `código` | 34 | 12 | 18 |
| 9 | `namespace` | 665 | 28 | 31 |
| 10 | `fluxo` | 17 | 6 | 28 |
| 11 | `pruebas` | 17 | 5 | 23 |
| 12 | `referencia` | 16 | 6 | 33 |
| 13 | `namespaces` | 180 | 20 | 34 |
| 14 | `aceptación` | 15 | 15 | 35 |
| 15 | `criterios` | 14 | 14 | 44 |
| 16 | `regra` | 14 | 5 | 45 |
| 17 | `validación` | 14 | 4 | 46 |
| 18 | `rustsec` | 13 | 3 | 56 |
| 19 | `18t03` | 11 | 7 | 4 |
| 20 | `docstring` | 11 | 5 | 11 |
| 21 | `verificar` | 11 | 4 | 66 |
| 22 | `selección` | 12 | 3 | 81 |
| 23 | `contexto` | 11 | 6 | 54 |
| 24 | `contrato` | 13 | 4 | 82 |
| 25 | `critérios` | 10 | 8 | 62 |
| 26 | `mantener` | 10 | 3 | 86 |
| 27 | `origem` | 10 | 4 | 87 |
| 28 | `userlibs` | 10 | 5 | 90 |
| 29 | `aprobado` | 9 | 5 | 155 |
| 30 | `arquitetura` | 9 | 4 | 156 |

Target-term positions with `min_df = 3` (4,146 → 2,938 rows). `retrieve` and `invalidate` fall below the cut because their document frequency drops to 2 and 1; the `min_df = 1` columns show they are still in the corpus.

| term | old rank | new rank | old tf / df | new tf / df | new rank at `min_df = 1` |
| --- | --- | --- | --- | --- | --- |
| `retrieve` | 2,851 | — | 4 / 3 | 3 / 2 | 7,981 |
| `persist` | 1,753 | 1,016 | 19 / 14 | 13 / 9 | 6,353 |
| `invoke` | 1,667 | 1,194 | 14 / 14 | 5 / 5 | 6,734 |
| `propagate` | 1,777 | 1,119 | 6 / 5 | 3 / 3 | 6,582 |
| `reproduce` | 1,255 | 581 | 86 / 68 | 77 / 61 | 5,272 |
| `invalidate` | 1,744 | — | 5 / 4 | 2 / 1 | 6,665 |
| `fallback` | 713 | 258 | 119 / 69 | 84 / 53 | 3,883 |
| `underlying` | 3,374 | 2,337 | 5 / 5 | 3 / 3 | 9,091 |

Every target term loses raw frequency because automated prose was a large share of the corpus (1,445 → 740 documents, 199,202 → 118,572 tokens), and ranks improve mainly because the vocabulary shrinks (4,146 → 2,938 rows).

### Residual automation and Latin-script non-English

The filters are login- and token-membership-based, not classifier-based, so the filtered corpus still contains automation that has no `[bot]` suffix. Top 10 actors by document count in `out/gharchive/documents-filtered.jsonl`:

| documents | actor |
| --- | --- |
| 20 | `atolis-hq-agent` |
| 18 | `chrisbbreuer` |
| 18 | `gokselozgur5` |
| 14 | `joshbruh-lang` |
| 8 | `donovanrost` |
| 7 | `FredApps` |
| 5 | `fubar-coder` |
| 5 | `CompleteDotTech` |
| 5 | `ventura8` |
| 4 | `viniciussucupira` |

`atolis-hq-agent` is an agent account: all 20 documents are templated design/plan prose ("Design: namespaces with pack-defined kinds … ## Status"). Their extracted text is byte-identical across all 20 events; the clean run below removes 19 of them with exact-text dedup.

The language filter reliably removes CJK text: the old `また` and `初筛` rows are gone from the top of this ranking. It does not remove Latin-script non-English *under the old token rule*. `código` is still rank 8 (`tf` 34, `df` 12) and `repositório`, `pruebas`, `validación` and others remain in the top 30. The cause was the rule itself: `word_frequency(token, "en") > 0` counted a token as English at any nonzero frequency, and `wordfreq`'s English list contains Portuguese and Spanish function words and loanwords at tiny frequencies (`código` is 1.7e-08 in `en`). The 12 documents that still contained `código` scored 0.656–0.791, above the 0.6 cut, because Portuguese `do`, `para`, `de`, `a`, `que`, `uma` and `por` all counted as known English tokens. The shared `1e-06` floor described above replaces that test; see the clean run for the result.

### Clean run: shared English floor and exact-text dedup

This section records the 1-hour clean run made while the English-ratio floor was
`1e-06`. That value is again the ratio floor today (`ENGLISH_RATIO_MIN_FREQUENCY`), so
the counters below still describe what the current filter does on this input; only the
tokenizer and the constant's name changed. The tables are kept exactly as measured then.

The token test then used the same "real English word" floor as the lemmatizer. `src/vocabops/normalize.py` defined `ENGLISH_WORD_MIN_FREQUENCY = 1e-06`; its lemmatizer checked against that constant and `src/vocabops/ingest.py` imported the same object, so the two thresholds could not drift apart. That rationale was **wrong** and is reversed in round 9: sharing forced one value to answer two questions, and when the lemmatizer legitimately moved to `3e-07` the language test silently became too loose. The two constants are now separate; see [decoupled floors](#decoupled-floors-and-the-v3-day-corpus). A token counted as English only when `word_frequency(token, "en") >= 1e-06`.

The floor is two orders of magnitude above wordfreq's noise floor for non-words (`merg` 1.6e-08, `requir` 3.3e-08) and above the trace frequencies at which wordfreq lists Spanish and Portuguese words (`código` 1.7e-08, `repositório` 0.0). That trace presence was exactly what defeated the old `> 0` rule and put `código` at rank 8 of the filtered ranking. The floor stays at or below the technical lemmas the corpus needs (`invalidate` is exactly 1e-06, `invoke` 2.14e-06, `cache` 4.27e-06), but it is still a general-English judgement: `invalidation` (1.7e-07) and `fallback` (4.57e-07) fall below it, so an otherwise English document containing them scores slightly under 1.0 and still clears the 0.6 document cut comfortably.

`--dedup-text` adds exact-text deduplication after the language filter and the event-ID checks. Two events with different IDs but byte-identical stripped text produce one document (the first in file order); the dropped event is counted as `skipped_duplicate_text` and reported as `skipped: N (duplicate text)`. This is exact duplication only — near-duplicates and templates whose tails differ are future work.

```bash
.venv/bin/python -m vocabops.ingest gharchive \
  --input out/gharchive/2026-11-18-3.json.gz \
  --output out/gharchive/documents-clean.jsonl \
  --max-docs 2000 --exclude-bots --min-english-ratio 0.6 --dedup-text

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-clean.jsonl \
  --output out/gharchive-rank-df3-clean \
  --snapshot-id gharchive-2026-11-18-3-proto --min-df 3
```

Counters over the same 3,319 events, in filter order:

| counter | count |
| --- | --- |
| events seen | 3,319 |
| documents written | 658 |
| skipped: no body | 1,874 |
| skipped: bot actor | 603 |
| skipped: below english ratio | 156 |
| skipped: no alphabetic tokens | 1 |
| skipped: duplicate text | 27 |

The totals close: 3,319 − 1,874 − 603 − 156 − 1 − 27 = 658. The floor drops 55 more documents than the old rule (101 → 156) while keeping 685 of the old 740, so the duplicate-text filter removes 27 of those 685 and leaves 658.

The clean corpus is 658 documents and 86,482 normalized tokens, down from 740 documents and 118,572 tokens. The 55 language drops account for 11,360 tokens; the 27 duplicate-text drops account for 20,730, of which 20,406 are 19 copies of one 1,074-token document (see `namespace` below). The `min_df = 3` ranking has 2,513 rows (7,616 at `min_df = 1`), down from 2,938 (10,529). Re-running the ingest and the ranking produced byte-identical files.

Top 30 of the clean `min_df = 3` ranking, with the position the same term held in `out/gharchive-rank-df3-filtered` (`-` means it was below that 2,938-row cut):

| # | term | tf | df | filtered # |
| --- | --- | --- | --- | --- |
| 1 | `sha256` | 50 | 7 | 1 |
| 2 | `worktree` | 24 | 13 | 3 |
| 3 | `stacksjs` | 23 | 18 | 4 |
| 4 | `rustsec` | 13 | 3 | 18 |
| 5 | `18t03` | 11 | 7 | 19 |
| 6 | `docstring` | 11 | 5 | 20 |
| 7 | `userlibs` | 10 | 5 | 28 |
| 8 | `dependabot` | 9 | 4 | 31 |
| 9 | `configmap` | 8 | 3 | 39 |
| 10 | `vercel` | 8 | 3 | 35 |
| 11 | `vitest` | 8 | 6 | 43 |
| 12 | `yml` | 8 | 7 | 44 |
| 13 | `50z` | 7 | 3 | 46 |
| 14 | `clamd` | 7 | 3 | 48 |
| 15 | `nextest` | 7 | 3 | 55 |
| 16 | `pytest` | 7 | 7 | 42 |
| 17 | `toml` | 7 | 5 | 58 |
| 18 | `77bits` | 6 | 3 | 61 |
| 19 | `aarch64` | 6 | 3 | 62 |
| 20 | `allowlist` | 6 | 4 | 64 |
| 21 | `ctest` | 6 | 5 | 66 |
| 22 | `nemoclaw` | 6 | 3 | 71 |
| 23 | `runbook` | 6 | 4 | 75 |
| 24 | `worktrees` | 6 | 4 | 79 |
| 25 | `20z` | 5 | 3 | 89 |
| 26 | `deepseek` | 5 | 4 | 92 |
| 27 | `frontmatter` | 5 | 5 | 2 |
| 28 | `rwelibs` | 5 | 5 | 106 |
| 29 | `serviceaccount` | 5 | 3 | 107 |
| 30 | `unmerged` | 5 | 5 | 109 |

All 18 Spanish/Portuguese rows in the old top 30 (`repositório`, `código`, `fluxo`, `pruebas`, `referencia`, `aceptación`, `criterios`, `regra`, `validación`, `verificar`, `selección`, `contexto`, `contrato`, `critérios`, `mantener`, `origem`, `aprobado`, `arquitetura`) are gone from the clean top 50. At `min_df = 3` they are gone from the ranking entirely, because the documents carrying them fall below the 0.6 ratio. At `min_df = 1`, `fluxo` and `referencia` survive in the tail (a couple of mixed-language documents still score at or above 0.6), but neither is near the top. No non-ASCII term appears in the clean top 50.

Target-term positions with `min_df = 3` (2,938 → 2,513 rows). `retrieve` and `invalidate` are absent from both `min_df = 3` rankings (document frequency 2 and 1); their `min_df = 1` positions show they are still in the corpus.

| term | filtered rank | clean rank | filtered tf / df | clean tf / df | clean rank at `min_df = 1` |
| --- | --- | --- | --- | --- | --- |
| `retrieve` | — | — | 3 / 2 | 3 / 2 | 5,049 |
| `persist` | 1,016 | 604 | 13 / 9 | 13 / 9 | 3,553 |
| `invoke` | 1,194 | 754 | 5 / 5 | 5 / 5 | 3,883 |
| `propagate` | 1,119 | 682 | 3 / 3 | 3 / 3 | 3,742 |
| `reproduce` | 581 | 250 | 77 / 61 | 77 / 61 | 2,681 |
| `invalidate` | — | — | 2 / 1 | 2 / 1 | 3,816 |
| `fallback` | 258 | 102 | 84 / 53 | 41 / 31 | 2,070 |
| `underlying` | 2,337 | 1,860 | 3 / 3 | 3 / 3 | 6,134 |

Most terms keep their frequency and move up only because the vocabulary shrinks (2,938 → 2,513 rows). `fallback` also loses 43 occurrences: the duplicated agent document contained `fallback` twice per copy (40 occurrences across the 20 copies), so removing 19 copies accounts for 38 of the lost occurrences.

The `namespace` result was not what the exact-only limitation predicted. The 20 `atolis-hq-agent` documents are not merely prefix-sharing variants: their extracted text is byte-identical — one unique string of 11,705 characters, all 20 with the same `sha256` after stripping. Exact-text dedup therefore removes 19 of them (20,406 tokens) and leaves one. `namespace` falls from rank 9 (`tf` 665, `df` 28) to rank 83 (`tf` 51, `df` 8); `namespaces` (rank 13, `tf` 180, `df` 20) disappears from the `min_df = 3` ranking entirely. Two other top-30 rows that were entirely supplied by that cluster also disappear: `004b` (rank 6, `tf` 20, `df` 20) and `groupable` (rank 7, `tf` 20, `df` 20). `frontmatter` drops from rank 2 (`tf` 25, `df` 25) to rank 27 (`tf` 5, `df` 5). Near-duplicate detection is still not implemented; this particular cluster simply happened to be exact duplication.

## Full-day run: 24 hourly files

The ingest counters below were produced at the `1e-06` English-ratio floor. The
ranking numbers were then recomputed after the floor change to `3e-07`; the tables
that depend on lemmatization (ranking sizes, top 40, target terms) show the `3e-07`
values with the old position for comparison. The corpus file itself was not
re-ingested, so every tf/df comparison isolates the lemmatizer.

The adapter now accepts `--input` more than once and treats the files as one run. Files are sorted by path before reading, so the output and the dedup winners do not depend on the order the flags are given in. All counters aggregate, the event-ID and exact-text dedup sets span every file, and `--max-docs` caps the total number of documents written. The summary starts with `input files: N`; every other counter line is unchanged. A single `--input` still writes exactly what it did before, plus that one `input files: 1` line.

```bash
INPUTS=$(for f in out/gharchive/2026-11-18/*.json.gz; do printf -- '--input %s ' "$f"; done)

.venv/bin/python -m vocabops.ingest gharchive $INPUTS \
  --output out/gharchive/documents-day.jsonl \
  --max-docs 100000 --exclude-bots --min-english-ratio 0.6 --dedup-text

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day.jsonl \
  --output out/gharchive-rank-day-df3 \
  --snapshot-id gharchive-2026-11-18-day --min-df 3

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day.jsonl \
  --output out/gharchive-rank-day-df10 \
  --snapshot-id gharchive-2026-11-18-day --min-df 10
```

Counters over 24 hourly files (99 MB compressed, 2026-11-18 00:00–23:59 UTC), in filter order:

| counter | count |
| --- | --- |
| input files | 24 |
| events seen | 121,837 |
| documents written | 17,390 |
| skipped: no body | 84,710 |
| skipped: bot actor | 14,874 |
| skipped: below english ratio | 3,954 |
| skipped: no alphabetic tokens | 18 |
| skipped: duplicate text | 891 |
| duplicate event IDs | 0 |
| malformed lines | 0 |
| missing event ID | 0 |

The totals close: 121,837 − 84,710 − 14,874 − 3,954 − 18 − 891 = 17,390. No event ID repeats across the day, so the cross-file event-ID dedup set never fires here; the 891 exact-text duplicates are different events with identical prose — mostly short command comments (`@codex review`, `/trunk merge`, `LGTM`) and repeated templated agent design text. The day corpus is 17,390 documents, 2,188,397 normalized tokens and 33 MB of JSONL, sha256 `74027bb1a605104c6800a7a62731eea1d7a9394cab5ae33f1e3b34ef8207e9ab`. A second ingest run produced a byte-identical file; both pipeline runs also reproduce byte-identically. Ingest takes about 19 s and each pipeline run about 7 s.

Ranking sizes at `3e-07`: 13,242 rows at `min_df = 3` and 6,215 rows at `min_df = 10`
(13,507 and 6,314 at `1e-06`; the merges remove 265 and 99 rows respectively). The
1-hour clean corpus, for comparison, had 658 documents, 86,482 tokens and 2,513 rows
at `min_df = 3`.

Top 40 at `min_df = 10` (positions after the `3e-07` change; `old #` is the position
of the same term under `1e-06`):

| # | term | tf | df | old # |
| --- | --- | --- | --- | --- |
| 1 | `worktree` | 589 | 289 | 1 |
| 2 | `sha256` | 241 | 136 | 2 |
| 3 | `webhook` | 240 | 109 | 3 |
| 4 | `arm64` | 219 | 153 | 4 |
| 5 | `allowlist` | 202 | 132 | 5 |
| 6 | `docstring` | 197 | 138 | 6 |
| 7 | `typecheck` | 191 | 160 | 7 |
| 8 | `vitest` | 191 | 154 | 8 |
| 9 | `yml` | 190 | 121 | 9 |
| 10 | `opencode` | 181 | 90 | 10 |
| 11 | `pytest` | 156 | 103 | 11 |
| 12 | `openapi` | 145 | 97 | 12 |
| 13 | `lockfile` | 140 | 85 | 13 |
| 14 | `soroban` | 140 | 97 | 14 |
| 15 | `coderabbit` | 139 | 83 | 15 |
| 16 | `sbom` | 137 | 21 | 16 |
| 17 | `subagent` | 159 | 65 | 17 |
| 18 | `vercel` | 132 | 72 | 18 |
| 19 | `chatgpt` | 122 | 61 | 19 |
| 20 | `dependabot` | 122 | 71 | 20 |
| 21 | `e2e` | 714 | 415 | 21 |
| 22 | `runbook` | 100 | 67 | 22 |
| 23 | `unmerged` | 97 | 86 | 23 |
| 24 | `toml` | 95 | 66 | 24 |
| 25 | `readback` | 100 | 78 | 25 |
| 26 | `idempotency` | 88 | 69 | 26 |
| 27 | `eslint` | 109 | 65 | 27 |
| 28 | `v0` | 925 | 347 | 28 |
| 29 | `codeql` | 85 | 57 | 29 |
| 30 | `worktrees` | 85 | 59 | 30 |
| 31 | `supabase` | 84 | 44 | 31 |
| 32 | `lgtm` | 83 | 79 | 32 |
| 33 | `mergeable` | 82 | 70 | 33 |
| 34 | `pnpm` | 81 | 47 | 34 |
| 35 | `picomatch` | 75 | 35 | 36 |
| 36 | `deepseek` | 74 | 45 | 37 |
| 37 | `i18n` | 74 | 57 | 38 |
| 38 | `webhooks` | 74 | 45 | 39 |
| 39 | `aarch64` | 72 | 41 | 40 |
| 40 | `if1` | 71 | 21 | 41 |

The list is nearly unchanged: `retries`, which used to sit at 35 as its own row,
merged into `retry` at 105, pulling everything below it up by one.

This is a materially better ranking than the 1-hour one: most of the top 40 is real infrastructure and tooling vocabulary (`worktree`, `webhook`, `allowlist`, `docstring`, `lockfile`, `sbom`, `idempotency`, `mergeable`, `runbook`). Automation and product names are still present (`coderabbit`, `dependabot`, `vercel`, `supabase`, `opencode`, `deepseek`, `chatgpt`, `soroban`), `lgtm` is a review convention rather than vocabulary, and `subagent` is agent-generated prose. `retries` no longer has its own row at 35: at the `3e-07` floor it merges into `retry`, which now ranks 105 (`tf` 1,453, `df` 781).

`min_df = 3` is visibly noisier. Its top 10 is `c606` (681 occurrences in 4 documents; a device codename repeated in generated simulator-preview prose), `worktree`, `sha256`, `webhook`, `arm64`, `allowlist`, `docstring`, `termux` (192 / 3), `typecheck`, `vitest`. Rows with `tf` in the hundreds and `df` in the single digits (`c606`, `termux`, `anyps5` 127 / 7, `boykopovar` 124 / 7) are repetition inside a handful of documents, and `--min-df 10` removes them.

Target-term positions at the `3e-07` floor, day corpus. The 1-hour columns and the
`1e-06` column are historical (those runs used the old floor); tf/df do not change
when only the emitted-row filter changes.

| term | 1h rank | day df3 rank | day df10 rank (`1e-06`) | day df10 rank (`3e-07`) | day tf / df |
| --- | --- | --- | --- | --- | --- |
| `fallback` | 102 | 211 | 199 | **188** | 1,192 / 688 |
| `reproduce` | 250 | 2,670 | 779 | 748 | 1,660 / 1,309 |
| `persist` | 604 | 3,684 | 1,247 | 1,208 | 480 / 327 |
| `invoke` | 754 | 4,371 | 1,606 | 1,560 | 175 / 149 |
| `propagate` | 682 | 4,949 | 1,916 | 1,868 | 67 / 55 |
| `invalidate` | — | 4,006 | 1,404 | 1,362 | 106 / 80 |
| `retrieve` | — | 7,559 | 3,486 | 3,408 | 58 / 48 |
| `underlying` | 1,860 | 9,096 | 4,405 | 4,312 | 76 / 71 |

Every target gains 19×–53× raw frequency. At `min_df = 3` the absolute rank is *worse* than in the 1-hour corpus for most of them even though the corpus is 26× larger, because the 24-hour vocabulary grows and the extra hours contribute proportionally more product, tooling and automation terms. `invalidate` and `retrieve` clear `min_df = 3` for the first time (document frequency 80 and 48). At `min_df = 10` six target terms sit inside the top 2,000, but `fallback` — the most frequent target by far — stays around position 190: it is common (1,192 occurrences) yet not distinctive. After the floor change, `fallbacks` no longer exists as a separate, higher-ranked row (#113 at `1e-06`) and is folded into `fallback`.

## Frequency-floor analysis

Before this round the lemmatizer validated candidate lemmas at `wordfreq >= 1e-06`, the same constant the ingest English-ratio filter uses. That floor is a general-English judgement and sat above two technical words this corpus needs: `fallback` (4.57e-07) and `encode` (8.91e-07). As a result `fallbacks` never merged into `fallback`, and `encoded` / `encoding` / `encodes` never merged into `encode`.

The measurement below was made in round 6 with the constant still at `1e-06`. On that
evidence the constant was lowered to `3e-07` this round; the outcome is recorded at the
end of this section. The measurement is a throwaway script under `out/` (not
committed): it reads `out/gharchive/documents-day.jsonl`, reproduces the lemmatizer's
irregular map, suffix candidates and "most frequent accepted candidate wins" rule at
both floors, and compares the outcomes token by token. Counts are over raw corpus
tokens before stopword removal; none of the 925 changed tokens is a stopword, so no
change is hidden by that step.

| measure | value |
| --- | --- |
| distinct raw tokens | 66,045 |
| raw token occurrences | 3,377,939 |
| distinct tokens whose lemma would change | 925 (1.40% of types) |
| occurrences of those tokens | 11,299 (0.33% of raw tf) |
| distinct lemmas at `1e-06` → `3e-07` | 59,806 → 59,059 |

So the floor is not a large lever on volume — a third of a percent of tokens — but it is a visible lever on vocabulary shape: 747 distinct terms disappear through merging.

Top 25 changed tokens by tf (`@1e-6` is the then-current lemma, `@3e-7` the alternative):

| # | token | tf | lemma @1e-6 | lemma @3e-7 | freq@1e-6 | freq@3e-7 | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `always` | 798 | `always` | `alway` | 5.75e-04 | 3.89e-07 | bad — `alway` is obsolete; the adverb is mangled |
| 2 | `credentials` | 514 | `credentials` | `credential` | 5.50e-06 | 5.62e-07 | correct merge |
| 3 | `endpoints` | 337 | `endpoints` | `endpoint` | 5.50e-07 | 8.51e-07 | correct merge |
| 4 | `authenticated` | 313 | `authenticated` | `authenticate` | 8.51e-07 | 5.25e-07 | correct merge |
| 5 | `retries` | 299 | `retries` | `retry` | 3.72e-08 | 3.72e-07 | correct merge |
| 6 | `superseded` | 285 | `superseded` | `supersede` | 1.48e-06 | 4.79e-07 | correct merge |
| 7 | `speed` | 258 | `speed` | `spe` | 1.00e-04 | 5.75e-07 | bad — `spe` is a fragment, not a word |
| 8 | `parsing` | 249 | `parsing` | `parse` | 7.24e-07 | 9.55e-07 | correct merge |
| 9 | `parses` | 144 | `parses` | `parse` | 1.12e-07 | 9.55e-07 | correct merge |
| 10 | `embedded` | 139 | `embedded` | `embed` | 7.76e-06 | 8.71e-07 | correct merge |
| 11 | `parsed` | 135 | `parsed` | `parse` | 2.40e-07 | 9.55e-07 | correct merge |
| 12 | `timestamps` | 127 | `timestamps` | `timestamp` | 1.66e-07 | 4.17e-07 | correct merge |
| 13 | `retried` | 125 | `retried` | `retry` | 1.23e-07 | 3.72e-07 | correct merge |
| 14 | `encrypted` | 123 | `encrypted` | `encrypt` | 2.63e-06 | 5.75e-07 | correct merge |
| 15 | `encoding` | 119 | `encoding` | `encode` | 2.40e-06 | 8.91e-07 | correct for the verb; the noun sense (`encoding`) is lost |
| 16 | `unbounded` | 116 | `unbounded` | `unbound` | 3.47e-07 | 7.08e-07 | bad — different word (`unbounded` = unlimited, `unbound` = not bound) |
| 17 | `callbacks` | 107 | `callbacks` | `callback` | 2.40e-07 | 6.17e-07 | correct merge |
| 18 | `detached` | 105 | `detached` | `detach` | 6.17e-06 | 9.77e-07 | correct merge |
| 19 | `embedding` | 101 | `embedding` | `embed` | 1.00e-06 | 8.71e-07 | correct for the verb; the ML noun sense is lost |
| 20 | `deps` | 97 | `deps` | `dep` | 4.27e-08 | 8.71e-07 | correct within developer jargon (`dep` is informal but real) |
| 21 | `appends` | 95 | `appends` | `append` | 5.50e-08 | 4.37e-07 | correct merge |
| 22 | `placeholders` | 94 | `placeholders` | `placeholder` | 1.41e-07 | 6.61e-07 | correct merge |
| 23 | `backends` | 90 | `backends` | `backend` | 5.01e-08 | 7.24e-07 | correct merge |
| 24 | `supersedes` | 89 | `supersedes` | `supersede` | 4.07e-07 | 4.79e-07 | correct merge |
| 25 | `lookups` | 85 | `lookups` | `lookup` | 1.10e-07 | 7.24e-07 | correct merge |

Judgement: 22 of the 25 are correct merges or an acceptable verb/noun conflation. Three are wrong: `always` → `alway`, `speed` → `spe`, and `unbounded` → `unbound`. The failing pattern is the same in all three — an `-ed` or `-s` token whose bare stem happens to be a wordfreq entry just above `3e-07` — so lowering the floor does not only admit real technical lemmas, it also admits more stem fragments. Any lower floor would need a guard against exactly those cases.

What happened to the two named terms once the floor was lowered:

- `fallbacks` (tf 55, df 51) — under the old floor it stayed its own row and at `min_df = 10` ranked **#113, above `fallback` at #199**, because wordfreq lists the plural at 1.48e-08 and the singular at 4.57e-07, so the plural got a much higher specificity score. At `3e-07` it merges: `fallback` goes from tf 1,137 / df 653 to tf 1,192 / df 688 and moves #199 → #188 (the round-6 estimate was ~#189).
- `encoded` (tf 84, df 69), plus `encodes` (37 / 30) and 119 of the 130 `encoding` occurrences — all merge into `encode` at `3e-07`. `encode` goes from tf 61 / df 46 (rank #1,727 at `min_df = 10`) to tf 301 / df 195 and rank #789 (the estimate was ~#827). The remaining 11 `encoding` occurrences come from `encodings`, which already maps to `encoding` at both floors; `encoding` survives as a low-ranked row (#4,355, tf 11, df 11).
- `invalidation` is unaffected: it is a derivational form the suffix rules never propose, so no floor change merges it into `invalidate`.

### Applied: the lemmatizer floor is `3e-07`

The constant in `src/vocabops/normalize.py` is now `LEMMA_MIN_FREQUENCY = 3e-07` (it was
`ENGLISH_WORD_MIN_FREQUENCY` until round 9 renamed it). The ingest English-ratio filter
no longer imports it: `src/vocabops/ingest.py` defines its own
`ENGLISH_RATIO_MIN_FREQUENCY = 1e-06`. The two thresholds moved apart in round 9 after
the round-8 regression, when the shared value let 284 French/Spanish documents into the
day corpus; see [decoupled floors](#decoupled-floors-and-the-v3-day-corpus). On
the fixed day corpus the chain of effects of the lemmatizer floor alone is:

| measure | `1e-06` | `3e-07` |
| --- | --- | --- |
| `min_df = 10` rows | 6,314 | 6,215 |
| `min_df = 3` rows | 13,507 | 13,242 |
| `fallback` rank / tf / df | 199 / 1,137 / 653 | 188 / 1,192 / 688 |
| `encode` rank / tf / df | 1,727 / 61 / 46 | 789 / 301 / 195 |
| `retry` rank / tf / df | — (`retries` #35) | 105 / 1,453 / 781 |

`fallbacks`, `encoded`, `encodes`, `retries`, `credentials` and `endpoints` no longer
exist as separate rows. The three known bad outcomes land as follows at `min_df = 10`:
`alway` #258 (tf 798, df 668), `spe` #699 (tf 258, df 127), `unbound` #975 (tf 160,
df 114). The stem `speed` also survives as its own small row (#6,171, tf 15, df 14) from
the plural `speeds`, which now lemmatizes to `speed` rather than to `spe`.

The ingest side effect was real and was not used to rebuild the v0/v0.1 corpora: re-running the
day ingest at `3e-07` (same flags, no `--dedup-text`) kept 294 more documents — the
language-filter drop fell from 3,954 to 3,660 and 18,575 documents were written before
text dedup. The 17,390-document corpus used for every v0/v0.1 ranking here was built at
`1e-06`, so those tf/df differences come from lemmatization alone. Round 9 reverses that
side effect: with the ratio floor back at `1e-06`, the v3 day corpus is byte-identical
to the v1 corpus (same sha256), and v0.2 is ranked from it.

Tests: the old assertion that pinned the constant (`test_english_floor_is_shared_with_the_lemmatizer`)
was replaced in round 9 by tests that pin each floor separately and assert they differ
(`test_english_ratio_floor_is_pinned_to_ingest`,
`test_english_ratio_floor_is_not_the_lemmatizer_floor`,
`test_lemmatize_floor_is_pinned_and_distinct_from_the_ratio_floor`), plus a Spanish
fixture that passed the 0.6 cut at `3e-07` and must drop at `1e-06`. The tests for the
four required merges (`fallbacks`, `encoded`, `credentials`, `retries`) and the three
known defects still hold unchanged, so a later change cannot silently "fix" or worsen
them without a test failure.

## Tokenizer rules and the re-ingested day corpus (v2)

The Core 500 v0 audit (see [the evaluation](core500-evaluation.md)) found 82 fragment
rows in its top 500. The largest class was tokenizer-made: an ISO timestamp such as
`2026-11-18T02:07:00Z` became `18t02` / `07` / `00z` under the bare `\w+` tokenizer and
entered the ranking as vocabulary. Three rules in `tokenize()` now remove that class;
they run in the tokenizer rather than in `clean_text()` so the pipeline and the ingest
English-ratio test see identical tokens:

1. ISO-8601 datetimes (with optional fractional seconds and `Z`/offset) and bare ISO
   dates are stripped from the text before tokenizing.
2. Tokens matching `^\d+(px|pt|rem|em)$` are dropped (CSS measurements).
3. Digit-first tokens with a digit after at least one letter are dropped
   (`^\d.*[A-Za-z].*\d$`, which catches `18t02` and `7a7e3f9f`).

Letter-first digit tokens are never dropped, so real technical terms survive:
`sha256` (#2), `arm64` (#4), `e2e` (#19), `i18n` (#36), `aarch64` (#42), `base64` (#52)
and `x64` (#135) all keep their rows. The rules are pinned by
`test_tokenize_strips_full_iso_timestamps_before_splitting`,
`test_tokenize_strips_standalone_iso_dates_but_keeps_years`,
`test_tokenize_drops_css_measurement_tokens`,
`test_tokenize_drops_digit_first_shards_only` and
`test_tokenize_keeps_vocabulary_and_drops_timestamp_css_shards`; the suite is 91 tests
after round 9's floor tests.

The day corpus was then re-ingested with the same flags at the `3e-07` floor:

```bash
INPUTS=$(for f in out/gharchive/2026-11-18/*.json.gz; do printf -- '--input %s ' "$f"; done)

.venv/bin/python -m vocabops.ingest gharchive $INPUTS \
  --output out/gharchive/documents-day-v2.jsonl \
  --max-docs 100000 --exclude-bots --min-english-ratio 0.6 --dedup-text

.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day-v2.jsonl \
  --output out/gharchive-rank-day-v2-df10 \
  --snapshot-id gharchive-2026-11-18-day-v2 --min-df 10
```

| counter | v1 (`1e-06`) | v2 (`3e-07`) | delta |
| --- | --- | --- | --- |
| input files | 24 | 24 | 0 |
| events seen | 121,837 | 121,837 | 0 |
| documents written | 17,390 | 17,674 | +284 |
| skipped: no body | 84,710 | 84,710 | 0 |
| skipped: bot actor | 14,874 | 14,874 | 0 |
| skipped: below english ratio | 3,954 | 3,660 | −294 |
| skipped: no alphabetic tokens | 18 | 18 | 0 |
| skipped: duplicate text | 891 | 901 | +10 |

The totals close (121,837 − 84,710 − 14,874 − 3,660 − 18 − 901 = 17,674). Of the 294
documents the lower floor admits, 10 are exact duplicates and 284 are new. The v2
corpus is 17,674 documents, 2,225,982 normalized tokens (+37,585, +1.7%), sha256
`998195329e64b08b7a7d2b3c0d4c55982159ad90af76fcda2fac5e9a9df6d6e6`. A second ingest,
pipeline run and candidate extraction each reproduced byte-identically. At `min_df 10`
the v2 ranking has 6,474 rows (6,215 in v1); every target slips a few places on the
larger vocabulary (`fallback` 188 → 199, `reproduce` 748 → 832, `persist` 1,208 →
1,363, `invalidate` 1,362 → 1,522, `invoke` 1,560 → 1,731, `propagate` 1,868 → 2,056,
`retrieve` 3,408 → 3,652, `underlying` 4,312 → 4,560).

Effect on the ranking: 31 of the 82 v0 fragment rows are gone from the ranking entirely
(25 timestamp shards, 5 CSS measurements, 1 hex string) and no timestamp or CSS row
remains in the top 500. The top 40 barely moves: `yml` 9 → 6, `e2e` 21 → 19, `openbot`
46 → 37, `deepseek` 36 → 29, `if1` 40 → 44. Residuals stay visible and are documented
rather than hidden: `v0` (#30), `1080p` (#265) and `500s` (#402) are letter-first digit
tokens the rules keep by design, and one time shard survives at #1,990 — `00z`, from
forms such as `2026-11-18 ~10:00Z` where a separator stops the datetime pattern.

The fragment share of the top 500 did **not** fall: 16.4% → 22.0%. The 284 new
documents are disproportionately French and Spanish, because the `3e-07` English-ratio
floor counts many of wordfreq's trace-level French and Spanish entries as English. They
add 64 new non-English rows, including `aucun` at #40 (from #239). The tokenizer fix
removed everything it targeted; the language filter is now the dominant defect.

## Decoupled floors and the v3 day corpus

The lemmatizer floor and the English-ratio floor were one constant until this round. They
answer different questions — *is this candidate a plausible headword?* versus *is this
token evidence that the document is English?* — and round 8's 284 extra French/Spanish
documents were the cost of sharing. The constants are now separate:

| constant | module | value | role |
| --- | --- | --- | --- |
| `LEMMA_MIN_FREQUENCY` | `src/vocabops/normalize.py` | `3e-07` | accepts candidate lemmas |
| `ENGLISH_RATIO_MIN_FREQUENCY` | `src/vocabops/ingest.py` | `1e-06` | counts a token as document-level English evidence |

`3e-07` keeps the round-6/7 lemmatizer evidence (`fallback` 4.57e-07 and `encode`
8.91e-07 must validate; the three known stem defects stay as documented). `1e-06` is
the value at which round 5 measured the language test working: all Spanish and
Portuguese documents dropped from the 1-hour corpus.

The day ingest was re-run at those values (`documents-day-v3.jsonl`):

| counter | v1 (`1e-06`, old tokenizer) | v2 (`3e-07`) | v3 (`1e-06`) |
| --- | --- | --- | --- |
| documents written | 17,390 | 17,674 | 17,390 |
| skipped: below english ratio | 3,954 | 3,660 | 3,954 |
| skipped: duplicate text | 891 | 901 | 891 |
| normalized tokens | 2,188,397 | 2,225,982 | 2,181,317 |
| corpus sha256 | `74027bb1…` | `99819532…` | `74027bb1…` |

**v3 is byte-identical to v1.** Restoring `1e-06` reproduces the round-5 corpus exactly;
the 284 documents are gone, no other document changed, and no document moves across the
0.6 cut because of the tokenizer (the tokens it removes were never ratio evidence for a
document that sat near the boundary). The 7,080-token drop against v1 is the tokenizer
on the same 17,390 documents; the 44,665-token drop against v2 adds the 284 dropped
documents. Two ingests, two pipeline runs and two candidate extractions all reproduced
byte-identically; the `min_df = 10` ranking has 6,182 rows (v1 6,215, v2 6,474).

The re-ranked candidate is `data/core500-v0.2.jsonl` (snapshot
`gharchive-2026-11-18-day-v3`, cut score 5.919). The fragment bucket falls from v0.1's
110 rows (22.0%) to 53 (10.6%), non-English rows from 78 to 18 with none above #211, and
every target term ranks 14–281 places better than in v0.1 (3–33 better than in v0) because
the competing vocabulary is 292 rows smaller. The full comparison is in
[Core 500 candidate — evaluation, Part 3](core500-evaluation.md#part-3--v02).

## Vocabulary and technical views

The Phase 2 review item "review high-ranking technical nouns separately from transferable
English vocabulary" is now two artifacts, both generated from
`data/ranking-v3-classification.jsonl` by `scripts/build_views.py`:
`data/core500-vocab-v0.jsonl` (buckets a + c, 500 rows: 342 a, 158 c) and
`data/core500-technical-v0.jsonl` (bucket b, top 300). Filling the vocabulary view
required classifying ranks 501–1020; a + c reached exactly 500 at rank 1020, so the
review stopped there (1,020 rows: a 342, b 403, c 158, d 104, e 13).

The split is a review, not a filter. Both deterministic alternatives were measured on
the 437 scored rows of the v0.2 audit and failed: a wordfreq cut at `1e-7` agrees 56.8%
(59.3% at the best threshold, because 41 of 103 (a) terms are as absent from general
English as product names), and a capitalization ratio has medians 0.07 for (a) and 0.12
for (b) — it catches 23% of (b) at a usable precision, and 84% only by mislabelling 71%
of the vocabulary side. The full numbers, the two views' composition and the technical
view's legitimate use as an ecosystem watchlist are in
[Core 500 candidate — evaluation, Part 4](core500-evaluation.md#part-4--vocabulary-and-technical-views).

## Corpus-attested headwords and the v4 day ranking

The Core 500 review (Part 4 of [the evaluation](core500-evaluation.md)) found that the
vocabulary view contains `rebase`, `rebased` and `rebases` as three rows for one lemma,
and five rows for the `dedupe`/`dedup` family. The lemmatizer's candidate generation was
never the problem: the suffix rules propose `rebase` for `rebased` and `rebases`. The
validation was too narrow. `rebase` is wordfreq **6.46e-08**, below the `3e-07` lemma
floor, and `dedup`/`dedupe` are **0.0**, so no candidate could ever validate even though
`rebase` and `dedup` are themselves ranking rows attested across the corpus.

The corpus is now allowed to vouch for its own headwords. `src/vocabops/normalize.py`
defines `ATTESTATION_MIN_DOCUMENTS = 3` and `attested_headwords()`, and the pipeline runs
a pre-pass before lemmatizing:

1. every document is tokenized with the existing rules (`tokenize(clean_text(text))`);
2. each raw form is counted in how many documents it occurs in (once per document);
3. forms with a document count `>= 3` are the attested set.

Candidate selection is unchanged except for acceptance: among the rule-generated
candidates, the highest-wordfreq candidate wins that is **either** wordfreq-valid
(`>= 3e-07`, as before) **or** in the attested set. Because candidates are ranked by
wordfreq, an attested-only candidate can only win when no wordfreq-valid candidate
exists; attestation never overrides a dictionary word. If no candidate qualifies, the
token is returned unchanged, as before. `lemmatize()` and `normalize()` keep their pure
single-token behaviour by defaulting the attested set to empty; only the pipeline passes
one in. The manifest records `attestation_min_documents` and `attested_forms`.

**Why three documents.** It is the smallest count that is corpus evidence rather than one
author's repetition (repetition inside one document counts once), and on a 17,390-document
day it is a low bar for a shared term. It is deliberately not zero or one: a one-off typo
or template string must not become a headword.

**Why this does not break reproducibility.** The pre-pass adds no clock, no randomness
and no dependence on hash order: documents are read in the same sorted/line order as the
rest of the pipeline, the attested set is a `frozenset` of forms selected by a fixed
integer threshold, and lemmatization consults it by membership only. The same input
therefore produces the same attested set and byte-identical outputs. Two v4 runs were
compared with `cmp` and matched, and the manifest carries the attested-set size so a run
can be checked against this document.

On the five-document fixture corpus, 35 raw forms are attested and **no token changes
lemma**: the fixture ranking is identical to the pre-change ranking (148 ranked terms,
same tokens). The new tests build dedicated corpora for the merge cases instead of
changing the shared fixture.

### v4 measurements

Command (unchanged inputs, so only the lemmatizer differs from v3):

```bash
.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day-v3.jsonl \
  --output out/gharchive-rank-day-v4-df10 \
  --snapshot-id gharchive-2026-11-18-day-v4 --min-df 10
```

| measure | v3 | v4 |
| --- | --- | --- |
| `min_df 10` rows | 6,182 | 6,137 |
| attested forms (raw types: 62,083) | — | 17,502 |
| raw token types whose lemma changed | — | 832 (1.34% of types) |
| occurrences whose lemma changed (of 3,370,859) | — | 6,519 (0.19%) |
| headwords that absorbed at least one form | — | 624 |

121 terms left the ranking and 76 entered it, which is the −45 row difference: most
removed inflections folded into a headword that was already ranked, while enough new
headwords crossed `df >= 10` to add rows.

**`rebase`.** The four rows collapse into one, and the tf adds exactly:

| term | v3 rank | v3 tf / df | v4 rank | v4 tf / df |
| --- | --- | --- | --- | --- |
| `rebase` | 69 | 335 / 216 | **37** | 492 / 317 |
| `rebased` | 103 | 115 / 101 | — | folded into `rebase` |
| `rebases` | 178 | 26 / 20 | — | folded into `rebase` |
| `rebasing` | 648 | 16 / 16 | — | folded into `rebase` |

**`dedup` family.** `deduped` (5) merges into `dedup`; `dedupes` (4) into `dedupe`;
`deduplicated` (20), `deduplicates` and `deduplicating` (10 together) into
`deduplicate`. `deduplication` is a derivational noun the suffix rules never propose, so
it stays its own row, as it did in v3.

| term | v3 rank | v3 tf / df | v4 rank | v4 tf / df |
| --- | --- | --- | --- | --- |
| `dedup` | 92 | 40 / 35 | 90 | 45 / 39 |
| `dedupe` | 80 | 45 / 39 | 81 | 49 / 41 |
| `deduplicate` | 277 | 17 / 15 | **86** | 47 / 36 |
| `deduplicated` | 241 | 20 / 16 | — | folded into `deduplicate` |
| `deduplication` | 420 | 57 / 48 | 406 | 57 / 48 |

**Top 20 newly merged families by absorbed tf** (measured by comparing token→lemma maps
with and without the attested set, over the whole ranking, not just the top):

| headword | wordfreq | absorbed tf | forms |
| --- | --- | --- | --- |
| `maintainer` | 2.40e-07 | 177 | `maintainers` |
| `truncate` | 1.74e-07 | 174 | `truncated` 125, `truncates` 27, `truncating` 22 |
| `ceil` | 7.24e-08 | 169 | `ceiling` (see the defect below) |
| `rebase` | 6.46e-08 | 157 | `rebased` 115, `rebases` 26, `rebasing` 16 |
| `hardcode` | 1.62e-08 | 131 | `hardcoded` 99, `hardcodes` 18, `hardcoding` 14 |
| `deliverable` | 2.69e-07 | 118 | `deliverables` |
| `deprecate` | 7.59e-08 | 109 | `deprecated` 97, `deprecating` 8, `deprecates` 4 |
| `serialize` | 6.03e-08 | 107 | `serialized` 68, `serializes` 32, `serializing` 7 |
| `redact` | 1.05e-07 | 106 | `redacted` 97, `redacts` 7, `redacting` 2 |
| `overwrite` | 2.69e-07 | 105 | `overwrites` 75, `overwriting` 30 |
| `refactor` | 7.59e-08 | 91 | `refactors` 49, `refactoring` 32, `refactored` 10 |
| `recompute` | 2.24e-08 | 90 | `recomputed` 58, `recomputes` 25, `recomputing` 7 |
| `worktree` | 0.0 | 85 | `worktrees` |
| `reorder` | 2.29e-07 | 84 | `reordering` 43, `reordered` 34, `reorders` 7 |
| `param` | 2.75e-07 | 83 | `params` |
| `webhook` | 0.0 | 74 | `webhooks` |
| `symlink` | 2.82e-08 | 72 | `symlinks` 47, `symlinked` 24, `symlinking` 1 |
| `sanitize` | 2.63e-07 | 66 | `sanitized` 60, `sanitizes` 6 |
| `util` | 1.00e-07 | 66 | `utils` |
| `untrack` | 0.0 | 65 | `untracked` |

The rest of the top 50 continues the pattern (`initialize`, `guardrail`, `allowlist`,
`docstring`, `paginate`, `enqueue`, `checksum`, `subagent`, `debounce`, `hostname`,
`lockfile`, `uuid`). Non-English plurals also merge correctly (`fichiers` → `fichier`,
`criterios` → `criterio`, `autres` → `autre`); that consolidates non-English rows but
does not make them English.

**The eight target terms** (tf/df unchanged — the corpus is the same; only rank moves):

| term | v3 rank | v4 rank |
| --- | --- | --- |
| `fallback` | 185 | 195 |
| `reproduce` | 716 | 695 |
| `persist` | 1,176 | 1,143 |
| `invalidate` | 1,329 | 1,302 |
| `invoke` | 1,527 | 1,497 |
| `propagate` | 1,835 | 1,798 |
| `retrieve` | 3,375 | 3,332 |
| `underlying` | 4,279 | 4,233 |

Target-adjacent rows: `retry` 104 → 112, `credential` 302 → 308, `endpoint` 407 → 394,
`encode` 757 → 731. Most terms move up because 45 rows left the ranking; `fallback`,
`retry` and `credential` slip because newly merged headwords such as `hardcode` (#29) and
`paginate` (#68) enter above them.

**The three known stem defects are unchanged.** `alway` #252 → 258 (tf 798, df 668),
`spe` #667 → 648 (tf 258, df 127), `unbound` #943 → 916 (tf 160, df 114). Their tf and df
are identical; only the rank moves with the smaller vocabulary. Attestation did not add a
second producer of `alway`: the day corpus produces `alway` only from `always`, and the
fixture test pins that.

**One new bad merge, stated plainly: `ceiling` → `ceil`.** `ceiling` is an ordinary word
(wordfreq 1.51e-05); the `-ing` rule proposes `ceil`, which wordfreq lists at 7.24e-08 but
the corpus attests as a standalone function name. 169 of its 184 occurrences move to
`ceil` (v4 #205, tf 173, df 91); the other 15 come from `ceilings`, whose candidate
`ceiling` is wordfreq-valid and keeps its own row (#5,511). This is the known bare-stem
defect class (`alway`, `spe`, `unbound`) reached through attestation rather than through
the floor, and it is the price of the rule as specified: attestation can only accept a
candidate the suffix rules propose, and for `ceiling` the rules propose no alternative.
A future guard that compares the original token's frequency (or POS) would remove this
case without touching the intended merges; it is not part of this round.

### The frequency-ratio guard and v5

The guard that Part 5 called future work is now `MIN_CANDIDATE_FREQUENCY_RATIO = 0.02` in
`src/vocabops/normalize.py`. A candidate is rejected when the original token has nonzero
wordfreq and `word_frequency(candidate) / word_frequency(token) < 0.02`. The test runs on
every acceptance path, including attested ones, so `ceil` (attested as a function name)
still loses to `ceiling`. Tokens at wordfreq 0 bypass the ratio: the `dedup` family has no
ratio to judge, and attestation governs. The threshold is a gap cut, not a tuned value —
the good merges measured run 0.102 (`credentials` → `credential`) and above; the bad ones
(`always` → `alway` 0.00068, `ceiling` → `ceil` 0.0048, `speed` → `spe` 0.0058) sit below
0.006.

Command (same corpus as v4, so only lemmatization differs):

```bash
.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day-v3.jsonl \
  --output out/gharchive-rank-day-v5-df10 \
  --snapshot-id gharchive-2026-11-18-day-v5 --min-df 10
```

**Blast radius, computed from the two lemma maps.** 36 raw types (2,074 occurrences) change
lemma, all back to themselves: 10 are intended blocks (`always`, `series`, `speed`,
`ceiling`, `morning`, `physics`, `clothes`, `politics`, `naked`, `netherlands`; 1,672
occurrences), 3 are non-English (`outils`, `règles`, `résultats`; 9 occurrences), and 23
are collateral damage (393 occurrences). The collateral class is real and is the round's
main surprise: the attestation win class has **wordfreq-0.0 candidates** (`webhook`,
`untrack`, `unassign`, `paginate`, `precompute`, `prefill`, …), so its ratio is 0 and the
guard rejects every one. `webhooks` is again its own row (#40), `webhook` drops from tf 314
to 240, and `untrack` disappears below `df 10` behind `untracked` (#372). The full 36-row
table and the per-row judgement are in
[Part 6](core500-evaluation.md#part-6--the-frequency-ratio-guard-the-v5-ranking-and-views-v1).
A narrow exemption for attested zero-frequency candidates would keep `always`, `speed` and
`ceiling` blocked and restore those 20 merges; that is the next lemmatizer change.

| measure | v4 | v5 |
| --- | --- | --- |
| `min_df 10` rows | 6,137 | 6,134 |
| terms leaving / entering | — | 14 / 11 |
| `fallback` rank | 195 | 191 |
| `reproduce` rank | 695 | 688 |
| `retry` / `credential` / `endpoint` / `encode` | 112 / 308 / 394 / 731 | 108 / 302 / 388 / 724 |
| `alway` | #258, tf 798 | gone; `always` #5,361 |
| `spe` | #648, tf 258 | gone; `speed` #4,845 |
| `ceil` | #205, tf 173 | gone; `ceiling` #3,308 |
| `unbound` | #916, tf 160 | #910, tf 160 |

Top-500 composition (v5 classification): (a) 109, (b) 236, (c) 91, (d) 54, (e) 10.

### Views v1

The views are no longer stale. `data/ranking-v5-classification.jsonl` reuses the v3 bucket
for every term that still exists (928 of its 1,004 rows) and classifies the 76 new ones;
the vocabulary side reaches 500 at rank 1,004. `scripts/build_views.py` then regenerates
`data/core500-vocab-v1.jsonl` (500 rows: 339 a, 161 c) and
`data/core500-technical-v1.jsonl` (300 b rows, covering v5 ranks 1–679). Against the v0
views: 58 vocabulary rows are new and 58 dropped (mostly inflections merged in v4), 442 are
shared; 26 technical rows are new. Target view-ranks: `fallback` #62 (was #60), `reproduce`
#307 (was #316), `retry` #37 (was #34). Both files regenerate byte-identically (`cmp`).

## Known limitations

- **Fixture corpus plus one bounded GH Archive day.** The fixture ranking demonstrates the mechanism and says nothing about corpus-scale vocabulary. A full day (24 hourly files; 17,390 documents in v1 and v3, 17,674 in v2) has been run, but Stack Overflow and CodeSearchNet adapters are not implemented, and one day of issue and pull-request prose is still a narrow, English-dominant slice of the ecosystem — the language filter still leaks a small Latin-script and Devanagari residue, as the v0.2 ranking shows.
- **Dictionary-validated lemmatizer, not a morphological analyzer.** An irregular-verb map plus suffix rules that propose candidates, accepted when `wordfreq` puts them at `3e-07` or the corpus attests them in `>= 3` documents, and then filtered by the `0.02` ratio guard against bare stems. There is no prefix handling and no POS tagging, so homographs share one row. The threshold is a general-English judgement: a real technical lemma below it keeps its inflections as separate rows unless the corpus attests the lemma (which is how `rebase` and `dedup` merge), and a candidate can still be wrong — `unbounded` becomes `unbound` because both are real words and the ratio guard cannot separate them. The guard does stop `always` → `alway`, `speed` → `spe` and `ceiling` → `ceil`, but its literal form also blocks real merges whose candidate has wordfreq 0.0 (`webhooks` → `webhook`, `untracked` → `untrack`); 23 such merges are documented in [Part 6](core500-evaluation.md#part-6--the-frequency-ratio-guard-the-v5-ranking-and-views-v1). When no candidate passes, the token is returned unchanged, which is safe but leaves prefixed forms such as `unchanged` unmerged with `changed`.
- **Tokenization still keeps some digit-bearing fragments.** The three digit rules remove ISO timestamps, CSS measurements and digit-first shards, which deleted 31 fragment rows from the v0 ranking, but letter-first tokens are kept by design (`sha256`, `arm64`, `e2e`) and that also keeps `v0`, `1080p`, `500s` and `v006`. One time shard also survives (`00z`, #1,776, from `2026-11-18 ~10:00Z` forms). In the v0.2 top 500, 35 of the 53 fragment rows are the classes these rules deliberately keep (31 identifier/codename/version shards and 4 other artifacts); the other 18 are non-English strings, which the tokenizer cannot fix.
- **wordfreq baseline.** General-English rates come from `wordfreq` per-token frequency, not a frequency-matched corpus. `wordfreq` combines several sources with its own weighting, and its coverage of technical vocabulary is uneven, which distorts scores for rare terms.
- **Single-token terms only.** No multi-word expressions or collocations.
- **Thin smoothing.** With a corpus this small, `alpha = 1` and `vocab_size` in the denominator dominate absolute scores; only the ordering is meaningful. One-off rare words can outrank repeated target terms.
- **Thin thresholds.** `--min-df` provides a document-frequency floor, and the opt-in ingest filters remove `[bot]` actors, documents below the `1e-06` English-token ratio floor (`ENGLISH_RATIO_MIN_FREQUENCY`), and exact duplicate text (`--dedup-text`), but there is no minimum term frequency, no near-duplicate or template filter, and no stopword extension for product names. Automation without a `[bot]` login can still reach the top, and mixed-language documents that clear the 0.6 ratio still contribute non-English terms — in v0.2 they are 18 of the top 500 (3.6%), because a 1e-06 frequency floor cannot separate a mostly-English document that quotes a French or Italian sentence.

Reproducibility rules for runs of this pipeline are in [Pipeline conventions](pipeline-conventions.md).
