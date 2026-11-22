import {
  type Card,
  type Grade as FsrsGrade,
  Rating,
  State,
  createEmptyCard,
  fsrs,
  generatorParameters,
} from "ts-fsrs";
import type {
  Grade,
  ReviewStore,
  SerializedFsrsCard,
  StudyMode,
  VocabularyTerm,
} from "./schema";

export const GRADE_TO_RATING: Record<Grade, FsrsGrade> = {
  again: Rating.Again,
  hard: Rating.Hard,
  good: Rating.Good,
  easy: Rating.Easy,
};

export interface GradePreview {
  grade: Grade;
  due: string;
  intervalLabel: string;
  scheduledDays: number;
}

export interface QueueItem {
  term: VocabularyTerm;
  kind: "review" | "learning" | "new";
  card: SerializedFsrsCard | null;
}

export interface DailyQueue {
  items: QueueItem[];
  dueReviewCount: number;
  learningCount: number;
  newAvailableCount: number;
  newRemainingToday: number;
}

export interface PortfolioStats {
  totalTerms: number;
  learnedCount: number;
  newCount: number;
  dueCount: number;
  reviewedToday: number;
  goodOrEasyRateToday: number | null;
  averageRetention: number | null;
}

function createScheduler(requestRetention: number) {
  return fsrs(
    generatorParameters({
      request_retention: requestRetention,
      enable_fuzz: false,
      enable_short_term: true,
    }),
  );
}

export function serializeCard(card: Card): SerializedFsrsCard {
  return {
    due: card.due.toISOString(),
    stability: card.stability,
    difficulty: card.difficulty,
    elapsed_days: card.elapsed_days,
    scheduled_days: card.scheduled_days,
    learning_steps: card.learning_steps,
    reps: card.reps,
    lapses: card.lapses,
    state: card.state,
    last_review: card.last_review ? card.last_review.toISOString() : null,
  };
}

export function deserializeCard(card: SerializedFsrsCard): Card {
  return {
    due: new Date(card.due),
    stability: card.stability,
    difficulty: card.difficulty,
    elapsed_days: card.elapsed_days,
    scheduled_days: card.scheduled_days,
    learning_steps: card.learning_steps,
    reps: card.reps,
    lapses: card.lapses,
    state: card.state as State,
    last_review: card.last_review ? new Date(card.last_review) : undefined,
  };
}

