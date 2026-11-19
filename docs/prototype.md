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

## Known limitations

- **Fixture corpus only.** Five short documents written by us. The ranking demonstrates the mechanism; it says nothing yet about real corpus-scale vocabulary. Stack Overflow, GH Archive, and CodeSearchNet adapters are not implemented.
- **Heuristic lemmatizer.** An irregular-verb map plus suffix rules, not a morphological analyzer or POS-aware lemmatizer. It has no prefix handling and known edge cases, e.g. plural silent-e words ending in `-ches` (`caches` → `cach`) and prefixed forms (`unchanged` → `unchange`). Part-of-speech tagging is not implemented, so homographs share one row.
- **wordfreq baseline.** General-English rates come from `wordfreq` per-token frequency, not a frequency-matched corpus. `wordfreq` combines several sources with its own weighting, and its coverage of technical vocabulary is uneven, which distorts scores for rare terms.
- **Single-token terms only.** No multi-word expressions or collocations.
- **Thin smoothing.** With a corpus this small, `alpha = 1` and `vocab_size` in the denominator dominate absolute scores; only the ordering is meaningful. One-off rare words can outrank repeated target terms.
- **No thresholds.** Every term is ranked, including rare noise and obvious technical nouns. Minimum frequency/document-frequency filtering is Phase 2 work.

Reproducibility rules for runs of this pipeline are in [Pipeline conventions](pipeline-conventions.md).
