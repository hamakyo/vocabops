# Release Policy

This document defines how VocabOps versions and publishes its vocabulary dataset. It complements [Data schema](data-schema.md) and [Pipeline conventions](pipeline-conventions.md).

## Two independent versions

The project has two version numbers that move independently:

- **Code version** — the pipeline and tooling (`pyproject.toml`, `vocabops.__version__`). Fixes and refactors bump this without changing the dataset.
- **Dataset version** — the published vocabulary artifact. This follows semantic versioning on its own track.

A dataset release therefore reads like `vocabulary 0.2.0 (built with pipeline 0.1.3)`. The dataset version is recorded in every record's `provenance.dataset_version`, and the pipeline version is recorded in the corpus manifest.

## Dataset semantic versioning

Given a dataset version `MAJOR.MINOR.PATCH`:

- **MAJOR** — breaking changes: removing or renaming a field, changing a field's meaning or type, changing ID semantics, or any change that requires consumers to update their code. A breaking schema change always bumps the dataset major version, per [Data schema](data-schema.md#versioning-principles).
- **MINOR** — additive, backward-compatible changes: new terms, new optional fields, new categories, additional sources, or recomputed metrics that keep the schema intact.
- **PATCH** — corrections that do not change schema or term inventory: fixed glosses, typo fixes, corrected provenance.

Metric values are expected to change between corpus snapshots. A snapshot refresh that only moves measurements is a minor release; it is never a patch if it changes which terms are present.

## Stable identifiers

- Term IDs follow the `<lemma>.<pos>` form defined in [Data schema](data-schema.md#id).
- An ID, once published, is never recycled and never reassigned to a different lemma or part of speech.
- If a term needs a new sense, append a semantic suffix; do not change the existing ID.
- Deprecated IDs are marked, not deleted, for at least one major version so learning history keeps resolving.

## What a release contains

Each dataset release is a directory `data/releases/<dataset-version>/` with:

- `vocabulary.json` — the full vocabulary records
- `vocabulary.csv` — the same records, flat, for inspection and spreadsheets
- `manifest.json` — snapshot ID, pipeline version, source families, general-English baseline, document and token counts
- `METHODOLOGY.md` — the ranking formula, smoothing, thresholds, source coverage, and known limitations for that release

A release does not contain raw third-party text. It contains derived vocabulary, aggregate metrics, and documentation only.

## Release checklist

1. Pipeline version and dataset version are set deliberately and differ only where intended.
2. `python -m pytest -q` passes in a clean `.venv`.
3. The pipeline is re-run from a fixed snapshot ID and the outputs match the committed state byte-for-byte.
4. `manifest.json` is committed with the release and matches the build that produced it.
5. Ranking rows contain no timestamps and are sorted deterministically.
6. Schema changes are checked against the dataset major-version rule; stable IDs were not renamed or recycled.
7. `METHODOLOGY.md` states the formula, thresholds, source coverage, and known limitations.
8. No raw third-party text, normalized third-party documents, or `out/` artifacts are committed.
9. JSON and CSV exports contain the same records in the same order.
10. Release notes state the dataset version, pipeline version, snapshot ID, and what changed since the previous release.
