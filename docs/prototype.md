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

A derived candidate counts as real when `word_frequency(candidate, "en") >= 1e-06`; among accepted candidates the most frequent wins. The original token is never in that comparison, because an inflected form can be more frequent than its lemma (`required` 1.05e-04 vs `require` 6.03e-05). If no candidate passes, the token is returned unchanged: `unchanged` stays `unchanged` instead of becoming `unchange`. Short tokens (length ≤ 3), non-alphabetic tokens, and `-ing` stems shorter than four characters are left alone, so `string` and `bus` survive.

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

Every other event type is skipped. A document requires a non-empty body; empty and whitespace-only bodies are skipped, and there is no bot or template filter. Each record is `{doc_id, source_family, repo, text}`, where `doc_id = sha256("gharchive/" + event id)` and duplicate event IDs are dropped. The adapter stops at `--max-docs` (default 2000).

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

## Known limitations

- **Fixture corpus only, plus one bounded GH Archive hour.** The fixture ranking demonstrates the mechanism and says nothing about corpus-scale vocabulary. The GH Archive adapter exists and one hour has been run, but Stack Overflow and CodeSearchNet adapters are not implemented, and one hour of issue and pull-request prose is not a corpus.
- **Dictionary-validated lemmatizer, not a morphological analyzer.** An irregular-verb map plus suffix rules that propose candidates, filtered by `wordfreq` at `1e-06`. There is no prefix handling and no POS tagging, so homographs share one row. The threshold is a general-English judgement: a real technical lemma below it keeps its inflections as separate rows (`fallback` at 4.57e-07, so `fallbacks` does not merge; `encode` at 8.91e-07, so `encoded` / `encoding` stay apart), and a real word that happens to match a stem can win (`rune` is a candidate for `running` but loses to the much more frequent `run`). When no candidate passes, the token is returned unchanged, which is safe but leaves prefixed forms such as `unchanged` unmerged with `changed`.
- **wordfreq baseline.** General-English rates come from `wordfreq` per-token frequency, not a frequency-matched corpus. `wordfreq` combines several sources with its own weighting, and its coverage of technical vocabulary is uneven, which distorts scores for rare terms.
- **Single-token terms only.** No multi-word expressions or collocations.
- **Thin smoothing.** With a corpus this small, `alpha = 1` and `vocab_size` in the denominator dominate absolute scores; only the ordering is meaningful. One-off rare words can outrank repeated target terms.
- **Thin thresholds.** `--min-df` now provides a document-frequency floor, but there is no minimum term frequency, no boilerplate/bot down-ranking, and no stopword extension for product names, so automation text and rare one-off tokens still reach the top.

Reproducibility rules for runs of this pipeline are in [Pipeline conventions](pipeline-conventions.md).