export function formatInterval(now: Date, due: Date): string {
  const diffMs = Math.max(0, due.getTime() - now.getTime());
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "1分未満";
  if (minutes < 60) return `${minutes}分`;
  const hours = Math.round(diffMs / 3_600_000);
  if (hours < 24) return `${hours}時間`;
  const days = Math.round(diffMs / 86_400_000);
  if (days < 30) return `${days}日`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}ヶ月`;
  const years = (days / 365).toFixed(1).replace(/\.0$/, "");
  return `${years}年`;
}

export function previewGrades(
  existingCard: SerializedFsrsCard | null,
  now: Date,
  requestRetention = 0.9,
): Record<Grade, GradePreview> {
  const scheduler = createScheduler(requestRetention);
  const card = existingCard ? deserializeCard(existingCard) : createEmptyCard(now);
  const outcomes = scheduler.repeat(card, now);

  const grades: Grade[] = ["again", "hard", "good", "easy"];
  const result = {} as Record<Grade, GradePreview>;
  for (const grade of grades) {
    const rating = GRADE_TO_RATING[grade];
    const nextCard = outcomes[rating].card;
    result[grade] = {
      grade,
      due: nextCard.due.toISOString(),
      intervalLabel: formatInterval(now, nextCard.due),
      scheduledDays: nextCard.scheduled_days,
    };
  }
  return result;
}

export function gradeTerm(
  store: ReviewStore,
  termId: string,
  grade: Grade,
  mode: StudyMode,
  now: Date,
): ReviewStore {
  const scheduler = createScheduler(store.settings.requestRetention);
  const prev = store.cards[termId]
    ? deserializeCard(store.cards[termId])
    : createEmptyCard(now);
  const rating = GRADE_TO_RATING[grade];
  const next = scheduler.repeat(prev, now)[rating].card;
  const serialized = serializeCard(next);

  return {
    ...store,
    cards: {
      ...store.cards,
      [termId]: serialized,
    },
    history: [
      ...store.history,
      {
        termId,
        grade,
        mode,
        reviewedAt: now.toISOString(),
        scheduledDays: serialized.scheduled_days,
      },
    ],
  };
}

export function getTermRetention(
  card: SerializedFsrsCard | null,
  now: Date,
  requestRetention = 0.9,
): number | null {
  if (!card || card.reps === 0 || !card.last_review) return null;
  const scheduler = createScheduler(requestRetention);
  const ret = scheduler.get_retrievability(deserializeCard(card), now, false);
  return typeof ret === "number" && Number.isFinite(ret) ? ret : null;
}

function localDayKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function countNewIntroducedToday(store: ReviewStore, now: Date): number {
  const today = localDayKey(now);
  const firstSeenDay = new Map<string, string>();
  for (const entry of store.history) {
    if (!firstSeenDay.has(entry.termId)) {
      firstSeenDay.set(entry.termId, localDayKey(new Date(entry.reviewedAt)));
    }
  }
  let count = 0;
  for (const day of firstSeenDay.values()) {
    if (day === today) count += 1;
  }
  return count;
}

export function buildDailyQueue(
  terms: readonly VocabularyTerm[],
  store: ReviewStore,
  now: Date,
  options?: {
    category?: string | null;
    learningWindowMinutes?: number;
  },
): DailyQueue {
  const category = options?.category ?? null;
  const learningWindowMs = (options?.learningWindowMinutes ?? 20) * 60_000;
  const nowMs = now.getTime();

  const filtered = category
    ? terms.filter((t) => t.categories.includes(category))
    : terms;

  const dueReviews: QueueItem[] = [];
  const learningSoon: QueueItem[] = [];
  const unseen: QueueItem[] = [];

  for (const term of filtered) {
    const card = store.cards[term.id] ?? null;
    if (!card) {
      unseen.push({ term, kind: "new", card: null });
      continue;
    }
    const dueMs = new Date(card.due).getTime();
    const isLearningState =
      card.state === State.Learning || card.state === State.Relearning;
    if (dueMs <= nowMs) {
      dueReviews.push({
        term,
        kind: isLearningState ? "learning" : "review",
        card,
      });
    } else if (isLearningState && dueMs <= nowMs + learningWindowMs) {
      learningSoon.push({ term, kind: "learning", card });
    }
  }

  const byDueAsc = (a: QueueItem, b: QueueItem) => {
    const da = a.card ? new Date(a.card.due).getTime() : 0;
    const db = b.card ? new Date(b.card.due).getTime() : 0;
    return da - db || a.term.id.localeCompare(b.term.id);
  };
  dueReviews.sort(byDueAsc);
  learningSoon.sort(byDueAsc);

  const introducedToday = countNewIntroducedToday(store, now);
  const newRemainingToday = Math.max(
    0,
    store.settings.dailyNewLimit - introducedToday,
  );
  const newQueue = unseen.slice(0, newRemainingToday);

  return {
    items: [...dueReviews, ...newQueue, ...learningSoon],
    dueReviewCount: dueReviews.length,
    learningCount: learningSoon.length,
    newAvailableCount: newQueue.length,
    newRemainingToday,
  };
}

export function computePortfolioStats(
  terms: readonly VocabularyTerm[],
  store: ReviewStore,
  now: Date,
): PortfolioStats {
  const nowMs = now.getTime();
  const today = localDayKey(now);
  const termIds = new Set(terms.map((t) => t.id));

  let learnedCount = 0;
  let dueCount = 0;
  const retentions: number[] = [];

  for (const term of terms) {
    const card = store.cards[term.id] ?? null;
    if (!card) continue;
    learnedCount += 1;
    if (new Date(card.due).getTime() <= nowMs) {
      dueCount += 1;
    }
    const ret = getTermRetention(card, now, store.settings.requestRetention);
    if (ret !== null) {
      retentions.push(ret);
    }
  }

  const todayHistory = store.history.filter(
    (h) => termIds.has(h.termId) && localDayKey(new Date(h.reviewedAt)) === today,
  );
  const goodOrEasy = todayHistory.filter(
    (h) => h.grade === "good" || h.grade === "easy",
  ).length;

  return {
    totalTerms: terms.length,
    learnedCount,
    newCount: terms.length - learnedCount,
    dueCount,
    reviewedToday: todayHistory.length,
    goodOrEasyRateToday:
      todayHistory.length > 0 ? goodOrEasy / todayHistory.length : null,
    averageRetention:
      retentions.length > 0
        ? retentions.reduce((sum, v) => sum + v, 0) / retentions.length
        : null,
  };
}
