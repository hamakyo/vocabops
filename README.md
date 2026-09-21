# VocabOps

> Learn the English software engineers actually encounter, right before you forget it.

VocabOps is an open, corpus-driven English vocabulary project for software engineers.

It combines real-world software engineering corpora with spaced repetition and habit tracking so learners can study the vocabulary that actually appears in GitHub, documentation, Stack Overflow, RFCs, and LLM-assisted development.

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

## Corpus direction

The long-term dataset should compare multiple sources instead of treating software English as one homogeneous corpus.

```text
GitHub / Docs / Stack Overflow / RFCs
                  |
                  v
       Human-written SE corpus
                  |
                  +-------------------+
                                      |
                                      v
                              Vocabulary ranking
                                      ^
                                      |
                  +-------------------+
                  |
                  v
      GPT / Claude / Gemini / agents
           LLM-generated corpus
```

This makes it possible to distinguish:

- general English
- software-engineering English
- ecosystem-specific language
- LLM-native / agentic coding language

The last category includes expressions that modern coding assistants may overrepresent relative to human-written engineering text. VocabOps should measure that empirically instead of labeling words as "AI-ish" by intuition alone.

## MVP

The first useful version targets:

- Core 500 vocabulary
- a documented data schema
- frequency and domain-specificity fields
- CEFR and Japanese glosses
- collocations and examples
- FSRS-based reviews
- daily heatmap and streak
- a first LLM-native vocabulary slice

## Repository layout

```text
vocabops/
├── data/
│   └── sample.json
├── docs/
│   ├── architecture.md
│   ├── data-schema.md
│   └── roadmap.md
└── README.md
```

## Documentation

- [Architecture](docs/architecture.md)
- [Data schema](docs/data-schema.md)
- [Roadmap](docs/roadmap.md)

## Status

Early-stage. The current priority is to lock down the corpus methodology and vocabulary schema before building the learning UI.

## License

Code is licensed under the repository license. Dataset licensing and attribution rules will be documented separately as corpus sources are finalized.
