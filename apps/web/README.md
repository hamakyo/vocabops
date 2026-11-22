# VocabOps Web — Learning MVP

Minimal, mobile-first daily learning UI backed by FSRS (`ts-fsrs`) and the shared VocabOps vocabulary schema (`data/releases/0.1.0-draft/vocabulary.json` and `data/sample.json`).

## Features

- **FSRS scheduling (`src/lib/scheduler.ts`)**: deterministic FSRS-5 scheduling (`enable_fuzz: false`) keyed by stable vocabulary IDs (`<lemma>.<pos>`), independent of streaks or gamification.
- **Today view**: New / Due Review / Learned counts, estimated retention %, daily new-card limit, dataset switcher, and category filter.
- **Three card modes (`src/lib/cards.ts`)**:
  - `Recognition` (EN term + collocations -> JA gloss & example)
  - `Active Recall` (JA software gloss -> EN term with optional typing check)
  - `Cloze` (EN sentence blank + JA translation -> target word/form, with graceful fallback to `Recognition` if a record has no cloze)
- **Persistence (`src/lib/storage.ts`)**: saves per-user review state in `localStorage` (`vocabops.review_store.v1`) with JSON export/import backup.

## Development

```sh
cd apps/web
npm install
npm run dev      # local dev server
npm test         # Vitest unit tests (FSRS lifecycle, card modes, persistence)
npm run build    # TypeScript check + production bundle
```
