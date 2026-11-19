# Core 500 candidate — evaluation

Two candidates are recorded here. **v0** (part 1) is the first measurement and is
kept intact as history. **v0.1** (part 2) applies the tokenizer fixes and rebuilds
the corpus at the current English floor. Neither is a published dataset.

# Part 1 — v0

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

# Part 2 — v0.1

**Status: candidate artifact, not a published dataset.** `data/core500-v0.1.jsonl`
applies the tokenizer fixes from `662c9fc` and rebuilds the corpus with the shared
`3e-07` English floor. It is a second measurement of the same one-day GH Archive
slice, not a new corpus and not Core 500. Everything in Part 1 still describes v0 and
is kept unchanged.

## What was measured

| item | value |
| --- | --- |
| corpus | 24 hourly GH Archive files, 2026-11-18 00:00–23:59 UTC |
| documents | 17,674 |
| normalized tokens | 2,225,982 |
| ingest filters | `--exclude-bots --min-english-ratio 0.6 --dedup-text --max-docs 100000` |
| lemma validation floor | `3e-07` (`ENGLISH_WORD_MIN_FREQUENCY`) |
| ranking cut | `--min-df 10` → 6,474 rows |
| candidate | first 500 rows, ranks 1–500 (cut score 6.197) |
| snapshot id | `gharchive-2026-11-18-day-v2` |
| corpus file | `out/gharchive/documents-day-v2.jsonl`, sha256 `998195329e64b08b7a7d2b3c0d4c55982159ad90af76fcda2fac5e9a9df6d6e6` |
| candidate file | `data/core500-v0.1.jsonl`, sha256 `b6190f38dc44efded3128a83911e425ef9beaf614bd0b1dbd20a9f6afe454fdc` |
| audit file | `data/core500-v0.1-audit.jsonl`, sha256 `0d62a652214258fe4b8a0c4411dd531f9e6989f22f41df5938b98c5da08e8871` |

Two things changed against v0: the tokenizer (three rules, below) and the corpus, which
is no longer the `1e-06` corpus re-ranked — it was re-ingested at the current `3e-07`
floor. Unlike v0, this candidate therefore carries both tokenizer and floor effects.

### Ingest counters, v0 → v0.1

| counter | v0 | v0.1 | delta |
| --- | --- | --- | --- |
| input files | 24 | 24 | 0 |
| events seen | 121,837 | 121,837 | 0 |
| documents written | 17,390 | 17,674 | +284 |
| skipped: no body | 84,710 | 84,710 | 0 |
| skipped: bot actor | 14,874 | 14,874 | 0 |
| skipped: below english ratio | 3,954 | 3,660 | −294 |
| skipped: no alphabetic tokens | 18 | 18 | 0 |
| skipped: duplicate text | 891 | 901 | +10 |

The totals close: 121,837 − 84,710 − 14,874 − 3,660 − 18 − 901 = 17,674. The language
drop is exactly the 3,660 the floor analysis predicted. Of the 294 documents the lower
floor admits, 10 are exact duplicates of an earlier text and are removed by
`--dedup-text`, leaving 284 new documents and 37,585 more tokens (+1.7%). A second
ingest produced a byte-identical file; the pipeline and the extraction also reproduce
byte-identically (verified with `cmp`).

### Tokenizer rules applied

Three rules in `tokenize()` (`src/vocabops/normalize.py`):

1. ISO-8601 datetimes (`2026-11-18T02:07:00Z`, including fractional seconds and
   offsets) and bare ISO dates are stripped from the text before `\w+` can split them
   into `18t02` / `07` / `00z` shards.
