import { describe, expect, it } from "vitest";
import { CORE500_DATASET, SAMPLE_DATASET } from "../src/lib/dataset";
import {
  buildDailyQueue,
  computePortfolioStats,
  getTermRetention,
  gradeTerm,
  previewGrades,
} from "../src/lib/scheduler";
import { createEmptyStore } from "../src/lib/storage";

describe("FSRS scheduler (Issue #2)", () => {
  const t0 = new Date("2026-06-01T09:00:00.000Z");

  it("operates on records from data/sample.json and Core 500 0.1.0-draft", () => {
    expect(SAMPLE_DATASET.terms.length).toBeGreaterThan(0);
    expect(CORE500_DATASET.terms.length).toBe(581);

    const store = createEmptyStore();
    const sampleQueue = buildDailyQueue(SAMPLE_DATASET.terms, store, t0);
    expect(sampleQueue.newAvailableCount).toBe(SAMPLE_DATASET.terms.length);
    expect(sampleQueue.dueReviewCount).toBe(0);

    const coreQueue = buildDailyQueue(CORE500_DATASET.terms, store, t0);
    expect(coreQueue.newAvailableCount).toBe(store.settings.dailyNewLimit);
  });

  it("produces deterministic next-review state for Again / Hard / Good / Easy", () => {
    const termId = SAMPLE_DATASET.terms[0].id;
    const base = createEmptyStore();

    for (const grade of ["again", "hard", "good", "easy"] as const) {
      const a = gradeTerm(base, termId, grade, "recognition", t0);
      const b = gradeTerm(base, termId, grade, "recognition", t0);
      expect(a).toEqual(b);
      expect(a.cards[termId].reps).toBe(1);
      expect(new Date(a.cards[termId].due).getTime()).toBeGreaterThanOrEqual(
        t0.getTime(),
      );
    }

    const previews = previewGrades(null, t0);
    expect(new Date(previews.easy.due).getTime()).toBeGreaterThan(
      new Date(previews.again.due).getTime(),
    );
  });

  it("covers New -> Learning -> Review -> Relearning lifecycle and retention decay", () => {
    const termId = "invalidate.v";
    let store = createEmptyStore();

    // 1. First Good review moves New -> Learning (short step)
    store = gradeTerm(store, termId, "good", "recognition", t0);
    const c1 = store.cards[termId];
    expect(c1.reps).toBe(1);
    expect(c1.lapses).toBe(0);

    // 2. Second Good review at due time graduates to Review (multi-day interval)
    const t1 = new Date(c1.due);
    store = gradeTerm(store, termId, "good", "active-recall", t1);
    const c2 = store.cards[termId];
    expect(c2.reps).toBe(2);
    expect(c2.scheduled_days).toBeGreaterThanOrEqual(1);

    // Retention is higher right after review than 10 days later.
    const rSoon = getTermRetention(c2, new Date(t1.getTime() + 3_600_000));
    const rLater = getTermRetention(
      c2,
      new Date(t1.getTime() + 10 * 86_400_000),
    );
    expect(rSoon).not.toBeNull();
    expect(rLater).not.toBeNull();
    expect(rSoon!).toBeGreaterThan(rLater!);

    // 3. Grading Again when due increments lapses and schedules short relearning
    const t2 = new Date(c2.due);
    store = gradeTerm(store, termId, "again", "cloze", t2);
    const c3 = store.cards[termId];
    expect(c3.lapses).toBe(1);
    expect(c3.reps).toBe(3);
  });

  it("prioritizes due reviews before new cards and enforces daily new limit", () => {
    const terms = SAMPLE_DATASET.terms.slice(0, 5);
    let store = createEmptyStore();
    store = { ...store, settings: { ...store.settings, dailyNewLimit: 2 } };

    // Introduce 2 cards today with Easy so both graduate beyond today
    store = gradeTerm(store, terms[0].id, "easy", "recognition", t0);
    store = gradeTerm(store, terms[1].id, "easy", "recognition", t0);

    // Same day: daily new limit reached -> 0 new cards left
    const sameDayQueue = buildDailyQueue(terms, store, new Date(t0.getTime() + 60_000));
    expect(sameDayQueue.newRemainingToday).toBe(0);
    expect(sameDayQueue.newAvailableCount).toBe(0);

    // Jump 30 days ahead: both learned cards are due before unseen new cards
    const future = new Date(t0.getTime() + 30 * 86_400_000);
    const futureQueue = buildDailyQueue(terms, store, future);
    expect(futureQueue.dueReviewCount).toBe(2);
    expect(futureQueue.newAvailableCount).toBe(2);
    expect(futureQueue.items[0].kind).toBe("review");
    expect(futureQueue.items[1].kind).toBe("review");
    expect(futureQueue.items[2].kind).toBe("new");

    const stats = computePortfolioStats(terms, store, future);
    expect(stats.learnedCount).toBe(2);
    expect(stats.dueCount).toBe(2);
    expect(stats.averageRetention).not.toBeNull();
  });
});
