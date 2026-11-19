# Pipeline Conventions

This document defines how VocabOps data pipelines are set up, laid out, and reproduced. It applies to the Phase 1 prototype and to later corpus builds.

## Environment

- Python 3.11 or newer.
- One virtual environment per checkout, created at `.venv/` (gitignored).
- Dependencies are declared in `pyproject.toml`; there are no ad-hoc installs.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Runtime dependencies belong in `[project.dependencies]`; test and tooling dependencies belong in the `dev` extra. Every command in the documentation assumes the `.venv` interpreter.

## Deterministic runs

A pipeline run must be reproducible byte-for-byte from the same inputs and the same pipeline version.

- **Fixed snapshot IDs.** Every run names its corpus snapshot explicitly (`--snapshot-id`), never from the clock or the host. The ID is recorded in the manifest.
- **Sorted output.** Input files are processed in sorted path order and ranking rows are sorted by score descending, then term ascending. No ranking depends on filesystem iteration order or on hash-map order.
- **No timestamps in ranking rows.** Ranking files contain measurements only. If a manifest carries a `created_at` field, that is the only place a timestamp may appear. The Phase 1 prototype omits timestamps from all generated files so repeated runs are byte-identical; a release manifest may add `created_at` without affecting ranking data.
- **Stable document IDs.** A document ID is `sha256(source_family + "/" + relative_path)` as a hex digest. It does not depend on content, so the same source document keeps the same ID across re-runs and the ID reveals no raw text. A source adapter that has no file path uses the source's own stable identifier in place of the path: the GH Archive adapter hashes `gharchive/<event id>`.
- **Pinned instrumentation.** `wordfreq` is pinned by a minimum version in `pyproject.toml`; a baseline change is a dataset change and must be recorded in the manifest or release notes.

Determinism is verifiable: run the pipeline twice into two output directories and compare files. `tests/test_pipeline.py` does this for the prototype.

## Directory layout

```text
<working storage, not committed>
raw/<source>/<snapshot-id>/          untouched source extracts
normalized/<snapshot-id>/            cleaned documents (JSONL)
work/<snapshot-id>/                  intermediate Parquet / JSONL

<git repository>
data/fixtures/<name>/                small fixtures we wrote ourselves
corpus/manifests/<snapshot-id>.json  committed snapshot manifests
data/releases/<dataset-version>/      released vocabulary (JSON/CSV)
out/                                 local pipeline output (gitignored)
```

`out/` is always gitignored. Raw and normalized corpora live outside the repository or in gitignored working storage. The repository carries code, fixtures, manifests, aggregate statistics, released vocabulary, and methodology only.

## What may be committed

Committed:

- pipeline code and tests
- fixture corpora written by the VocabOps authors
- snapshot manifests
- aggregate statistics and rankings derived from measurements
- released vocabulary records and methodology notes

Not committed:

- raw third-party corpus text (Stack Overflow, GH Archive, CodeSearchNet, or any other external source)
- normalized documents derived from third-party text
- large intermediate files
- any local `out/` directory

This boundary matches [Corpus sources](corpus-sources.md#raw-storage-policy) and the release policy in [Release policy](release-policy.md).

## Reproducing a run

Every run is one command with explicit inputs, a fixed snapshot ID, and a known output directory.

Prototype example:

```bash
.venv/bin/python -m vocabops.pipeline \
  --input data/fixtures/sample_corpus \
  --output out/human-se-v0.1-proto \
  --snapshot-id human-se-v0.1-proto
```

Inputs:

- `data/fixtures/sample_corpus/*.txt` — one document per file, all `source_family = "fixture"`

Outputs:

- `out/human-se-v0.1-proto/ranking.json`
- `out/human-se-v0.1-proto/ranking.csv`
- `out/human-se-v0.1-proto/manifest.json`

A run is considered reproduced when the outputs match an earlier run byte-for-byte and the manifest matches the committed snapshot manifest.

For later source adapters, the same shape applies: a fixed snapshot ID selects an immutable input set, one command produces normalized documents, statistics, and a manifest, and the manifest is committed even though the raw corpus is not.
