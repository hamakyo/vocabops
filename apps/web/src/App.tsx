import { BookMarked, Moon, Search, Sun } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SessionComplete } from "./components/SessionComplete";
import { StudyCard } from "./components/StudyCard";
import { TodaySummary } from "./components/TodaySummary";
import { Badge, Button, Card } from "./components/ui/primitives";
import { cn } from "./lib/cn";
import {
  type DatasetId,
  getDatasetById,
  listCategories,
} from "./lib/dataset";
import { formatPosJa } from "./lib/labels";
import {
  buildDailyQueue,
  computePortfolioStats,
  getTermRetention,
  gradeTerm,
  previewGrades,
} from "./lib/scheduler";
import type { Grade, ReviewStore, StudyMode } from "./lib/schema";
import {
  createEmptyStore,
  exportReviewStoreJson,
  loadReviewStore,
  parseReviewStore,
  saveReviewStore,
} from "./lib/storage";

type View = "today" | "study" | "deck";

const THEME_KEY = "vocabops.theme";

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function getInitialDark(): boolean {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === "dark") return true;
    if (saved === "light") return false;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

export function App() {
  const [dark, setDark] = useState<boolean>(getInitialDark);
  const [datasetId, setDatasetId] = useState<DatasetId>("core500-draft");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [studyMode, setStudyMode] = useState<StudyMode>("recognition");
  const [view, setView] = useState<View>("today");
  const [deckQuery, setDeckQuery] = useState<string>("");
  const [sessionReviewed, setSessionReviewed] = useState<number>(0);
  const [sessionInitialCount, setSessionInitialCount] = useState<number>(0);
  const [store, setStore] = useState<ReviewStore>(() =>
    loadReviewStore(browserStorage()),
  );
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      window.localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
    } catch {
      // ignore storage errors
    }
  }, [dark]);

  const dataset = useMemo(() => getDatasetById(datasetId), [datasetId]);
  const categories = useMemo(() => listCategories(dataset), [dataset]);

  const updateStore = useCallback((next: ReviewStore) => {
    setStore(next);
    saveReviewStore(browserStorage(), next);
  }, []);

  const queue = useMemo(
    () =>
      buildDailyQueue(dataset.terms, store, now, {
        category: selectedCategory || null,
      }),
    [dataset.terms, store, now, selectedCategory],
  );

  const stats = useMemo(
    () => computePortfolioStats(dataset.terms, store, now),
    [dataset.terms, store, now],
  );

  const currentItem = queue.items[0] ?? null;

  const currentPreviews = useMemo(
    () =>
      currentItem
        ? previewGrades(
            currentItem.card,
            now,
            store.settings.requestRetention,
          )
        : null,
    [currentItem, now, store.settings.requestRetention],
  );

  const currentRetention = useMemo(
    () =>
      currentItem
        ? getTermRetention(
            currentItem.card,
            now,
            store.settings.requestRetention,
          )
        : null,
    [currentItem, now, store.settings.requestRetention],
  );

  const handleGrade = useCallback(
    (grade: Grade) => {
      if (!currentItem) return;
      const reviewTime = new Date();
      const nextStore = gradeTerm(
        store,
        currentItem.term.id,
        grade,
        studyMode,
        reviewTime,
      );
      updateStore(nextStore);
      setNow(reviewTime);
      setSessionReviewed((c) => c + 1);
    },
    [currentItem, store, studyMode, updateStore],
  );

  const handleDailyNewLimitChange = useCallback(
    (limit: number) => {
      updateStore({
        ...store,
        settings: { ...store.settings, dailyNewLimit: limit },
      });
    },
    [store, updateStore],
  );

  const handleExportBackup = useCallback(() => {
    const json = exportReviewStoreJson(store);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vocabops-review-state.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [store]);

  const handleImportBackup = useCallback(
    (rawJson: string) => {
      try {
        const parsed = parseReviewStore(rawJson);
        updateStore(parsed);
        setNow(new Date());
      } catch (err) {
        window.alert(`学習履歴の読み込みに失敗しました: ${String(err)}`);
      }
    },
    [updateStore],
  );

  const handleResetProgress = useCallback(() => {
    const empty = createEmptyStore();
    updateStore(empty);
    setSessionReviewed(0);
    setNow(new Date());
  }, [updateStore]);

  const startSession = useCallback(() => {
    const freshNow = new Date();
    const freshQueue = buildDailyQueue(dataset.terms, store, freshNow, {
      category: selectedCategory || null,
    });
    setNow(freshNow);
    setSessionReviewed(0);
    setSessionInitialCount(freshQueue.items.length);
    setView("study");
  }, [dataset.terms, store, selectedCategory]);

  const deckMatches = useMemo(() => {
    const q = deckQuery.trim().toLowerCase();
    return dataset.terms.filter((t) => {
      if (selectedCategory && !t.categories.includes(selectedCategory)) {
        return false;
      }
      if (!q) return true;
      return (
        t.id.toLowerCase().includes(q) ||
        t.term.toLowerCase().includes(q) ||
        t.ja.gloss.toLowerCase().includes(q) ||
        t.ja.software_gloss.toLowerCase().includes(q)
      );
    });
  }, [dataset.terms, selectedCategory, deckQuery]);

  const deckFiltered = useMemo(() => deckMatches.slice(0, 80), [deckMatches]);

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="sticky top-0 z-20 border-b border-zinc-200/80 bg-white/85 backdrop-blur-md dark:border-zinc-800/80 dark:bg-zinc-950/85">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-xs">
              <BookMarked className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight">VocabOps</div>
              <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                エンジニア英語学習 · {dataset.version}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <nav
              className="flex rounded-xl border border-zinc-200 bg-zinc-100/80 p-0.5 dark:border-zinc-800 dark:bg-zinc-900"
              aria-label="メインナビゲーション"
            >
              {(
                [
                  { id: "today", label: "今日" },
                  { id: "study", label: `学習 (${queue.items.length})` },
                  { id: "deck", label: "単語一覧" },
                ] as { id: View; label: string }[]
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => {
                    if (tab.id === "study") {
                      startSession();
                    } else {
                      setNow(new Date());
                      setView(tab.id);
                    }
                  }}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-xs font-medium transition-all cursor-pointer",
                    view === tab.id
                      ? "bg-white text-zinc-900 shadow-2xs dark:bg-zinc-800 dark:text-zinc-50"
                      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            <Button
              size="sm"
              variant="ghost"
              className="h-8 w-8 p-0"
              aria-label={dark ? "ライトモードへ切替" : "ダークモードへ切替"}
              onClick={() => setDark((d) => !d)}
            >
              {dark ? (
                <Sun className="h-4 w-4 text-amber-400" />
              ) : (
                <Moon className="h-4 w-4 text-zinc-600" />
              )}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 pb-16">
        {view === "today" && (
          <TodaySummary
            datasetId={datasetId}
            dataset={dataset}
            categories={categories}
            selectedCategory={selectedCategory}
            studyMode={studyMode}
            dailyNewLimit={store.settings.dailyNewLimit}
            queue={queue}
            stats={stats}
            onDatasetChange={(id) => {
              setDatasetId(id);
              setSelectedCategory("");
            }}
            onCategoryChange={setSelectedCategory}
            onModeChange={setStudyMode}
            onDailyNewLimitChange={handleDailyNewLimitChange}
            onStartSession={startSession}
            onExportBackup={handleExportBackup}
            onImportBackup={handleImportBackup}
            onResetProgress={handleResetProgress}
          />
        )}

        {view === "study" &&
          (currentItem && currentPreviews ? (
            <StudyCard
              item={currentItem}
              remainingCount={queue.items.length}
              sessionTotal={sessionInitialCount}
              sessionCompleted={sessionReviewed}
              studyMode={studyMode}
              previews={currentPreviews}
              retention={currentRetention}
              onGrade={handleGrade}
              onExit={() => {
                setNow(new Date());
                setView("today");
              }}
            />
          ) : (
            <SessionComplete
              stats={stats}
              sessionReviewed={sessionReviewed}
              onReturnToday={() => {
                setNow(new Date());
                setView("today");
              }}
              onAddMoreNew={() => {
                handleDailyNewLimitChange(store.settings.dailyNewLimit + 5);
                setNow(new Date());
              }}
            />
          ))}

        {view === "deck" && (
          <Card className="p-4 sm:p-5" aria-label="単語一覧">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <input
                type="search"
                value={deckQuery}
                onChange={(e) => setDeckQuery(e.target.value)}
                placeholder="英単語・日本語訳で絞り込み..."
                className="h-10 w-full rounded-xl border border-zinc-200 bg-zinc-50 pr-3 pl-9 text-sm text-zinc-900 focus:border-indigo-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
              />
            </div>

            <div className="mb-2 text-xs text-zinc-500 dark:text-zinc-400">
              表示中 {deckFiltered.length} / 該当 {deckMatches.length} 語
            </div>

            <div className="divide-y divide-zinc-200/80 dark:divide-zinc-800">
              {deckFiltered.map((t) => {
                const card = store.cards[t.id] ?? null;
                const ret = getTermRetention(
                  card,
                  now,
                  store.settings.requestRetention,
                );
                return (
                  <div
                    key={t.id}
                    className="flex items-start justify-between gap-3 py-3"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold text-zinc-950 dark:text-zinc-50">
                          {t.term}
                        </span>
                        <Badge>{formatPosJa(t.pos)}</Badge>
                        {t.cefr && <Badge variant="outline">{t.cefr}</Badge>}
                      </div>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        {t.ja.software_gloss || t.ja.gloss}
                      </p>
                    </div>
                    <div className="shrink-0 text-right text-xs text-zinc-500 tabular-nums dark:text-zinc-400">
                      {card ? (
                        <>
                          <div>復習 {card.reps} 回</div>
                          <div className="mt-0.5 text-emerald-600 dark:text-emerald-400">
                            {ret !== null
                              ? `定着率 ${Math.round(ret * 100)}%`
                              : "学習中"}
                          </div>
                        </>
                      ) : (
                        <span className="text-zinc-400">未学習</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}
      </main>
    </div>
  );
}