2. Tokens matching `^\d+(px|pt|rem|em)$` are dropped (CSS measurements).
3. Digit-first tokens with a digit after at least one letter are dropped
   (`^\d.*[A-Za-z].*\d$`: `18t02`, `7a7e3f9f`). Letter-first digit tokens are never
   dropped, so `sha256` (#2), `arm64` (#4), `e2e` (#19), `i18n` (#36), `aarch64`
   (#42) and `x64` (#135) survive unchanged.

Effect on the fragment bucket: 31 of v0's 82 fragment rows are gone from the ranking
entirely — 25 timestamp shards (`18t13`, `35z`, `05z`, …), 5 CSS measurements
(`44px`, `390px`, `320px`, `375px`, `1280px`) and the hex string `7a7e3f9f`. A further
5 rows (`404s`, `compilatore`, `proporre`, `python3`, `sottoponi`) are still ranked but
fell below the 500 cut. No timestamp or CSS-measurement row remains in the top 500.

Residuals, stated plainly: `v0` (#30), `1080p` (#265) and `500s` (#402) are letter-first
digit tokens that the rules deliberately keep; `v0` is the first shard of version
strings such as `v0.23.2` and `v0.0.139`, not a vocabulary item, and it is classified
as a fragment in the audit. One time shard also survives outside the candidate: `00z`
(#1,990, tf 21, df 13), produced by forms such as `2026-11-18 ~10:00Z`, where a
separator between date and time stops the datetime pattern from matching. It is the
only timestamp shard left in the 6,474-row ranking.

## Coverage of the eight target terms

| term | v0 rank | v0.1 rank | tf | df |
| --- | --- | --- | --- | --- |
| `fallback` | 188 | **199** | 1,201 | 695 |
| `reproduce` | 748 | 832 | 1,664 | 1,313 |
| `persist` | 1,208 | 1,363 | 480 | 327 |
| `invalidate` | 1,362 | 1,522 | 106 | 80 |
| `invoke` | 1,560 | 1,731 | 175 | 149 |
| `propagate` | 1,868 | 2,056 | 67 | 55 |
| `retrieve` | 3,408 | 3,652 | 58 | 48 |
| `underlying` | 4,312 | 4,560 | 76 | 71 |

Every target still sits slightly lower than in v0 even though each gains a little raw
frequency: the extra 284 documents grow the `min_df 10` vocabulary from 6,215 to 6,474
rows, and the added rows are mostly non-English, which raises the competition without
adding English vocabulary. `fallback` remains the only target inside the 500 (at 199,
down from 188). The target-adjacent rows moved the same way: `retry` 105 → 110,
`credential` 315 → 341, `endpoint` 435 → 467; `encode` 789 → 885.

## Composition audit

### Counts

| bucket | v0 | v0.1 | delta |
| --- | --- | --- | --- |
| (a) transferable SE vocabulary | 94 (18.8%) | 85 (17.0%) | −9 |
| (b) technical nouns / product / tool / project names | 228 (45.6%) | 217 (43.4%) | −11 |
| (c) abbreviations and acronyms | 86 (17.2%) | 80 (16.0%) | −6 |
| (d) fragments and artifacts | 82 (16.4%) | 110 (22.0%) | +28 |
| (e) other / unclear | 10 (2.0%) | 8 (1.6%) | −2 |

433 terms are shared with v0, 67 are replaced, and **not one shared term changed
bucket** — every bucket delta is explained by rows entering and leaving the top 500.
The 67 replacements: 64 non-English rows entered (d), plus `fastify` and `unittest`
(b), `dtos` (c). Leaving: 9 (a) — `callee`, `checkable`, `deterministically`,
`launchable`, `merge`, `reimplement`, `restorable`, `runnable`, `timestamp` — 13 (b),
7 (c) and 36 (d), 31 of which the tokenizer removed outright.

### (a) and (b) notes

`merge` falling out of the top 500 (472 → 515) is a rank slide, not a frequency loss:
it has tf 6,149 and df 3,144, but is far too common in general English to score high.
The (a) and (b) text is otherwise unchanged; the same `worktree` / `webhook` /
`docstring` / `runbook` core leads the list, with `fastify` (#250) and `unittest`
(#453) the only new technical nouns. `openbot` (#37, from #46) and `deepseek` (#29,
from #36) rise on the reshuffle.

### (d) fragments and artifacts — full list (110 terms)

The count went **up**, not down. This is the honest headline of v0.1: the tokenizer
fix removed every timestamp and CSS shard, but the floor-driven re-ingest added 64
non-English rows, so the fragment share rose from 16.4% to 22.0%.

Non-English strings, 78 rows (2.8% of v0's 500 → 15.6% of v0.1's). Fourteen were
already in v0 — `aucun`, `aucune`, `fichiers`, `critères`, `criterios`, `fichier`,
`aceptación`, `relecture`, `अञ`, `गन`, `सङ`, `गह`, `हळ`, `中文说明` — and the other 64
are new: `écran` (69), `échec` (92), `usuario` (115), `décision` (128), `contenu`
(157), `servidor` (158), `revisión` (172), `preuve` (191), `défaut` (201), `règle`
(205), `contient` (209), `serveur` (223), `vérifié` (227), `configuración` (234),
`périmètre` (236), `attendu` (246), `résultat` (253), `utilisateur` (273), `échoue`
(274), `réel` (276), `contexte` (280), `constat` (284), `ajouter` (292), `publicar`
(296), `código` (302), `alcance` (310), `dependencias` (312), `restent` (314),
`vérifier` (319), `botón` (332), `comportement` (333), `pruebas` (337), `correctif`
(345), `dépend` (346), `sesión` (353), `réponse` (361), `contexto` (365), `écrit`
(367), `passent` (376), `erreur` (400), `critérios` (403), `modifié` (405), `bloque`
(415), `lignes` (416), `affiche` (428), `branche` (436), `abrir` (438), `apparaît`
(439), `confirmar` (442), `critère` (443), `evidencia` (444), `fusionnée` (445),
`lisible` (447), `nuvem` (449), `priorité` (450), `depende` (468), `pantalla` (470),
`producción` (474), `archivos` (477), `cambios` (478), `seulement` (484), `contrôle`
(488), `prueba` (499), `seule` (500).

Identifier, codename and version shards, 31 rows: `v0` (30), `if1` (44), `qwen3` (50),
`herdr` (54), `x402` (55), `nemoclaw` (57), `brihas` (66), `if0` (68), `sarathy` (93),
`stardelt` (100), `krikri` (114), `xhigh` (120), `if2` (149), `fc5q` (152), `39xc`
(154), `vjpf` (159), `crtl` (180), `77bits` (192), `ac5` (232), `1080p` (265), `if3`
(299), `romn` (316), `go1` (321), `ac7` (344), `v006` (355), `ac6` (368), `ac2` (385),
`ac4` (390), `500s` (402), `ventura8` (413), `arfan11` (441). These are the residual
class the digit rules do not touch: letter-first tokens and codenames with no digit
after the letter part.

Stem fragment from the lowered floor, 1 row: `alway` (279), the damaged lemma of
`always` (798 occurrences). The other two known defects are unchanged: `spe` (#781,
tf 258, df 127) and `unbound` (#1,097, tf 160, df 114) sit outside the candidate.

### Why the non-English rows entered

The old and new corpora differ by 284 documents out of 17,674, but those documents are
disproportionately French and Spanish. They are spread across many repositories (the
largest contribute 4 documents each), and they contain 90 raw `aucun` occurrences across
35 documents; the row moves from tf 35 / df 19 to tf 121 / df 54. This is
a floor effect, not a tokenizer effect: the English-ratio test counts a token as
English when wordfreq lists it at `>= 3e-07`, and wordfreq lists many French and
Spanish words at that level. At `1e-06` those documents scored below 0.6; at `3e-07`
they clear it. No tokenizer rule touched the ratio path (it filters to `isalpha()`
tokens before measuring).

## Top-40 changes

39 of v0's top 40 stay inside the top 40. `if1` drops from 40 to 44 and `aucun` enters
at 40. Positions otherwise move by one or two places because the vocabulary grew; the
visible movers are `yml` (9 → 6), `e2e` (21 → 19), `supabase` (31 → 28), `deepseek`
(36 → 29), `openbot` (46 → 37) and `i18n` (37 → 36); `v0` slips 28 → 30.

| # | term | tf | df | v0 # |
| --- | --- | --- | --- | --- |
| 1 | `worktree` | 595 | 292 | 1 |
| 2 | `sha256` | 246 | 140 | 2 |
| 3 | `webhook` | 245 | 111 | 3 |
| 4 | `arm64` | 223 | 156 | 4 |
| 5 | `allowlist` | 202 | 132 | 5 |
| 6 | `yml` | 199 | 126 | 9 |
| 7 | `docstring` | 198 | 139 | 6 |
| 8 | `typecheck` | 196 | 165 | 7 |
| 9 | `vitest` | 192 | 155 | 8 |
| 10 | `opencode` | 183 | 91 | 10 |
| 11 | `pytest` | 163 | 107 | 11 |
| 12 | `openapi` | 146 | 98 | 12 |
| 13 | `lockfile` | 145 | 88 | 13 |
| 14 | `soroban` | 140 | 97 | 14 |
| 15 | `coderabbit` | 139 | 83 | 15 |
| 16 | `sbom` | 137 | 21 | 16 |
| 17 | `subagent` | 159 | 65 | 17 |
| 18 | `vercel` | 133 | 73 | 18 |
| 19 | `e2e` | 754 | 429 | 21 |
| 20 | `chatgpt` | 124 | 63 | 19 |
| 21 | `dependabot` | 122 | 71 | 20 |
| 22 | `runbook` | 102 | 69 | 22 |
| 23 | `unmerged` | 97 | 86 | 23 |
| 24 | `toml` | 95 | 66 | 24 |
| 25 | `readback` | 101 | 79 | 25 |
| 26 | `idempotency` | 88 | 69 | 26 |
| 27 | `eslint` | 110 | 66 | 27 |
| 28 | `supabase` | 87 | 47 | 31 |
| 29 | `deepseek` | 86 | 51 | 36 |
| 30 | `v0` | 929 | 351 | 28 |
| 31 | `codeql` | 85 | 57 | 29 |
| 32 | `worktrees` | 85 | 59 | 30 |
| 33 | `lgtm` | 84 | 80 | 32 |
| 34 | `mergeable` | 83 | 71 | 33 |
| 35 | `pnpm` | 81 | 47 | 34 |
| 36 | `i18n` | 77 | 59 | 37 |
| 37 | `openbot` | 76 | 25 | 46 |
| 38 | `picomatch` | 75 | 35 | 35 |
| 39 | `webhooks` | 74 | 45 | 38 |
| 40 | `aucun` | 121 | 54 | 239 |

## Verdict against the Phase 2 exit condition

The Phase 2 exit condition is unchanged, and v0.1 does not meet it.

**Met, better than v0:**

- the ranking and the candidate are reproducible byte-identically from a fixed corpus;
- the tokenizer defect named in v0 is fixed for its stated classes: zero timestamp
  shards and zero CSS measurements in the top 500, and 31 fragment rows removed from
  the ranking entirely, while real digit-bearing terms (`sha256`, `arm64`, `e2e`,
  `i18n`, `aarch64`) keep their rows;
- the ingest counters now agree with the floor prediction (3,660 language drops),
  so the corpus and the floor documentation are consistent for the first time.

**Not met:**

- the candidate is still not a vocabulary dataset: 43.4% (b), 16.0% (c) and 22.0% (d);
- fragments did not shrink: 16.4% → 22.0%. The composition of the bucket changed
  completely — non-English strings replaced timestamp shards — but a release still
  cannot ship 110 rows of it;
- coverage of the eight target terms is still 1 of 8, and every target rank is slightly
  worse than in v0;
- the corpus is still one day of GitHub issue/PR prose, and the audit is still a single
  LLM annotation.

Conclusion: the tokenizer work is done; the language filter is now the dominant defect.
The `3e-07` floor is right for the lemmatizer but too permissive as a document-level
language test, because wordfreq's English list contains French and Spanish words at
that level. The next round should decide the language filter by script/stopword
evidence rather than by per-token frequency, and add a guard against stem fragments
(`alway`). Keep both v0 and v0.1 in `data/` as measurements.

# Part 3 — v0.2

**Status: candidate artifact, not a published dataset.** `data/core500-v0.2.jsonl`
takes the tokenizer from v0.1 and the corpus from v0, by giving the ingest English-ratio
test its own floor again. It is the first candidate whose corpus contains no
floor-admitted French/Spanish block. It is still one day of GH Archive prose, not Core
500. Parts 1 and 2 are kept unchanged as history; where they describe the two floors as
one shared constant, Part 3 supersedes them.

## What changed: two questions, two floors

The lemmatizer and the ingest language filter were asking different questions with one
number:

- the lemmatizer asks *"is this candidate a plausible English headword?"*. `3e-07` is
  the right answer: it is below the technical lemmas the corpus needs (`fallback`
  4.57e-07, `encode` 8.91e-07) and above the stem fragments that should not become
  lemmas. The round-6/7 evidence for it still holds;
- the ingest ratio test asks *"is this token evidence that the document is English?"*.
  At `3e-07` it is too loose: wordfreq's English list contains French and Spanish words
  at that level (`cette` 1.78e-07, `esta` 6.92e-07), so the ratio silently counted
  foreign function words as English evidence. Round 5 had already measured that
  `1e-06` works: every Spanish and Portuguese document dropped from the 1-hour corpus.

Round 8's regression is the cost of sharing: the day corpus at `3e-07` gained 284
French/Spanish documents, and non-English rows in the top 500 rose from v0's 17 to
v0.1's 78 (the "14" in the round-8 brief is the subset that survived into v0.1; three
Italian rows fell below its cut). The fix is therefore not a new filter design, it is
to stop pretending the two thresholds are one decision. The constants are now:

| constant | module | value | role |
| --- | --- | --- | --- |
| `LEMMA_MIN_FREQUENCY` | `src/vocabops/normalize.py` | `3e-07` | validates candidate lemmas |
| `ENGLISH_RATIO_MIN_FREQUENCY` | `src/vocabops/ingest.py` | `1e-06` | counts a token as document-level English evidence |

The old rationale — one constant so that "the two thresholds cannot drift apart" — was
wrong and is corrected in `docs/prototype.md`: drift was never the risk. The risk was
that one value would be forced to answer two questions, and it was. This also means
Part 2's closing suggestion (decide the language filter by script/stopword evidence)
was not taken this round: the measured frequency decoupling was tried first, and it
recovered the round-5 behaviour without new machinery. Script/stopword evidence remains
the right next step for the mixed-language residue (below).

## What was measured

| item | value |
| --- | --- |
| corpus | 24 hourly GH Archive files, 2026-11-18 00:00–23:59 UTC |
| documents | 17,390 |
| normalized tokens | 2,181,317 |
| ingest filters | `--exclude-bots --min-english-ratio 0.6 --dedup-text --max-docs 100000` |
| language-test floor | `1e-06` (`ENGLISH_RATIO_MIN_FREQUENCY`) |
| lemma validation floor | `3e-07` (`LEMMA_MIN_FREQUENCY`) |
| ranking cut | `--min-df 10` → 6,182 rows |
| candidate | first 500 rows, ranks 1–500 (cut score 5.919) |
| snapshot id | `gharchive-2026-11-18-day-v3` |
| corpus file | `out/gharchive/documents-day-v3.jsonl`, sha256 `74027bb1a605104c6800a7a62731eea1d7a9394cab5ae33f1e3b34ef8207e9ab` |
| candidate file | `data/core500-v0.2.jsonl`, sha256 `97565cc9a871aa56a1c308056a42991c98cba44eda8ed50e49b2ea00c0974c74` |
| audit file | `data/core500-v0.2-audit.jsonl`, sha256 `2b57c413715f8d5085921afc90a4f00301fb8cf160a2b9413230db22bb23ab0d` |

## Ingest counters: v1, v2, v3

v1 is the `1e-06` round-5 run with the old tokenizer; v2 is the `3e-07` shared-floor run
with the new tokenizer; v3 is this run.

| counter | v1 (`1e-06`) | v2 (`3e-07`) | v3 (`1e-06`) | v3 − v1 | v3 − v2 |
| --- | --- | --- | --- | --- | --- |
| input files | 24 | 24 | 24 | 0 | 0 |
| events seen | 121,837 | 121,837 | 121,837 | 0 | 0 |
| documents written | 17,390 | 17,674 | 17,390 | 0 | −284 |
| skipped: no body | 84,710 | 84,710 | 84,710 | 0 | 0 |
| skipped: bot actor | 14,874 | 14,874 | 14,874 | 0 | 0 |
| skipped: below english ratio | 3,954 | 3,660 | 3,954 | 0 | +294 |
| skipped: no alphabetic tokens | 18 | 18 | 18 | 0 | 0 |
| skipped: duplicate text | 891 | 901 | 891 | 0 | −10 |
| normalized tokens | 2,188,397 | 2,225,982 | 2,181,317 | −7,080 | −44,665 |

The totals close: 121,837 − 84,710 − 14,874 − 3,954 − 18 − 891 = 17,390.

**v3 is byte-identical to v1** (`cmp` clean, same sha256). That is the strongest
statement this round can make: returning the document test to `1e-06` reproduces the
round-5 corpus exactly, so the 284 documents v0.1 admitted are gone and no other
document changed. The tokenizer work between v1 and v3 does not flip a single document
at the 0.6 cut: the tokens it removes (timestamp shards, CSS measurements, digit-first
fragments) were either non-alphabetic or too rare to move any document's ratio across
the line. The 7,080-token drop against v1 is therefore pure tokenizer effect on the
same 17,390 documents, and the −44,665 against v2 is that plus the 284 dropped
documents.

Both re-runs are byte-identical: a second ingest produced the same corpus file, and two
pipeline runs on it produced identical `ranking.json`, `ranking.csv` and `manifest.json`
(verified with `cmp`). The candidate extraction also reproduced byte-identically.

## Coverage of the eight target terms

| term | v0 rank | v0.1 rank | v0.2 rank | tf | df |
| --- | --- | --- | --- | --- | --- |
| `fallback` | 188 | 199 | **185** | 1,192 | 688 |
| `reproduce` | 748 | 832 | 716 | 1,660 | 1,309 |
| `persist` | 1,208 | 1,363 | 1,176 | 480 | 327 |
| `invalidate` | 1,362 | 1,522 | 1,329 | 106 | 80 |
| `invoke` | 1,560 | 1,731 | 1,527 | 175 | 149 |
| `propagate` | 1,868 | 2,056 | 1,835 | 67 | 55 |
| `retrieve` | 3,408 | 3,652 | 3,375 | 58 | 48 |
| `underlying` | 4,312 | 4,560 | 4,279 | 76 | 71 |

Every tf/df is identical to v0, because the corpus is the same document set and these
terms are untouched by the tokenizer. All ranks improve by 3–116 places, and the whole
gain comes from the vocabulary shrinking from 6,215 to 6,182 rows: the 33 types the
tokenizer removes are 33 fewer competitors, not 33 fewer occurrences. `fallback` is
still the only target inside the 500. Target-adjacent rows move the same way: `retry`
105 → 110 → 104, `credential` 315 → 341 → 302, `endpoint` 435 → 467 → 407, `encode`
789 → 885 → 757.

## Composition audit

### Counts

| bucket | v0 | v0.1 | v0.2 |
| --- | --- | --- | --- |
| (a) transferable SE vocabulary | 94 (18.8%) | 85 (17.0%) | 103 (20.6%) |
| (b) technical nouns / product / tool / project names | 228 (45.6%) | 217 (43.4%) | 241 (48.2%) |
| (c) abbreviations and acronyms | 86 (17.2%) | 80 (16.0%) | 93 (18.6%) |
| (d) fragments and artifacts | 82 (16.4%) | 110 (22.0%) | 53 (10.6%) |
| (e) other / unclear | 10 (2.0%) | 8 (1.6%) | 10 (2.0%) |

v0.2 shares 469 terms with v0 and 434 with v0.1. Against v0: 31 rows left, 31 entered,
and the 31 that left are **exactly** the tokenizer fragment class — 25 ISO timestamp
shards, 5 CSS measurements and `7a7e3f9f`. Against v0.1: 66 replaced — 63 non-English
(d) rows, `dtos` (c), `fastify` and `unittest` (b); 36 rows that v0.1 had pushed out
return from v0, and 30 terms enter the candidate for the first time (`parse`, `append`,
`supersede`, `rollback`, `macos`, `gradle`, `prs`, `regex`, `mqtt`, `sasl`, …). No
shared term changed bucket.

The (b) share rises to 48.2%, above both earlier versions, and that is expected: the
slots freed by 57 fragment rows are filled by ordinary technical nouns, not by
transferable vocabulary. (a) also rises to 20.6%, but the candidate is still closer to
an ecosystem directory than to a vocabulary list.

### (d) fragments and artifacts — full list (53 terms)

Identifier, codename and version shards, 31 rows: `v0` (28), `if1` (40), `qwen3` (48),
`herdr` (51), `x402` (52), `nemoclaw` (54), `brihas` (62), `if0` (64), `sarathy` (87),
`stardelt` (94), `krikri` (107), `xhigh` (118), `if2` (139), `fc5q` (142), `39xc` (144),
`vjpf` (146), `crtl` (164), `77bits` (174), `ac5` (207), `1080p` (239), `if3` (269),
`romn` (281), `go1` (292), `ac7` (307), `v006` (317), `ac6` (327), `ac2` (344),
`ac4` (347), `500s` (359), `ventura8` (368), `arfan11` (389). This is the residue the
digit rules deliberately keep (letter-first tokens and codenames with no digit after
the letter part), unchanged in kind from v0.1.

Non-English strings, 18 rows: `अञ` (211), `गन` (212), `सङ` (226), `aucune` (233),
`aucun` (234), `गह` (249), `fichier` (261), `fichiers` (262), `relecture` (297),
`हळ` (299), `aceptación` (308), `criterios` (329), `critères` (411), `中文说明` (415),
`compilatore` (435), `proporre` (437), `sottoponi` (438), `branche` (493).

Artifacts, 4 rows: `alway` (252, the damaged lemma of `always`, 798 occurrences),
`404s` (434), `python3` (451), `µs` (482).

The non-English count is **18, back to v0's level**, but the honest accounting needs one
correction to the round-8 brief. v0 did not have 14 non-English rows in its top 500; it
had **17** — the 14 that also survived into v0.1 (`aucun`, `aucune`, `fichier`,
`fichiers`, `critères`, `criterios`, `aceptación`, `relecture`, `अञ`, `गन`, `सङ`, `गह`,
`हळ`, `中文说明`), plus `compilatore`, `proporre` and `sottoponi`, which fell just below
v0.1's deeper cut and are back now that the ranking is 292 rows smaller. v0.2's 18 are
the 15 non-English rows v0.1 retains (those 14 plus `branche`, v0.1 #436 and v0 #524)
and those three returning Italian rows. **Nothing new leaked in**: the fifteen are a
subset of v0.1's 78. So the right comparison is 17 → 78 → 18.

Two further facts matter more than the count. First, **no non-English row is above
#211** in v0.2; in v0.1 the highest was `écran` at #69 and eight sat above #200
(`écran` 69, `échec` 92, `usuario` 115, `décision` 128, `contenu` 157, `servidor` 158,
`revisión` 172, `preuve` 191). Second, the residue is no longer a separate
foreign-document block: the 284 documents are gone, so the remaining rows come from
mixed-language documents that are mostly English and still clear 0.6 (`compilatore` and
`proporre` have df 10, exactly the cut). A frequency floor cannot separate those;
script or stopword evidence is needed, as Part 2 said.

### `alway` / `spe` / `unbound`

The three known stem defects are unchanged in kind and now sit slightly higher because
the ranking is smaller: `alway` #252 (v0 #258, v0.1 #279; tf 798, df 668), `spe` #667
(v0 #699; tf 258, df 127), `unbound` #943 (v0 #975; tf 160, df 114). `alway` is the only
one of the three inside the 500. The decoupling does not touch the lemmatizer, so this
is the expected result; the guard against bare stems is still absent.

## Verdict against the Phase 2 exit condition

The Phase 2 exit condition is unchanged, and v0.2 still does not meet it.

**Met, better than v0 and v0.1:**

- the corpus, ranking and candidate are reproducible byte-identically, and v3's corpus
  is byte-identical to v1's — the decoupling has no hidden side effects;
- the language leak is fixed at its measured cause: 78 → 18 non-English rows, none
  above #211, and the 284 floor-admitted documents are gone;
- the tokenizer fix now shows its true effect, measured on a corpus that does not carry
  the language regression: 31 fragment rows removed and nothing else changed;
- the fragment share falls from 22.0% to 10.6%, below v0's 16.4%.

**Not met:**

- 10.6% is still a release blocker: 31 codename/identifier shards, 18 non-English
  strings and 4 artifacts remain in 500 rows;
- coverage of the target terms is still 1 of 8, though every target now ranks above its
  v0 position;
- (b) is 48.2% — the candidate is still an ecosystem directory with vocabulary mixed in;
- the audit is a single LLM annotation, and the corpus is one day of issue/PR prose.

Conclusion: the floors are correctly decoupled and this is the corpus the next round
should build on. The remaining defects are not frequency-threshold defects. The next
work is the one Part 2 named: script/stopword evidence in the language test for
mixed-language documents, and a bare-stem guard in the lemmatizer. Keep v0, v0.1 and
v0.2 in `data/` as measurements.
