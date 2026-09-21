# Data Schema

This document defines the initial vocabulary record used by VocabOps.

The schema is intentionally explicit about which fields are curated and which must be derived from corpus measurements.

## Goals

A vocabulary record should be:

- stable across dataset releases
- useful to both humans and applications
- traceable to corpus measurements
- expressive enough for software-engineering and LLM-native vocabulary
- compatible with spaced-repetition learning content

## Example

```json
{
  "id": "invalidate.v",
  "term": "invalidate",
  "lemma": "invalidate",
  "pos": "verb",
  "ja": {
    "gloss": "無効化する",
    "software_gloss": "キャッシュやトークンなどを無効化する"
  },
  "cefr": "C1",
  "categories": ["backend", "cache"],
  "forms": ["invalidates", "invalidated", "invalidating"],
  "collocations": [
    "invalidate the cache",
    "invalidate a token",
    "invalidate an entry"
  ],
  "examples": [
    {
      "text": "The cache is invalidated when the configuration changes.",
      "kind": "curated"
    }
  ],
  "metrics": {
    "frequency": {
      "github": null,
      "stackoverflow": null,
      "docs": null,
      "llm": null
    },
    "document_frequency": null,
    "se_specificity": null,
    "llm_lift": null,
    "model_lift": {
      "claude": null,
      "gpt": null,
      "gemini": null
    }
  },
  "learning": {
    "tier": "core",
    "priority": null
  },
  "provenance": {
    "dataset_version": "0.1.0-dev",
    "metric_snapshot": null,
    "sources": []
  }
}
```

## Required fields

### `id`

Stable identifier for references from learning history and external applications.

Recommended format:

```text
<lemma>.<pos>
```

Examples:

- `retrieve.v`
- `fallback.n`
- `deterministically.adv`

If two meanings need to be separated later, append a semantic suffix rather than changing an existing ID.

### `term`

Display form of the word or phrase.

### `lemma`

Canonical dictionary form.

### `pos`

Part of speech.

Initial values:

- `noun`
- `verb`
- `adjective`
- `adverb`
- `phrase`
- `other`

### `ja`

Japanese learning metadata.

- `gloss` — concise general translation
- `software_gloss` — meaning in software-engineering context when useful

### `categories`

Multi-valued taxonomy.

Initial candidates:

- `core`
- `frontend`
- `backend`
- `database`
- `git`
- `cloud`
- `security`
- `testing`
- `documentation`
- `architecture`
- `ai`
- `agentic`
- `llm-native-candidate`

The final `llm-native` designation should be derived from evidence rather than assigned manually.

## Corpus metrics

### `frequency`

Occurrence counts or normalized frequencies by source family.

Raw counts should not be compared across corpora of different sizes without normalization.

### `document_frequency`

Number or proportion of documents containing the term.

This helps distinguish broadly useful vocabulary from words repeated heavily in a small number of documents.

### `se_specificity`

Measures how disproportionately a term occurs in software-engineering text relative to a general-English reference corpus.

The exact formula is intentionally not fixed in v0.1. Candidate methods include:

- log frequency ratio
- log odds ratio with informative prior
- TF-IDF-like domain weighting

The selected method must be documented before publishing ranked releases.

### `llm_lift`

Relative prevalence in LLM-generated software-engineering text compared with a matched human-written software-engineering corpus.

Conceptually:

```text
normalized_frequency(term, LLM corpus)
--------------------------------------
normalized_frequency(term, human SE corpus)
```

Production calculation should include smoothing and minimum-support thresholds so rare terms do not produce misleading ratios.

### `model_lift`

Optional model-family-specific variants such as:

- `claude`
- `gpt`
- `gemini`

These fields should remain `null` until the corpora are sufficiently comparable.

## CEFR

`cefr` may be one of:

```text
A1 A2 B1 B2 C1 C2
```

or `null` when no reliable mapping is available.

CEFR describes general-language difficulty and should not be treated as software-domain importance.

## Collocations

Collocations capture chunks that are often more useful than isolated words.

Examples:

- `resolve a dependency`
- `propagate an error`
- `fall back to`
- `reproduce an issue`
- `invalidate the cache`

Where possible, collocations should ultimately be corpus-derived.

## Examples

Each example has:

- `text`
- `kind`

Initial `kind` values:

- `curated`
- `synthetic`
- `corpus`

Corpus examples require provenance and licensing review before redistribution.

## Learning metadata

### `tier`

Initial values:

- `core` — Core 500
- `essential` — Essential 1500
- `full` — long tail

### `priority`

Optional ranking score for introducing cards.

This should eventually combine usefulness, frequency, specificity, and learner difficulty rather than simply mirroring raw frequency.

## Provenance

Every published record should make it possible to identify:

- dataset version
- metric snapshot
- contributing source families

Raw copyrighted corpus text does not need to be redistributed for VocabOps to publish derived vocabulary statistics.

## Versioning principles

- Stable IDs should not be recycled.
- Corpus-derived metrics are expected to change between snapshots.
- Breaking schema changes require a dataset major-version bump.
- Human edits and generated metrics should remain distinguishable.
