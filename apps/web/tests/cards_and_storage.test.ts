import { describe, expect, it } from "vitest";
import { buildCardPresentation, checkTypedAnswer } from "../src/lib/cards";
import { CORE500_DATASET, SAMPLE_DATASET } from "../src/lib/dataset";
import { gradeTerm } from "../src/lib/scheduler";
import {
  type KeyValueStorage,
  exportReviewStoreJson,
  loadReviewStore,
  parseReviewStore,
  saveReviewStore,
} from "../src/lib/storage";

function createMemoryStorage(): KeyValueStorage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => {
      map.set(k, v);
    },
    removeItem: (k) => {
      map.delete(k);
    },
  };
}

describe("Card modes and persistence", () => {
  it("builds recognition, active-recall, and cloze cards for sample.json", () => {
    const retrieve = SAMPLE_DATASET.terms.find((t) => t.id === "retrieve.v")!;

    const rec = buildCardPresentation(retrieve, "recognition");
    expect(rec.effectiveMode).toBe("recognition");
    expect(rec.promptPrimary).toBe("retrieve");

    const ar = buildCardPresentation(retrieve, "active-recall");
    expect(ar.effectiveMode).toBe("active-recall");
    expect(ar.answerPrimary).toBe("retrieve");
    expect(checkTypedAnswer("Retrieves", ar.expectedAnswers)).toBe(true);
    expect(checkTypedAnswer("delete", ar.expectedAnswers)).toBe(false);

    // sample.json omits precomputed cloze, so resolveCloze derives it on the fly
    const cl = buildCardPresentation(retrieve, "cloze");
    expect(cl.effectiveMode).toBe("cloze");
    expect(cl.promptPrimary).toContain("____");
    expect(cl.answerPrimary.toLowerCase()).toBe("retrieves");
  });

  it("falls back gracefully from cloze to recognition when target term is absent", () => {
    const param = CORE500_DATASET.terms.find((t) => t.id === "param.n")!;
    const card = buildCardPresentation(param, "cloze");
    expect(card.effectiveMode).toBe("recognition");
    expect(card.fallbackFromCloze).toBe(true);
  });

  it("persists review state across restarts and validates JSON backup roundtrip", () => {
    const mem = createMemoryStorage();
    const now = new Date("2026-06-01T12:00:00.000Z");

    let store = loadReviewStore(mem);
    store = gradeTerm(store, "invalidate.v", "good", "cloze", now);
    saveReviewStore(mem, store);

    // Simulate reload into fresh app instance
    const reloaded = loadReviewStore(mem);
    expect(reloaded).toEqual(store);
    expect(reloaded.cards["invalidate.v"].reps).toBe(1);

    const exported = exportReviewStoreJson(reloaded);
    expect(parseReviewStore(exported)).toEqual(reloaded);

    expect(() => parseReviewStore('{"schemaVersion": 99}')).toThrow();
  });
});
