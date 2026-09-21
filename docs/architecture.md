# Architecture

VocabOps is split into three product layers and one corpus pipeline so the dataset can remain useful independently of the learning application.

## 1. Corpus strategy

VocabOps v0.1 uses existing public datasets first instead of starting with a broad custom crawler.

The initial human software-engineering corpus is:

```text
Stack Overflow dump / SOTorrent
             +
         GH Archive
             +
       CodeSearchNet
             |
             v
 Human Software Engineering Corpus
             |
             +-------------------+
                                 |
                                 v
                          se_specificity
                                 ^
                                 |
                             wordfreq
                      General-English baseline
```

This combination gives the prototype three different kinds of engineering prose:

- problem-solving and debugging language from Stack Overflow
- collaboration language from GitHub events
- documentation/docstring language from CodeSearchNet

Direct repository cloning, official-doc crawling, and larger code corpora are intentionally postponed until the Core 500 hypothesis has been validated.

See [Corpus sources](corpus-sources.md) for source-specific policy.

## 2. Data pipeline

```text
Existing source datasets
  |
  +-- Stack Overflow dump / SOTorrent
  +-- GH Archive
  +-- CodeSearchNet
  +-- wordfreq baseline
  |
  v
Source adapters
  |
  v
Normalized documents
  |
  +-- remove/segment code where appropriate
  +-- strip markup and boilerplate
  +-- sentence segmentation
  +-- tokenization
  +-- lemmatization
  +-- part-of-speech tagging
  +-- hashed/reproducible document identity
  +-- source metadata
  |
  v
Corpus statistics
  |
  +-- term frequency
  +-- document frequency
  +-- source-family frequency
  +-- repository frequency where available
  +-- software-engineering specificity
  |
  v
Vocabulary enrichment
  |
  +-- Japanese gloss
  +-- CEFR
  +-- categories
  +-- collocations
  +-- examples
  |
  v
Versioned dataset
```

The pipeline should be reproducible. Derived values should be generated from source snapshots and scripts rather than edited manually wherever practical.

## 3. Raw-data boundary

Raw source text is an analysis input, not the main public artifact.

```text
External/private working storage
├── raw source snapshots
├── normalized documents
└── intermediate Parquet / JSONL

Git repository
├── source manifests
├── pipeline code
├── aggregate statistics
├── released vocabulary
└── methodology
```

The prototype may use local storage or CI artifacts. Durable object storage can be added after the corpus design is proven.

Every corpus build should emit a snapshot manifest containing at least:

- snapshot ID
- creation date
- pipeline version
- source families
- general-English baseline
- document/token counts
- checksum where applicable

## 4. Dataset layer

The dataset is the core project artifact.

It should support at least:

- JSON for applications
- CSV for inspection and analysis
- optional SQLite / Parquet exports for larger releases
- stable term identifiers
- dataset versioning
- provenance for generated metrics

Vocabulary tiers are planned as:

- **Core 500** — highest-value vocabulary for everyday engineering English
- **Essential 1500** — broader reading coverage
- **Full** — long-tail corpus vocabulary and phrases

A term can belong to multiple semantic categories such as `backend`, `git`, `cloud`, `ai`, `agentic`, or `llm-native`.

## 5. Ranking

Raw software-corpus frequency is not enough.

A first prototype score should compare software frequency against a general-English baseline:

```text
software-engineering frequency
            vs
    general-English frequency
            |
            v
       se_specificity
```

Candidate implementations include a smoothed log-frequency ratio or log-odds method.

Ranking should eventually combine:

- frequency
- document frequency
- software-engineering specificity
- source diversity
- learning usefulness
- learner difficulty

The ranking method must be documented and evaluated before Core 500 is treated as stable.

## 6. Learning engine

The learning engine consumes the dataset but does not own it.

Primary responsibilities:

- FSRS scheduling
- per-user review state
- New / Review queues
- Again / Hard / Good / Easy grades
- recognition cards
- active recall cards
- cloze cards
- contextual usage cards
- retention estimates

The learning state should reference stable dataset term IDs so dataset releases can evolve independently.

## 7. Habit layer

The habit layer turns the review engine into a daily workflow.

Planned signals:

- reviews completed per day
- new terms learned
- streak
- calendar heatmap
- estimated retention
- category mastery
- review backlog

The streak should motivate consistency without overriding the scheduler. FSRS decides *what should be reviewed*; the habit layer encourages the learner to *show up and do it*.

## 8. Human vs LLM corpora

A distinguishing VocabOps feature is explicit comparison between human-written software engineering text and LLM-generated engineering text.

Exploratory public chat datasets may help discover candidates, but model-specific lift should ultimately use a controlled corpus.

```text
matched human SE corpus -------------+
                                     |
                                     v
                               comparative stats
                                     ^
                                     |
controlled shared tasks -------------+
    |        |        |
 Claude     GPT     Gemini
```

Metrics such as `llm_lift` should describe how much more frequently a term appears in an LLM corpus than in a comparable human corpus.

Model-specific metrics such as `claude_lift`, `gpt_lift`, or `gemini_lift` should only be published when task mix, corpus size, and sampling are sufficiently comparable.

Terms should not be tagged as "Claudish" or "LLM-native" solely from anecdotal impressions.

## 9. Suggested implementation boundary

```text
apps/
  web/                     learning application

packages/
  dataset/                 schema + generated vocabulary package
  fsrs/                    review scheduling integration
  corpus/                  shared normalization/statistics utilities

pipelines/
  stackoverflow/
  gharchive/
  codesearchnet/
  llm/

corpus/
  manifests/

data/
  sample.json
  releases/

docs/
  architecture.md
  corpus-sources.md
  data-schema.md
  roadmap.md
```

The first engineering milestone is not a crawler. It is an end-to-end prototype that produces a candidate vocabulary ranking from the existing source stack.
