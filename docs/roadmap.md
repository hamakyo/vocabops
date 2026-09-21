# Roadmap

VocabOps should validate the data model and corpus methodology before investing heavily in the learning UI.

## Phase 0 — Foundation

Goal: make the project understandable and reproducible.

- [x] define product vision
- [x] document architecture
- [x] define initial vocabulary schema
- [x] add a sample dataset
- [ ] choose corpus sources and licensing policy
- [ ] define reproducible data-pipeline conventions
- [ ] define release/versioning policy

Exit condition:

A contributor can understand what VocabOps is, how a term is represented, and how corpus-derived metrics are expected to work.

## Phase 1 — Core 500

Goal: publish the first useful software-engineering vocabulary dataset.

- [ ] assemble candidate vocabulary from software-engineering corpora
- [ ] remove boilerplate, code tokens, URLs, and obvious noise
- [ ] lemmatize and part-of-speech tag candidates
- [ ] compare against a general-English reference corpus
- [ ] define and validate `se_specificity`
- [ ] rank candidate vocabulary
- [ ] curate Japanese glosses
- [ ] attach CEFR where reliable
- [ ] extract common collocations
- [ ] publish Core 500 as JSON and CSV
- [ ] document methodology and known biases

Exit condition:

Core 500 can be consumed independently as an open dataset.

## Phase 2 — Learning MVP

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

## Phase 3 — Habit Layer

Goal: make consistent use visible and rewarding.

- [ ] daily activity heatmap
- [ ] streak tracking
- [ ] daily review goal
- [ ] words learned
- [ ] category mastery
- [ ] backlog visibility
- [ ] retention trend

The streak must not change FSRS scheduling. It is a behavioral layer, not a memory model.

## Phase 4 — LLM-native English

Goal: quantify language patterns introduced or amplified by modern LLM-assisted development.

- [ ] define comparable human and LLM software-engineering corpora
- [ ] collect model-family samples with reproducible prompts/tasks
- [ ] normalize corpus size and task distribution
- [ ] calculate `llm_lift`
- [ ] evaluate minimum-support and smoothing rules
- [ ] calculate model-specific lift where statistically defensible
- [ ] publish an LLM-native candidate deck
- [ ] validate whether commonly cited "Claudish" terms are actually overrepresented

Candidate terms may include words such as:

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

## Phase 5 — Essential 1500

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

## Phase 6 — Dataset ecosystem

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

- leagues
- avatars
- virtual currency
- social feeds
- elaborate gamification
- large amounts of hand-authored curriculum

The early product thesis is simple:

> Learn the English software engineers actually encounter, right before you forget it.
