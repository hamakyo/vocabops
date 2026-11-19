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

## Fixture corpus

Five short documents, all original prose:

- `01-bug-report.txt` — a cache/session bug report with a fenced log block and a URL
- `02-code-review-thread.txt` — a review thread about retries and fallbacks
- `03-readme-excerpt.txt` — a storage-layer README excerpt with inline code and an HTML tag
- `04-incident-note.txt` — a post-deploy incident note
- `05-api-design-note.txt` — an API error-model design note

They deliberately repeat `retrieve`, `persist`, `invoke`, `propagate`, `reproduce`, `invalidate`, `fallback`, and `underlying` across different documents, alongside ordinary general English so the ranking has contrast.

On the current fixtures (5 documents, 276 tokens, 149 ranked terms) seven of those eight terms land in the top 20. `underlying` ranks lower because it is comparatively common in general English, which is the effect the baseline is supposed to capture.

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

The top of the real ranking is not yet a usable vocabulary list. The first ten `min_df = 3` rows are `unchange`, `xhigh`, `coderabbit`, `merg`, `requir`, `enforc`, `aliase`, `sha256`, `declar`, `unresolv`. Three separate effects are visible:

- Bots and automation: `coderabbit` (a review bot, 102 occurrences in 47 documents) and `18t03` are review-bot boilerplate, not human prose.
- Lemma artifacts: `unchange`, `merg`, `requir`, `enforc`, `declar`, `resolv`, `defin`, `repeate`, `reache` are suffix-rule lemmatizer damage. `unchange` is a further instance of the `unchanged` case already listed under known limitations.
- Non-English and token noise: CJK fragments (`また`, `初筛`), `xhigh` (a numeric-config token), `pukujan`, `aprè`.

Of the eight fixture target terms, none reaches the top 800 of either ranking; `fallback` is the best of them at 825th (`min_df = 3`). In the full ranking (`min_df = 1`, 21,872 terms) they rank: `fallback` 3,559; `reproduce` 15,658; `invoke` 16,670; `invalidate` 16,842; `persist` 16,863; `propagate` 16,907; `retrieve` 18,921; `underlying` 20,018. With `min_df = 3` (4,235 terms) they rank: `fallback` 825; `reproduce` 1,388; `invoke` 1,793; `invalidate` 1,870; `persist` 1,879; `propagate` 1,903; `retrieve` 2,942; `underlying` 3,461. They are present but far from the top: one hour of issue and pull-request prose is small and dominated by product-specific tokens and automation.

## Known limitations

- **Fixture corpus only, plus one bounded GH Archive hour.** The fixture ranking demonstrates the mechanism and says nothing about corpus-scale vocabulary. The GH Archive adapter exists and one hour has been run, but Stack Overflow and CodeSearchNet adapters are not implemented, and one hour of issue and pull-request prose is not a corpus.
- **Heuristic lemmatizer.** An irregular-verb map plus suffix rules, not a morphological analyzer or POS-aware lemmatizer. It has no prefix handling and known edge cases, e.g. plural silent-e words ending in `-ches` (`caches` → `cach`) and prefixed forms (`unchanged` → `unchange`). Part-of-speech tagging is not implemented, so homographs share one row.
- **wordfreq baseline.** General-English rates come from `wordfreq` per-token frequency, not a frequency-matched corpus. `wordfreq` combines several sources with its own weighting, and its coverage of technical vocabulary is uneven, which distorts scores for rare terms.
- **Single-token terms only.** No multi-word expressions or collocations.
- **Thin smoothing.** With a corpus this small, `alpha = 1` and `vocab_size` in the denominator dominate absolute scores; only the ordering is meaningful. One-off rare words can outrank repeated target terms.
- **Thin thresholds.** `--min-df` now provides a document-frequency floor, but there is no minimum term frequency, no boilerplate/bot down-ranking, and no stopword extension for product names, so automation text and rare one-off tokens still reach the top.

Reproducibility rules for runs of this pipeline are in [Pipeline conventions](pipeline-conventions.md).
