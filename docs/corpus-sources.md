# Corpus Sources

VocabOps v0.1 prioritizes existing, reproducible datasets before building custom large-scale crawlers.

The goal is to validate the central hypothesis first:

> Can corpus statistics surface software-engineering vocabulary that is more useful than a hand-written technical word list?

## v0.1 source stack

### Stack Overflow — human problem-solving language

Primary source:

- Stack Exchange / Stack Overflow public data dump

Prototype option:

- SOTorrent-derived text blocks for faster experimentation

Role:

- questions
- answers
- comments
- debugging language
- error descriptions
- problem/solution vocabulary

Processing policy:

- remove or isolate code blocks
- strip HTML and boilerplate
- preserve document boundaries
- retain tags as metadata
- compute term frequency and document frequency

Raw post text is an analysis input, not a VocabOps release artifact.

### GH Archive — human engineering collaboration language

Primary source:

- GH Archive public GitHub event stream

Role:

- issue titles and bodies when present in event payloads
- issue comments
- pull-request text
- pull-request reviews
- commit messages
- contemporary collaboration vocabulary

Why use it first:

- avoids crawling GitHub repository-by-repository for the first prototype
- supports time-bounded snapshots
- can be queried before downloading a large raw corpus

Limitations:

- event data is not a complete representation of repository documentation
- edits and duplicate event representations require normalization
- source selection still needs repository/language/domain balancing

### CodeSearchNet — documentation/docstring English

Primary source:

- CodeSearchNet corpus

Role:

- docstrings
- API/documentation-style technical prose
- language-associated engineering vocabulary

Why use it:

- already structured
- separates documentation-like text from code
- useful as a documentation layer for the first corpus

Limitations:

- older than the other planned sources
- language coverage is limited
- should not be treated as the sole representation of current software English

### wordfreq — general-English baseline

Primary source:

- wordfreq English frequency data

Role:

- estimate general-language frequency
- support the first implementation of `se_specificity`

VocabOps should compare domain frequency against a general-English baseline rather than ranking words by raw software-corpus frequency alone.

The first prototype may use a simple smoothed log-frequency ratio. The final ranking formula should be validated separately.

## Human Software Corpus v0.1

The first prototype corpus is therefore:

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

This design intentionally postpones broad custom crawling.

## Sources postponed until after hypothesis validation

### Direct GitHub repository cloning

Use later for:

- README files
- `docs/`
- Markdown documentation
- ecosystem-specific snapshots
- up-to-date projects missing from CodeSearchNet

Prefer an allowlist of repositories and shallow clones.

### Official documentation websites

Prefer source repositories when available.

Only crawl websites when:

- no suitable source repository exists
- access is permitted
- crawl rate and caching are controlled
- licensing and redistribution constraints are understood

### Large code corpora

Possible later sources include larger public code datasets.

They are not required for Core 500 prototype generation because VocabOps targets natural-language engineering vocabulary rather than identifier frequency.

## LLM corpus strategy

Existing conversational datasets may be used for exploratory candidate discovery, but they should not define model-specific lift by themselves.

For defensible comparisons, VocabOps should generate a controlled benchmark corpus.

```text
shared task set
    |
    +-- Claude
    +-- GPT
    +-- Gemini
    |
    v
matched LLM engineering corpus
    |
    v
compare against matched human SE corpus
```

Control at least:

- task family
- programming language
- prompt content
- approximate response length
- sample count

Candidate terms such as `deterministically`, `recursively`, `canonical`, `orthogonal`, and `underlying` remain hypotheses until measured.

## Raw storage policy

Raw source text should not normally be committed to the VocabOps repository.

Recommended separation:

```text
Git repository
├── source manifests
├── pipeline code
├── aggregate statistics
├── released vocabulary
└── documentation

External/private working storage
├── raw snapshots
├── normalized documents
└── intermediate Parquet/JSONL files
```

For the prototype, local storage or CI artifacts are sufficient.

For durable snapshots, object storage can be added later.

## Snapshot manifests

Every corpus run should emit a manifest such as:

```json
{
  "snapshot_id": "human-se-v0.1-2026-09",
  "created_at": "2026-09-22",
  "pipeline_version": "0.1.0",
  "sources": [
    "stackoverflow",
    "gharchive",
    "codesearchnet"
  ],
  "general_baseline": "wordfreq",
  "documents": null,
  "tokens": null,
  "sha256": null
}
```

The manifest should be committed even when the raw corpus is not.

## Document identity

Normalized documents should retain a stable or reproducible hashed source identifier where practical.

This allows VocabOps to calculate:

- term frequency
- document frequency
- repository/source frequency
- source-family frequency

without publishing the underlying raw text.

## Public release boundary

VocabOps public releases should primarily contain:

- derived vocabulary records
- aggregate frequency metrics
- rankings
- collocations where redistribution is safe
- curated or safely generated examples
- corpus manifests
- methodology

Raw third-party source text remains outside the public dataset unless redistribution rights are explicit and compatible.
