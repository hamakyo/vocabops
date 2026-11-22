# Notebooks

Thin, reproducible runner notebooks for running heavy VocabOps stages on Google Colab.

## Guardrails

- **No pipeline logic in notebooks:** notebooks only install `vocabops` and invoke committed CLI entrypoints under `src/vocabops/`.
- **Externalize raw data and outputs:** mount Google Drive or use `/content/work` for raw third-party corpora and `out/` artifacts. Never commit third-party text or local `out/` outputs.
- **Deterministic runs:** always pass an explicit `--snapshot-id` and record model/package provenance in `manifest.json`.

## Available notebooks

| Notebook | Stage | CLI invoked | Colab |
| --- | --- | --- | --- |
| [`colab_pos_collocations.ipynb`](colab_pos_collocations.ipynb) | GPU POS-aware lemmatization & dependency-based collocation extraction | `python -m vocabops.enrich` | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/hamakyo/vocabops/blob/main/notebooks/colab_pos_collocations.ipynb) |
| [`colab_draft_curation.ipynb`](colab_draft_curation.ipynb) | GPU open-model Japanese gloss, example & cloze draft curation | `python -m vocabops.draft_curation` | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/hamakyo/vocabops/blob/main/notebooks/colab_draft_curation.ipynb) |
