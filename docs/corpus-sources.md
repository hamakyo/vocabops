# Corpus Sources

VocabOps v0.1 prioritizes existing, reproducible datasets before building custom large-scale crawlers.

The goal is to validate the central hypothesis first:

> Can corpus statistics surface software-engineering vocabulary that is more useful than a hand-written technical word list?

## v0.1 source stack

### Stack Overflow — human problem-solving language

Acquisition route (measured 2026-11-20):

- Hugging Face dataset `flax-sentence-embeddings/stackexchange_title_body_jsonl`
  (a Stack Exchange redistribution), file `stackoverflow.com-Posts.jsonl.gz`,
  downloaded with `huggingface_hub`;
- working stream `out/stackoverflow/raw/stackoverflow-full.jsonl.gz`:
  7,826,492,339 bytes, 18,562,443 lines, sha256
  `031b28eee4e4d7c6dd819df3dd40d3681cdcd85e85462711725654b134733c5d`;
- one JSON object per post, `texts[0]` the title and `texts[1:]` the body;
  `tags` are retained, HTML/markup is stripped, and the document is
  `title + "\n" + body`.

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
- preserve document boundaries (one document per post)
- retain tags as metadata
- compute term frequency and document frequency

### Sampling design: two stages, not one

A single pass of the committed adapter over all 18.56M records measured at
about **3 hours**, which repeatedly exceeded the run window. The sample was
therefore built in two stages:

1. **Stage 1 — uniform line sample.** A one-pass reservoir sample of
   **30,000 raw JSONL lines** from the full file, seed `20261119`
   (`~/so_stage1.py`). This reads the gzip stream once and stores only 30,000
   lines.
2. **Stage 2 — the committed adapter.** `python -m vocabops.ingest
   stackoverflow --input out/stackoverflow/raw-sample-30000.jsonl ...`, seed
   `20261118`, gates unchanged. Of the 30,000 lines, **29,852 passed all
   gates** (14 under the 100-character minimum, 134 below the 0.6 English
   ratio, 0 exact duplicates); the adapter then reservoir-sampled
   **17,390 documents** into
   `out/stackoverflow/documents-so-sample.jsonl`.

**Why this is the sample of record.** Stage 1 is a uniform sample of the full
line stream, and stage 2 is a uniform sample of the gate-passing records
inside it. The composition of two uniform samples is a uniform sample of the
gate-passing population: 29,852/30,000 (99.5%) of stage-1 lines pass, so the
17,390 stage-2 documents are a uniform sample of roughly 18.4M gate-passing
posts, not a convenience slice. The equivalence is exact for the record-local
gates (empty, length, language, alphabetic tokens). One caveat: the real
single-pass pipeline also runs exact-text dedup across the whole stream, while
stage 2 can only dedup inside its 30,000-line window. A duplicate whose first
copy fell outside the window would be kept here and dropped in a full run.
The sample contains **zero** exact duplicates, so there is no within-sample
evidence of that class; the residual bias is at most one copy per
cross-boundary duplicate and is not measurable from the sample.

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

Acquisition route (measured 2026-11-20):

- Hugging Face canonical dataset `code-search-net/code_search_net`, language
  `train` splits. The official CodeSearchNet S3 links returned **403**, so the
  HF mirror is the route actually used;
- six parquet files: go 211 MB, java 390 MB, javascript 159 MB, php 461 MB,
  python 522 MB, ruby 39 MB;
- **1,880,853** training records read. Of those, **919,216 (48.9%)** passed
  all gates; the rest were 865,105 under the 100-character minimum, 44,097
  below the 0.6 English ratio, 48,693 exact duplicates, 3,183 empty, 559 with
  no alphabetic tokens;
- a single-pass Algorithm-R reservoir sample (seed `20261118`) took
  **17,390** documents, written to
  `out/codesearchnet/documents-csn-sample.jsonl`;
- sample composition by language: java 4,992, php 4,424, python 4,221, go
  2,020, javascript 1,174, ruby 559. A second full run reproduced the sample
  byte-identically (sha256
  `f1c5e06de4a0c4fd3d65a6e99943ebcbb5bbdc2c4447ef1778356da94dfcc6fc`).

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
- language coverage is limited (six languages, no C#/C++), and the sample is
  Ruby-thin at 559 documents
- should not be treated as the sole representation of current software English
- **document IDs are not unique in this source.** The identity key is
  `repo/path#func_name`; the upstream train split contains 56 such keys with
  two or three different docstrings, i.e. 92 lines beyond the first with a
  repeated `doc_id`. The pipeline counts every line as a document, so the
  17,390-document count is unaffected, but a consumer that keys by `doc_id`
  would collapse those rows. Fixing the key would change the sample and is
  deferred.

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

## Combined corpus v1 (52,170 documents)

The first three-source corpus is a plain concatenation, in this order:
`out/gharchive/documents-day-v3.jsonl` +
`out/codesearchnet/documents-csn-sample.jsonl` +
`out/stackoverflow/documents-so-sample.jsonl` →
`out/combined/documents-combined-v1.jsonl` (52,170 lines, sha256
`6acbf476b9a7b6b562d693b1d6561dfd2b5331a2ff4fe9af069342132aa193e1`).

Each source contributes exactly 17,390 documents. That equal-document design
does **not** give equal weight: `se_specificity` uses token frequency, and the
sources differ in document length.

| source | documents | document share | normalized tokens | token share | text bytes | byte share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GH Archive (2026-11-18 day, v3) | 17,390 | 33.3% | 2,181,317 | 52.2% | 30,979,129 | 58.6% |
| CodeSearchNet sample | 17,390 | 33.3% | 521,906 | 12.5% | 5,586,210 | 10.6% |
| Stack Overflow sample | 17,390 | 33.3% | 1,476,830 | 35.3% | 16,341,419 | 30.9% |
| **total** | **52,170** | 100% | **4,180,053** | 100% | 52,906,758 | 100% |

Token counts use the project normalizer (lemmatized, stopwords removed) and
match the combined pipeline manifest. GH Archive is more than half the token
mass; CodeSearchNet is one docstring-sized eighth. This is the first measured
answer to "what does adding sources do to the ranking" — see
[Part 8 of the Core 500 evaluation](core500-evaluation.md#part-8--combined-corpus-and-source-bias).

Known identity caveat: 56 CodeSearchNet identifiers occur 2–3 times, so the
file has 52,170 lines but 52,078 unique `doc_id` values (92 repeated lines).
The pipeline treats every line as a document; nothing deduplicates on
`doc_id`, and the counts above are line counts.

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
