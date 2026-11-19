# Core 500 candidate — evaluation (v0)

**Status: candidate artifact, not a published dataset.** `data/core500-v0.jsonl` is a
measurement from one day of GH Archive prose. It has no glosses, no CEFR levels, no
collocations and no examples. It is not Core 500 in the Phase 2 sense and must not be
released as one. This document records what the candidate is, what it gets right, and
what is wrong with it.

## What was measured

| item | value |
| --- | --- |
| corpus | 24 hourly GH Archive files, 2026-11-18 00:00–23:59 UTC |
| documents | 17,390 |
| normalized tokens | 2,188,397 |
| ingest filters | `--exclude-bots --min-english-ratio 0.6 --dedup-text` (the English-ratio test ran at the old `1e-06` floor; see the caveat below) |
| lemma validation floor | `3e-07` (`ENGLISH_WORD_MIN_FREQUENCY`, lowered this round from `1e-06`) |
| ranking cut | `--min-df 10` → 6,215 rows |
| candidate | first 500 rows, ranks 1–500 |
| snapshot id | `gharchive-2026-11-18-day` |
| candidate file | `data/core500-v0.jsonl`, sha256 `5fbc775880f10979994f1397f7723734a33a72c52e46d96d0abb84410a0f2fe5` |
| audit file | `data/core500-v0-audit.jsonl` (term, rank, bucket for all 500) |

The score is the unchanged `se_specificity`: `ln(se_rate / max(wordfreq_en, 1e-8))`
with add-one smoothing. No scoring formula changed this round.

**Caveat on the corpus.** The 17,390-document corpus was built before the floor
change and was deliberately reused so that only lemmatization changes. Re-running the
ingest at `3e-07` would keep about 294 more documents (language-filter drops fall from
3,954 to 3,660) and would produce a slightly different corpus. That re-ingest is not
part of this candidate; the candidate is a re-ranking of the fixed day corpus.

### Why `min-df 10`

At this corpus size the `min_df = 3` top is junk-led: `c606` (681 occurrences in 4
documents, a device codename repeated in generated simulator-preview prose), `termux`
(192 / 3), `anyps5` (127 / 7) and `boykopovar` (124 / 7). Rows with hundreds of
occurrences in single-digit documents are repetition inside a handful of texts, not
vocabulary. `min_df = 10` removes that class; `min_df = 3` keeps 13,242 rows and
`min_df = 10` keeps 6,215. The cut is a document-frequency floor, not a frequency
floor: a term still needs `df >= 10`, and the shared lemma-validation floor is `3e-07`.

### Reproducibility

The candidate is extracted mechanically from the ranking and regenerates
byte-identically:

```bash
.venv/bin/python -m vocabops.pipeline \
  --input out/gharchive/documents-day.jsonl \
  --output out/gharchive-rank-day-floor-df10 \
  --snapshot-id gharchive-2026-11-18-day --min-df 10

.venv/bin/python scripts/extract_core500.py \
  --ranking out/gharchive-rank-day-floor-df10/ranking.json \
  --output data/core500-v0.jsonl
```

`scripts/extract_core500.py` copies the first 500 rows, assigning `rank` 1–500 and
renaming `se_specificity` to `score`. Two runs produced the same sha256. The ranking
itself reproduces byte-identically from the corpus.

## Coverage of the eight target terms

Only one of the eight target terms is inside the top 500.

| term | rank (df10, `3e-07`) | tf | df | rank at `1e-06` |
| --- | --- | --- | --- | --- |
| `fallback` | **188** | 1,192 | 688 | 199 |
| `reproduce` | 748 | 1,660 | 1,309 | 779 |
| `persist` | 1,208 | 480 | 327 | 1,247 |
| `invalidate` | 1,362 | 106 | 80 | 1,404 |
| `invoke` | 1,560 | 175 | 149 | 1,606 |
| `propagate` | 1,868 | 67 | 55 | 1,916 |
| `retrieve` | 3,408 | 58 | 48 | 3,486 |
| `underlying` | 4,312 | 76 | 71 | 4,405 |

