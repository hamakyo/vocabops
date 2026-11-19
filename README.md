# VocabOps

> Learn the English software engineers actually encounter, right before you forget it.

VocabOps is an open, corpus-driven English vocabulary project for software engineers.

It combines real-world software engineering corpora with spaced repetition and habit tracking so learners can study the vocabulary that actually appears in engineering discussions, documentation, and LLM-assisted development.

## Why VocabOps

Traditional vocabulary lists tend to emphasize general English or obvious technical nouns such as `database`, `server`, and `algorithm`.

VocabOps focuses on the words and phrases that often determine whether technical English feels effortless or slow:

- `retrieve`
- `persist`
- `invoke`
- `propagate`
- `reproduce`
- `invalidate`
- `deterministically`
- `recursively`
- `fallback`
- `underlying`

The goal is not just to know definitions, but to recognize and recall vocabulary in realistic engineering contexts.

## Product layers

VocabOps is designed as three independent but composable layers.

### 1. Open Vocabulary Dataset

Corpus-derived vocabulary with metadata such as:

- lemma and part of speech
- Japanese translation
- CEFR level
- software-engineering specificity
- source-specific frequency
- collocations and phrases
- realistic examples
- category tags
- LLM-native vocabulary metrics such as `llm_lift`

### 2. Learning Engine

A spaced-repetition layer centered on active recall.

Planned capabilities:

- FSRS-based scheduling
- New / Review queues
- Again / Hard / Good / Easy grading
- recognition, recall, cloze, and contextual questions
- retention estimates

### 3. Habit Layer

Tools that make short daily sessions sustainable.

Planned capabilities:

- daily learning heatmap
- streak tracking
- review counts
- learned-word counts
- category mastery
- retention trend

## Corpus v0.1

The first corpus deliberately reuses existing datasets before VocabOps builds custom large-scale collectors.

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

This lets the project test its central hypothesis quickly: whether corpus-derived ranking surfaces vocabulary that is more useful than a hand-written software glossary.

Direct GitHub repository cloning, official-doc crawling, and larger corpora come later when measurable coverage gaps justify them.

## LLM-native English

A later corpus layer compares human-written software-engineering text with controlled LLM output.

```text
Human SE corpus --------------------+
                                    |
                                    v
                              comparative stats
                                    ^
                                    |
Shared engineering tasks -----------+
     |       |       |
   Claude   GPT   Gemini
```

Terms such as `deterministically`, `recursively`, or `canonical` may be tracked as candidates, but VocabOps should only label them LLM-native when the corpus measurements support that conclusion.

## MVP

The first useful version targets:

- Human Software Corpus v0.1
- reproducible `se_specificity` ranking
- Core 500 vocabulary
- documented data schema and corpus manifests
- CEFR and Japanese glosses
- collocations and examples
- FSRS-based reviews
- daily heatmap and streak
- a first LLM-native vocabulary experiment

## Repository layout

```text
vocabops/
├── data/
│   ├── fixtures/
│   │   └── sample_corpus/    five original fixture documents
│   └── sample.json
├── docs/
│   ├── architecture.md
│   ├── corpus-sources.md
│   ├── data-schema.md
│   ├── pipeline-conventions.md
│   ├── prototype.md
│   ├── release-policy.md
│   └── roadmap.md
├── src/
│   └── vocabops/
│       ├── normalize.py
│       ├── pipeline.py
│       └── stats.py
├── tests/
├── pyproject.toml
└── README.md
```

## Documentation

- [Architecture](docs/architecture.md)
- [Corpus sources](docs/corpus-sources.md)
- [Data schema](docs/data-schema.md)
- [Pipeline conventions](docs/pipeline-conventions.md)
- [Release policy](docs/release-policy.md)
- [Phase 1 prototype](docs/prototype.md)
- [Core 500 evaluation](docs/core500-evaluation.md)
- [Ranking evaluation](docs/ranking-evaluation.md)
- [Roadmap](docs/roadmap.md)

## Status

Phase 1 is complete and Phase 2 (the Core 500 dataset) is under way. The pipeline runs end to end on three real corpora — a full day of GH Archive (17,390 documents), Stack Overflow and CodeSearchNet (17,390 sampled documents each) — with a dictionary- and corpus-validated lemmatizer. Because naive concatenation lets docstring conventions and platform APIs swamp the vocabulary, the production ranking fuses per-source rankings (Borda fusion, percentile variant); the method comparison is recorded in [Ranking evaluation](docs/ranking-evaluation.md) and the running measurements in [Core 500 evaluation](docs/core500-evaluation.md). The current vocabulary view (v3) is built on the fused ranking. Next: Japanese glosses, then publishing Core 500 as JSON/CSV with the methodology. 148 tests pass.

## License

Code is licensed under the repository license. Third-party corpus licensing and attribution remain source-specific. VocabOps public releases should primarily distribute derived vocabulary data and aggregate statistics rather than raw third-party text.
