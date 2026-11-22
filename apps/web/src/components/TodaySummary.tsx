import { useRef } from "react";
import { DATASETS, type DatasetId } from "../lib/dataset";
import type { DailyQueue, PortfolioStats } from "../lib/scheduler";
import type { StudyMode, VocabularyDataset } from "../lib/schema";

interface TodaySummaryProps {
  datasetId: DatasetId;
  dataset: VocabularyDataset;
  categories: string[];
  selectedCategory: string;
  studyMode: StudyMode;
  dailyNewLimit: number;
  queue: DailyQueue;
  stats: PortfolioStats;
  onDatasetChange: (id: DatasetId) => void;
  onCategoryChange: (cat: string) => void;
  onModeChange: (mode: StudyMode) => void;
  onDailyNewLimitChange: (limit: number) => void;
  onStartSession: () => void;
  onExportBackup: () => void;
  onImportBackup: (rawJson: string) => void;
  onResetProgress: () => void;
}

const MODE_OPTIONS: { id: StudyMode; label: string }[] = [
  { id: "recognition", label: "Recognition" },
  { id: "active-recall", label: "Active Recall" },
  { id: "cloze", label: "Cloze" },
];

export function TodaySummary({
  datasetId,
  dataset,
  categories,
  selectedCategory,
  studyMode,
  dailyNewLimit,
  queue,
  stats,
  onDatasetChange,
  onCategoryChange,
  onModeChange,
  onDailyNewLimitChange,
  onStartSession,
  onExportBackup,
  onImportBackup,
  onResetProgress,
}: TodaySummaryProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const retentionLabel =
    stats.averageRetention !== null
      ? `${Math.round(stats.averageRetention * 100)}%`
      : "—";

  return (
    <section className="card" aria-label="Today summary">
      <div className="metrics-grid">
        <div className="metric-tile">
          <div className="metric-value">{queue.dueReviewCount + queue.learningCount}</div>
          <div className="metric-label">Review due</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{queue.newAvailableCount}</div>
          <div className="metric-label">New today</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">
            {stats.learnedCount}
            <span style={{ fontSize: 13, fontWeight: 400, color: "var(--muted)" }}>
              /{stats.totalTerms}
            </span>
          </div>
          <div className="metric-label">Learned</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{retentionLabel}</div>
          <div className="metric-label">Est. retention</div>
        </div>
      </div>

      <div className="mode-pills" role="group" aria-label="Card mode">
        {MODE_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            className={`pill ${studyMode === opt.id ? "active" : ""}`}
            onClick={() => onModeChange(opt.id)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="controls-grid">
        <div className="control-group">
          <label htmlFor="dataset-select">Dataset</label>
          <select
            id="dataset-select"
            value={datasetId}
            onChange={(e) => onDatasetChange(e.target.value as DatasetId)}
          >
            {DATASETS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label htmlFor="category-select">Category filter</label>
          <select
            id="category-select"
            value={selectedCategory}
            onChange={(e) => onCategoryChange(e.target.value)}
          >
            <option value="">All categories ({dataset.terms.length})</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label htmlFor="daily-new-select">New cards / day</label>
          <select
            id="daily-new-select"
            value={dailyNewLimit}
            onChange={(e) => onDailyNewLimitChange(Number(e.target.value))}
          >
            {[5, 10, 15, 20, 30, 50].map((n) => (
              <option key={n} value={n}>
                {n} new / day
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label>Today progress</label>
          <div style={{ padding: "8px 0", fontSize: 13, color: "var(--muted)" }}>
            Reviewed: <strong style={{ color: "var(--text)" }}>{stats.reviewedToday}</strong>
            {stats.goodOrEasyRateToday !== null && (
              <>
                {" · "}Good/Easy:{" "}
                <strong style={{ color: "var(--text)" }}>
                  {Math.round(stats.goodOrEasyRateToday * 100)}%
                </strong>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="cta-row">
        <button
          type="button"
          className="btn-primary cta-start"
          disabled={queue.items.length === 0}
          onClick={onStartSession}
        >
          {queue.items.length > 0
            ? `Start Session (${queue.items.length} cards)`
            : "All caught up for today"}
        </button>
      </div>

      {dataset.note && <div className="note-banner">{dataset.note}</div>}

      <div className="footer-actions">
        <button type="button" onClick={onExportBackup}>
          Export review state
        </button>
        <button type="button" onClick={() => fileRef.current?.click()}>
          Import review state
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".json"
          style={{ display: "none" }}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            onImportBackup(await file.text());
            e.target.value = "";
          }}
        />
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => {
            if (window.confirm("Reset all local FSRS review history?")) {
              onResetProgress();
            }
          }}
        >
          Reset local state
        </button>
      </div>
    </section>
  );
}
