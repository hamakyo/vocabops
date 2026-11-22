import type { ReviewStore } from "./schema";

export const STORAGE_KEY = "vocabops.review_store.v1";
export const DEFAULT_DAILY_NEW_LIMIT = 15;
export const DEFAULT_REQUEST_RETENTION = 0.9;

export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export function createEmptyStore(): ReviewStore {
  return {
    schemaVersion: 1,
    cards: {},
    history: [],
    settings: {
      dailyNewLimit: DEFAULT_DAILY_NEW_LIMIT,
      requestRetention: DEFAULT_REQUEST_RETENTION,
    },
  };
}

export function parseReviewStore(raw: string): ReviewStore {
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object") {
    throw new Error("Review store must be a JSON object");
  }
  const obj = parsed as Partial<ReviewStore>;
  if (obj.schemaVersion !== 1) {
    throw new Error(`Unsupported review store schemaVersion: ${String(obj.schemaVersion)}`);
  }
  if (!obj.cards || typeof obj.cards !== "object" || Array.isArray(obj.cards)) {
    throw new Error("Review store 'cards' must be an object");
  }
  if (!Array.isArray(obj.history)) {
    throw new Error("Review store 'history' must be an array");
  }

  const dailyNewLimit =
    typeof obj.settings?.dailyNewLimit === "number" &&
    Number.isFinite(obj.settings.dailyNewLimit) &&
    obj.settings.dailyNewLimit >= 0
      ? Math.round(obj.settings.dailyNewLimit)
      : DEFAULT_DAILY_NEW_LIMIT;

  const requestRetention =
    typeof obj.settings?.requestRetention === "number" &&
    obj.settings.requestRetention > 0.5 &&
    obj.settings.requestRetention < 0.99
      ? obj.settings.requestRetention
      : DEFAULT_REQUEST_RETENTION;

  return {
    schemaVersion: 1,
    cards: { ...obj.cards },
    history: [...obj.history],
    settings: {
      dailyNewLimit,
      requestRetention,
    },
  };
}

export function loadReviewStore(storage: KeyValueStorage | null): ReviewStore {
  if (!storage) return createEmptyStore();
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return createEmptyStore();
    return parseReviewStore(raw);
  } catch {
    return createEmptyStore();
  }
}

export function saveReviewStore(
  storage: KeyValueStorage | null,
  store: ReviewStore,
): void {
  if (!storage) return;
  storage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export function exportReviewStoreJson(store: ReviewStore): string {
  const sortedCards: ReviewStore["cards"] = {};
  for (const key of Object.keys(store.cards).sort()) {
    sortedCards[key] = store.cards[key];
  }
  return `${JSON.stringify({ ...store, cards: sortedCards }, null, 2)}\n`;
}
