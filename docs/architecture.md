# Architecture

VocabOps is split into three layers so the dataset can remain useful even without the learning application.

## 1. Data pipeline

```text
Raw sources
  |
  +-- GitHub
  +-- Stack Overflow
  +-- Official documentation
  +-- RFCs / specifications
  +-- LLM / coding-agent outputs
  |
  v
Normalization
  |
  +-- strip code where appropriate
  +-- sentence segmentation
  +-- tokenization
  +-- lemmatization
  +-- part-of-speech tagging
  +-- source metadata
  |
  v
Corpus statistics
  |
  +-- raw frequency
  +-- document frequency
  +-- source frequency
  +-- software-engineering specificity
  +-- LLM lift
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

## 2. Dataset layer

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

## 3. Learning engine

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

## 4. Habit layer

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

## 5. Human vs LLM corpora

A distinguishing VocabOps feature is explicit comparison between human-written software engineering text and LLM-generated engineering text.

```text
Human SE corpus --------------------+
                                    |
                                    v
                              comparative stats
                                    ^
                                    |
LLM / coding-agent corpus ----------+
```

Metrics such as `llm_lift` should describe how much more frequently a term appears in an LLM corpus than in a comparable human corpus.

Model-specific metrics such as `claude_lift`, `gpt_lift`, or `gemini_lift` may be added when the underlying samples are large and comparable enough.

These values must be empirical. Terms should not be tagged as "Claudish" or "LLM-native" solely from anecdotal impressions.

## 6. Suggested implementation boundary

A likely repository structure is:

```text
apps/
  web/                 learning application

packages/
  dataset/             schema + generated vocabulary package
  fsrs/                review scheduling integration
  corpus/              shared corpus processing utilities

pipelines/
  github/
  stackoverflow/
  docs/
  llm/

data/
  sample.json
  releases/

docs/
  architecture.md
  data-schema.md
  roadmap.md
```

The MVP does not need this full structure immediately. The first milestone is to validate the schema and corpus methodology with a small reproducible sample.