Target-adjacent words that the floor change brings into the top 500: `retry` (#105),
`credential` (#315, the merged form of `credentials`, tf 950), `endpoint` (#435).
`encode` (#789) stays outside. `retry`, `credential` and `endpoint` are not part of
the original eight.

The honest reading: the candidate is not a list of the eight words the prototype was
designed around. `fallback` is the only one that reaches the cut, and it sits at 188.
The rest are too common in general English (`reproduce`, `persist`, `retrieve`) or too
rare in this corpus (`propagate`, `invoke`, `underlying`) to rank high under a
specificity measure.

## Composition audit

### Method and its limits

Every one of the 500 terms was assigned to exactly one bucket by reading the term
itself. **This classification is an LLM judgement call, not a reproducible
measurement.** Two annotators would disagree on boundary cases, especially compound
nouns such as `runbook` or `toolchain`. The per-term assignment is committed in
`data/core500-v0-audit.jsonl` so it can be checked, argued with and corrected row by
row. The rules used were:

- **(a) transferable SE vocabulary** — an ordinary English word or transparent
  derivation used in a software sense, which a learner would meet outside any single
  tool (`merge`, `retry`, `stale`, `malformed`, `dedupe`, `idempotent`).
- **(b) technical nouns / product / tool / project names** — a noun or name denoting a
  specific technology, artifact, format, protocol, product or project (`webhook`,
  `docstring`, `worktree`, `dockerfile`, `vercel`, `pytest`).
- **(c) abbreviations and acronyms** — `yml`, `sbom`, `lgtm`, `oidc`, `i18n`, `k8s`.
- **(d) fragments and artifacts** — non-words produced by tokenization or
  lemmatization, codenames, version shards, numeric/CSS/command fragments, non-English
  strings (`alway`, `spe` is outside the 500, `18t03`, `44px`, `अञ`).
- **(e) other / unclear** — a plausible token whose role cannot be determined from the
  term alone (`agy`, `cotal`, `omp`).

The boundary between (a) and (b) is the weakest part of the audit: a compound like
`runbook` is both a technical noun and transparent English. Such items were put in (b)
when they name an artifact and in (a) when they behave like ordinary vocabulary.

### Counts

| bucket | count | share |
| --- | --- | --- |
| (a) transferable SE vocabulary | 94 | 18.8% |
| (b) technical nouns / product / tool / project names | 228 | 45.6% |
| (c) abbreviations and acronyms | 86 | 17.2% |
| (d) fragments and artifacts | 82 | 16.4% |
| (e) other / unclear | 10 | 2.0% |

The dominant bucket is (b), and a large part of it is product and tool names
(`vercel`, `supabase`, `grafana`, `clickhouse`, `vitest`, `pytest`, `eslint`,
`dependabot`, `coderabbit`, `deepseek`, `chatgpt`). That is the core finding: at
`min_df 10` this corpus ranks a software *ecosystem* directory, not a vocabulary list.
Only 18.8% of the candidate is ordinary English an engineer would study as English.

### (a) examples (94 total)

`merge`, `retry`, `retryable`, `mergeable`, `rebase`, `rebased`, `rebases`, `refactor`,
`refactors`, `unmerged`, `dedupe`, `dedup`, `deduplicate`, `deduplicated`, `enqueue`,
`enqueued`, `debounce`, `debounced`, `idempotent`, `nullable`, `unhandled`,
`unauthenticated`, `untrusted`, `untracked`, `unpinned`, `unset`, `malformed`,
`deterministically`, `staleness`, `supersession`, `overwrites`, `recomputes`,
`revalidate`, `requeue`, `resync`, `restorable`, `runnable`, `checkable`,
`launchable`, `inspectable`, `maintainer`, `approver`, `orchestrator`, `agentic`,
`credential`, `endpoint`, `timestamp`, `byte`.

### (b) examples (228 total)

`worktree`, `webhook`, `webhooks`, `allowlist`, `allowlisted`, `docstring`,
`docstrings`, `lockfile`, `lockfiles`, `monorepo`, `namespace`, `dockerfile`,
`frontmatter`, `entrypoint`, `subagent`, `subagents`, `subcommand`, `runbook`,
`runbooks`, `toolchain`, `workspace`, `workflow`, `frontend`, `backend`, `runtime`,
`stdin`, `stdout`, `stderr`, `symlink`, `tarball`, `tokenizer`, `idempotency`,
`preflight`, `healthcheck`, `codeowners`, `postgres`, `sqlite`, `redis`, `kubectl`,
`vitest`, `pytest`, `eslint`, `vercel`, `supabase`.

### (c) examples (86 total)

`sha256`, `yml`, `yaml`, `sbom`, `toml`, `jsonl`, `jsonb`, `lgtm`, `i18n`, `a11y`,
`e2e`, `k8s`, `oidc`, `oauth`, `oauth2`, `jwt`, `rbac`, `csrf`, `ssrf`, `hmac`,
`base64`, `amd64`, `arm64`, `aarch64`, `x64`, `x86`, `wasm`, `mcp`, `sdk`, `llm`,
`cli`, `ci`, `py`, `env`, `src`, `px`.

The presence of `e2e` at rank 21 (`tf` 714, `df` 415) is notable: it is an acronym
that behaves like vocabulary, but it is not a word a learner reads as English. The
same is true of `lgtm` (#32), which is a review convention rather than vocabulary.

### (d) fragments and artifacts — full list (82 terms)

Timestamps and time shards (`ISO-8601` fragments split by the tokenizer, e.g.
`2026-11-18T02:07:00Z` → `18t02`, `07`, `00z`):
`18t13` (66), `18t06` (189), `18t03` (287), `18t07` (288), `18t02` (376),
`18t05` (377), `18t08` (378), `18t18` (439), `35z` (260), `12z` (284), `05z` (285),
`08z` (286), `52z` (289), `30z` (320), `40z` (342), `45z` (343), `31z` (379),
`56z` (381), `06z` (411), `20z` (412), `38z` (413), `44z` (414), `59z` (415),
`57z` (464), `16z` (492).

Version and model shards: `v0` (28), `qwen3` (48), `go1` (305), `v006` (331),
`ventura8` (391), `python3` (481).

Numeric, CSS and status fragments: `44px` (150), `390px` (151), `320px` (190),
`1080p` (244), `375px` (245), `1280px` (341), `500s` (380), `404s` (463).

Identifier and codename fragments: `if1` (40), `herdr` (51), `x402` (52),
`nemoclaw` (54), `brihas` (62), `if0` (64), `sarathy` (88), `stardelt` (95),
`krikri` (108), `xhigh` (119), `if2` (140), `fc5q` (143), `39xc` (145), `vjpf` (147),
`crtl` (167), `77bits` (177), `ac5` (212), `romn` (294), `ac7` (321), `ac6` (344),
`ac2` (361), `ac4` (364), `7a7e3f9f` (382), `arfan11` (417).

Stem fragment from the lowered floor: `alway` (258), the damaged lemma of `always`
(798 occurrences). `spe`, the damaged lemma of `speed`, is rank 699 and therefore just
outside the candidate; `unbound`, the damaged lemma of `unbounded`, is rank 975.

Non-English strings: `अञ` (216), `गन` (217), `सङ` (231), `aucune` (238), `aucun` (239),
`गह` (255), `fichier` (268), `fichiers` (269), `relecture` (310), `हळ` (312),
`aceptación` (322), `criterios` (346), `critères` (440), `中文说明` (444),
`compilatore` (465), `proporre` (467), `sottoponi` (468).

This is the actionable defect list. Most of it is one bug: **the tokenizer treats
`18T02` and `05Z` as words**, so ISO timestamps and clock times become vocabulary.
Fixing tokenization (split on digit/letter boundaries or drop tokens with digits) would
remove roughly 30 of the 82 fragment rows, including the highest-ranked ones. A second
bug is the absence of any guard against stem fragments (`alway`). A third is the
language filter letting French, Spanish, Italian and Devanagari tokens through in
mixed-language documents.

### (e) other / unclear (10 terms)

`agy` (120), `cotal` (130), `aiv` (142), `aidevops` (146), `rwelibs` (442), `dsh`
(447), `kib` (458), `finex` (459), `iln` (484), `omp` (489). Each looks like a
codename, an abbreviation or a truncation, but the term alone does not settle which.
They should be resolved against document context before any release.

## Boilerplate influence

The day ingest found 891 exact-duplicate texts at the `1e-06` floor. Re-running the
ingest without `--dedup-text` at the new floor gives 18,575 documents and 17,674
distinct texts, i.e. **901 replicated copies**, and confirms the round-6 findings:

- one templated design text appears **263 times** before dedup
  (`Design: namespaces with pack-defined kinds …`);
- `@codex review` appears **124 times**, `/trunk merge` 45 times, `/review` 17 times,
  `@coderabbitai full review` 16 times;
- short command comments and templated agent prose are the bulk of the duplication.

Exact-text dedup keeps one copy of each, so those texts contribute one document each
to the ranking. Traces remain visible in the top 500:

- `namespace` (#446) comes from the 263-copy template, which survives once;
- `lgtm` (#32, `df` 79) is a one-word review approval, not vocabulary;
- `coderabbit` (#15, 139 occurrences in 111 documents) and `dependabot` (#20) are
  tool names carried mostly by human-written text that mentions the bots, not by bot
  actors (the `[bot]` filter already removed those);
- agent and model chatter contributes `subagent` (#17), `deepseek` (#36), `chatgpt`
  (#19), `qwen` (#44), `grok` (#259).

The duplication is largely contained, but the selection is still shaped by
automation: an ecosystem directory and review conventions rank alongside vocabulary.
There is no down-ranking of boilerplate terms, only exact-text removal.

## Verdict against the Phase 2 exit condition

The exit condition is: *Core 500 can be consumed independently as an open dataset and
its ranking can be explained from reproducible measurements.*

**Met:**

- the ranking is reproducible from fixed inputs, byte-identically;
- every row carries `tf`, `df` and a documented score, and the extraction is a
  deterministic script;
- the candidate and corpus are openly documented, including filters and known defects;
- the audit makes the composition of all 500 rows checkable;
- thresholds are defined with evidence: lemma floor `3e-07` from the day-corpus
  measurement, `min_df 10` from the `df3` junk-led top.

**Not met:**

- it cannot be consumed as a vocabulary dataset: 45.6% is product/tool/technical
  nouns, 17.2% acronyms and 16.4% fragments, and there are no glosses, CEFR levels,
  collocations or examples (these are known Phase 2 gaps and explicitly out of scope
  for this round);
- coverage of the prototype's own target terms is 1 of 8;
- 16.4% of rows are artifacts that should not be in any release; the tokenizer fix is
  a prerequisite;
- the corpus is one day of GitHub issue/PR prose, not a language sample; nothing here
  measures general engineering English;
- the audit is a single LLM annotation with no second annotator and no agreement
  measure.

So the candidate is a useful diagnostic artifact and a step toward Core 500, not Core
500. It should stay in `data/` as `v0` until tokenization, boilerplate down-ranking
and the vocabulary/name split are fixed.
