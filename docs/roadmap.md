# Roadmap

VocabOps should validate the corpus hypothesis and ranking methodology before investing heavily in custom collection infrastructure or the learning UI.

## Phase 0 — Foundation

Goal: make the project understandable and reproducible.

- [x] define product vision
- [x] document architecture
- [x] define initial vocabulary schema
- [x] add a sample dataset
- [x] choose the initial corpus source strategy
- [x] document the public/raw-data boundary
- [ ] define reproducible data-pipeline conventions
- [ ] define release/versioning policy

Initial corpus stack:

- Stack Overflow dump / SOTorrent
- GH Archive
- CodeSearchNet
- wordfreq as the general-English baseline

Exit condition:

A contributor can understand what VocabOps is, how a term is represented, where the first corpus comes from, and how corpus-derived metrics are expected to work.

## Phase 1 — Human Software Corpus v0.1

Goal: generate a reproducible software-engineering vocabulary ranking without building a broad custom crawler.

### Source adapters

- [ ] ingest a small Stack Overflow / SOTorrent sample
- [ ] ingest a bounded GH Archive sample
- [ ] ingest CodeSearchNet docstrings
- [ ] integrate wordfreq baseline frequencies

### Normalization

- [ ] remove or segment code blocks
- [ ] strip markup, URLs, and boilerplate
- [ ] preserve document boundaries
- [ ] assign stable/reproducible document IDs
- [ ] tokenize
- [ ] lemmatize
- [ ] part-of-speech tag
- [ ] preserve source-family metadata

### Statistics

- [ ] compute term frequency
- [ ] compute document frequency
- [ ] compute source-family frequency
- [ ] compute repository frequency where available
- [ ] implement a first `se_specificity` score
- [ ] emit corpus snapshot manifests

Exit condition:

One command or workflow can reproduce a candidate vocabulary ranking from fixed source snapshots.

## Phase 2 — Core 500

Goal: turn the corpus ranking into the first useful software-engineering vocabulary dataset.

- [ ] evaluate candidate ranking methods
- [ ] define minimum frequency/document-frequency thresholds
- [ ] detect and down-rank boilerplate and obvious low-value terms
- [ ] review high-ranking technical nouns separately from transferable English vocabulary
- [ ] curate Japanese glosses
- [ ] attach CEFR where reliable
- [ ] extract common collocations
- [ ] add curated or safely generated examples
- [ ] publish Core 500 as JSON and CSV
- [ ] document methodology, source coverage, and known biases

Exit condition:

Core 500 can be consumed independently as an open dataset and its ranking can be explained from reproducible measurements.

## Phase 3 — Learning MVP

Goal: make Core 500 learnable in short daily sessions.

- [ ] build a minimal web application
- [ ] integrate FSRS
- [ ] support New / Review queues
- [ ] support Again / Hard / Good / Easy grading
- [ ] add recognition cards
- [ ] add active-recall cards
- [ ] add cloze cards
- [ ] persist per-user review state
- [ ] show estimated retention

Exit condition:

A learner can complete daily reviews and have future reviews scheduled automatically.

## Phase 4 — Habit Layer

Goal: make consistent use visible and rewarding.

- [ ] daily activity heatmap
- [ ] streak tracking
- [ ] daily review goal
- [ ] words learned
- [ ] category mastery
- [ ] backlog visibility
- [ ] retention trend

The streak must not change FSRS scheduling. It is a behavioral layer, not a memory model.

## Phase 5 — LLM-native English

Goal: quantify language patterns introduced or amplified by modern LLM-assisted development.

### Exploration

- [ ] evaluate existing public conversational datasets for candidate discovery
- [ ] identify coding-related subsets where licensing permits analysis
- [ ] build an initial candidate list

### Controlled comparison

- [ ] define a shared software-engineering task benchmark
- [ ] collect matched model-family samples
- [ ] control task mix, programming language, response length, and sample count
- [ ] define a matched human comparison corpus
- [ ] calculate `llm_lift`
- [ ] evaluate minimum-support and smoothing rules
- [ ] calculate model-specific lift where statistically defensible
- [ ] publish an LLM-native candidate deck
- [ ] validate whether commonly cited "Claudish" terms are actually overrepresented

Candidate terms may include:

- deterministically
- recursively
- canonical
- orthogonal
- invariant
- bounded
- composable
- semantically
- implicitly
- explicitly
- underlying

These are hypotheses, not labels. Inclusion in the final LLM-native set requires corpus evidence.

## Phase 6 — Corpus Expansion

Goal: improve freshness and ecosystem coverage after the Core 500 hypothesis is validated.

Potential additions:

- [ ] allowlisted GitHub repository clones for README and `docs/`
- [ ] official documentation source repositories
- [ ] selected official documentation websites where permitted
- [ ] ecosystem-specific snapshots
- [ ] larger public code/documentation corpora where they add measurable value

This phase should be driven by observed coverage gaps, not by a desire to maximize corpus size.

## Phase 7 — Essential 1500

Goal: broaden reading coverage without sacrificing relevance.

- [ ] expand beyond Core 500
- [ ] improve multi-word expression extraction
- [ ] add source/ecosystem categories
- [ ] add learning-priority model
- [ ] publish Essential 1500
- [ ] provide import/export formats for external learning tools

Potential categories:

- Git / GitHub
- frontend
- backend
- databases
- cloud / infrastructure
- security
- testing
- architecture
- documentation
- AI / LLM
- agentic coding

## Phase 8 — Dataset ecosystem

Goal: make VocabOps useful beyond the first-party app.

Possible outputs:

- npm package
- Python package
- Hugging Face dataset
- SQLite / Parquet releases
- Anki export
- API
- periodic corpus snapshots

## Non-goals for early releases

Until the dataset and review loop are proven, avoid spending significant effort on:

- broad web crawling
- mirroring large raw corpora
- exhaustive GitHub repository collection
- leagues
- avatars
- virtual currency
- social feeds
- elaborate gamification
- large amounts of hand-authored curriculum

The early product thesis is simple:

> Learn the English software engineers actually encounter, right before you forget it.
