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

A derived candidate counts as real when `word_frequency(candidate, "en") >= 1e-06`; among accepted candidates the most frequent wins. The same `ENGLISH_WORD_MIN_FREQUENCY` constant is used by the ingest English-ratio filter, so the two thresholds cannot drift apart. The original token is never in that comparison, because an inflected form can be more frequent than its lemma (`required` 1.05e-04 vs `require` 6.03e-05). If no candidate passes, the token is returned unchanged: `unchanged` stays `unchanged` instead of becoming `unchange`. Short tokens (length ≤ 3), non-alphabetic tokens, and `-ing` stems shorter than four characters are left alone, so `string` and `bus` survive.

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

`src/vocabops/ingest.py` is the first real source adapter. It streams a GH Archive hourly event file (local `.json.gz` / `.json` or an http(s) URL) line by line, keeps the human-written prose, and writes one JSON document per line:

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
- `--min-english-ratio R` — tokenize the extracted text with the normalizer's `tokenize()`, keep alphabetic tokens only, and compute `known / total`. A token is known only when `word_frequency(token, "en") >= 1e-06`, the shared `ENGLISH_WORD_MIN_FREQUENCY` constant defined in `src/vocabops/normalize.py` and imported here; the lemmatizer's candidate check uses the same constant, so the two thresholds cannot drift apart. Keep the document when the ratio is `>= R`; drop it when the ratio is lower. A document with zero alphabetic tokens is skipped as empty. `R` must be in 0..1.
- `--dedup-text` — after the other filters, drop a document whose stripped full text is byte-identical to a document already kept in the run. Comparison is `sha256` of `text.strip()` and the first occurrence in file order wins. Off by default. This is exact duplication only: near-duplicates, and templated documents that share a long prefix but differ in the tail, are not detected.

Both filters run at fixed positions: event-type/body extraction, then bot filter, then language filter, then event-ID checks, then optional exact-text deduplication, then `--max-docs`. Every dropped event lands in exactly one counter, and `ingest()` returns them all: `events_seen`, `documents_written`, `skipped_no_body`, `skipped_bot`, `skipped_language`, `skipped_no_tokens`, `skipped_duplicate_text`, `duplicates`, `malformed`, `missing_id`. Neither flag touches normalization, the lemmatizer, `se_specificity`, or the ranking; exclusion happens only here.

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

The token test now uses the same "real English word" floor as the lemmatizer. `src/vocabops/normalize.py` defines `ENGLISH_WORD_MIN_FREQUENCY = 1e-06`; its lemmatizer checks against that constant and `src/vocabops/ingest.py` imports the same object, so the two thresholds cannot drift apart silently. A token counts as English only when `word_frequency(token, "en") >= 1e-06`.

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

## Known limitations

- **Fixture corpus only, plus one bounded GH Archive hour.** The fixture ranking demonstrates the mechanism and says nothing about corpus-scale vocabulary. The GH Archive adapter exists and one hour has been run, but Stack Overflow and CodeSearchNet adapters are not implemented, and one hour of issue and pull-request prose is not a corpus.
- **Dictionary-validated lemmatizer, not a morphological analyzer.** An irregular-verb map plus suffix rules that propose candidates, filtered by `wordfreq` at `1e-06`. There is no prefix handling and no POS tagging, so homographs share one row. The threshold is a general-English judgement: a real technical lemma below it keeps its inflections as separate rows (`fallback` at 4.57e-07, so `fallbacks` does not merge; `encode` at 8.91e-07, so `encoded` / `encoding` stay apart), and a real word that happens to match a stem can win (`rune` is a candidate for `running` but loses to the much more frequent `run`). When no candidate passes, the token is returned unchanged, which is safe but leaves prefixed forms such as `unchanged` unmerged with `changed`.
- **wordfreq baseline.** General-English rates come from `wordfreq` per-token frequency, not a frequency-matched corpus. `wordfreq` combines several sources with its own weighting, and its coverage of technical vocabulary is uneven, which distorts scores for rare terms.
- **Single-token terms only.** No multi-word expressions or collocations.
- **Thin smoothing.** With a corpus this small, `alpha = 1` and `vocab_size` in the denominator dominate absolute scores; only the ordering is meaningful. One-off rare words can outrank repeated target terms.
- **Thin thresholds.** `--min-df` provides a document-frequency floor, and the opt-in ingest filters remove `[bot]` actors, documents below the shared `1e-06` English-token floor, and exact duplicate text (`--dedup-text`), but there is no minimum term frequency, no near-duplicate or template filter, and no stopword extension for product names. Automation without a `[bot]` login can still reach the top, and mixed-language documents that clear the 0.6 ratio still contribute non-English terms to the tail.

Reproducibility rules for runs of this pipeline are in [Pipeline conventions](pipeline-conventions.md).
