# VocabOps Core 500 — Methodology (0.1.0-draft)

## Overview

- **Dataset version:** `0.1.0-draft`
- **Pipeline version:** `0.1.0`
- **Snapshot ID:** `core500-draft-v1`
- **Metric snapshot:** `combined-3source-enrich-v1`
- **Records:** 581 `(lemma, pos)` entries covering 498 unique lemmas
- **Curation status breakdown:** {"draft": 581}
- **Zero-warning records (with cloze):** 549 / 581

## Corpus & Ranking

- **Source families:** `codesearchnet`, `gharchive`, `stackoverflow`
- **Human Software Corpus v0.1:** 52,170 documents (17,390 GH Archive + 17,390 Stack Overflow two-stage sample + 17,390 CodeSearchNet docstrings).
- **General-English baseline:** `wordfreq` (shared lemma floor `3e-07`, ranking cut `--min-df 10`).
- **Ranking method:** Percentile Borda fusion with equalized absence penalty across source families (`vocabops.fusion`), split into vocabulary vs. technical views (`data/core500-vocab-v3.jsonl`).

## POS & Collocation Enrichment

- Generated with `python -m vocabops.enrich` using spaCy `en_core_web_trf` (`3.8.0`) on Colab GPU.
- Selects each lemma's primary part of speech plus secondary POS tags with `pos_share >= 0.25`.
- Extracts dependency-based collocations (`verb_obj`, `verb_prep_obj`, `amod_noun`, `noun_compound`, `verb_adv`) and observed inflected `forms`.

## Draft Curation & Human Review

- Initial Japanese glosses (`ja.gloss`), software-engineering glosses (`ja.software_gloss`), CEFR estimates, allowlisted categories, and synthetic EN/JA examples were generated via `python -m vocabops.draft_curation` using `Qwen/Qwen2.5-7B-Instruct` with greedy decoding.
- Cloze cards (`cloze.prompt`, `cloze.answer`) are derived deterministically by masking the target lemma or one of its observed inflected forms.
- Human edits and approvals are applied deterministically via `python -m vocabops.curation apply-overrides`, preserving corpus telemetry and distinguishing `examples[].kind = "curated"` from `"synthetic"`.

## Known Limitations

- Records with `curation.status = "draft"` and `needs_human_review = true` have not yet been manually audited.
- `metrics.llm_lift` and `metrics.model_lift` remain `null` until a controlled Human vs. LLM benchmark corpus is measured (Phase 5). Neither `llm-native` nor `llm-native-candidate` is assigned automatically.
- Remaining validation warnings: `{"example_missing_target_term": 32}` (primarily shorthand abbreviations whose synthetic examples expand to full English words).
