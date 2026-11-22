import { useCallback, useMemo, useState } from "react";
import { SessionComplete } from "./components/SessionComplete";
import { StudyCard } from "./components/StudyCard";
import { TodaySummary } from "./components/TodaySummary";
import {
  type DatasetId,
  getDatasetById,
  listCategories,
} from "./lib/dataset";
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

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function App() {
  const [datasetId, setDatasetId] = useState<DatasetId>("core500-draft");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [studyMode, setStudyMode] = useState<StudyMode>("recognition");
  const [view, setView] = useState<View>("today");
  const [deckQuery, setDeckQuery] = useState<string>("");
  const [sessionReviewed, setSessionReviewed] = useState<number>(0);
  const [store, setStore] = useState<ReviewStore>(() =>
    loadReviewStore(browserStorage()),
  );
  const [now, setNow] = useState<Date>(() => new Date());

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
        window.alert(`Failed to import review state: ${String(err)}`);
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

  const deckFiltered = useMemo(() => {
    const q = deckQuery.trim().toLowerCase();
    return dataset.terms
      .filter((t) => {
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
      })
      .slice(0, 80);
  }, [dataset.terms, selectedCategory, deckQuery]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-title">VocabOps</span>
          <span className="brand-sub">
            {dataset.dataset} · {dataset.version}
          </span>
        </div>
        <nav className="nav-tabs" aria-label="Main navigation">
          <button
            type="button"
            className={`btn-tab ${view === "today" ? "active" : ""}`}
            onClick={() => {
              setNow(new Date());
              setView("today");
            }}
          >
            Today
          </button>
          <button
            type="button"
            className={`btn-tab ${view === "study" ? "active" : ""}`}
            onClick={() => {
              setNow(new Date());
              setView("study");
            }}
          >
            Study ({queue.items.length})
          </button>
          <button
            type="button"
            className={`btn-tab ${view === "deck" ? "active" : ""}`}
            onClick={() => setView("deck")}
          >
            Deck
          </button>
        </nav>
      </header>

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
          onStartSession={() => {
            setNow(new Date());
            setSessionReviewed(0);
            setView("study");
          }}
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
        <section className="card" aria-label="Deck browser">
          <input
            className="deck-search"
            type="search"
            value={deckQuery}
            onChange={(e) => setDeckQuery(e.target.value)}
            placeholder="Filter terms by English or Japanese..."
          />
          {deckFiltered.map((t) => {
            const card = store.cards[t.id] ?? null;
            const ret = getTermRetention(card, now, store.settings.requestRetention);
            return (
              <div key={t.id} className="deck-row">
                <div>
                  <span className="deck-term">{t.term}</span>{" "}
                  <span className="badge">{t.pos}</span>{" "}
                  {t.cefr && <span className="badge">{t.cefr}</span>}
                  <div className="deck-gloss">
                    {t.ja.software_gloss || t.ja.gloss}
                  </div>
                </div>
                <div style={{ textAlign: "right", fontSize: 12, color: "var(--muted)" }}>
                  {card ? (
                    <>
                      <div>reps: {card.reps}</div>
                      <div>{ret !== null ? `R ${Math.round(ret * 100)}%` : "learning"}</div>
                    </>
                  ) : (
                    <span>new</span>
                  )}
                </div>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
