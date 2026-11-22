import { useRef } from "react";
import { DATASETS, type DatasetId } from "../lib/dataset";
import { formatCategoryJa } from "../lib/labels";
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
  { id: "recognition", label: "英→日（認識）" },
  { id: "active-recall", label: "日→英（想起）" },
  { id: "cloze", label: "穴埋め（Cloze）" },
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

  const datasetNoteJa =
    datasetId === "core500-draft"
      ? "※ 0.1.0-draft は GPU 生成の未レビュー下書きデータです（訳・例文は随時キュレーション予定）。"
      : "※ スキーマ確認用のサンプル語彙データセットです。";

  return (
    <section className="card" aria-label="今日の学習サマリー">
      <div className="metrics-grid">
        <div className="metric-tile">
          <div className="metric-value">
            {queue.dueReviewCount + queue.learningCount}
          </div>
          <div className="metric-label">復習待ち</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{queue.newAvailableCount}</div>
          <div className="metric-label">今日の新規</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">
            {stats.learnedCount}
            <span style={{ fontSize: 13, fontWeight: 400, color: "var(--muted)" }}>
              /{stats.totalTerms}
            </span>
          </div>
          <div className="metric-label">学習済み</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{retentionLabel}</div>
          <div className="metric-label">推定定着率</div>
        </div>
      </div>

      <div className="mode-pills" role="group" aria-label="出題モード">
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
          <label htmlFor="dataset-select">データセット</label>
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
          <label htmlFor="category-select">カテゴリ</label>
          <select
            id="category-select"
            value={selectedCategory}
            onChange={(e) => onCategoryChange(e.target.value)}
          >
            <option value="">すべて（{dataset.terms.length}語）</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {formatCategoryJa(cat)}（{cat}）
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label htmlFor="daily-new-select">1日の新規カード上限</label>
          <select
            id="daily-new-select"
            value={dailyNewLimit}
            onChange={(e) => onDailyNewLimitChange(Number(e.target.value))}
          >
            {[5, 10, 15, 20, 30, 50].map((n) => (
              <option key={n} value={n}>
                {n}語 / 日
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label>今日の進捗</label>
          <div style={{ padding: "8px 0", fontSize: 13, color: "var(--muted)" }}>
            復習済み:{" "}
            <strong style={{ color: "var(--text)" }}>
              {stats.reviewedToday}回
            </strong>
            {stats.goodOrEasyRateToday !== null && (
              <>
                {" · "}正答率:{" "}
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
            ? `今日の学習を始める（${queue.items.length}枚）`
            : "今日の学習は完了しています"}
        </button>
      </div>

      <div className="note-banner">{datasetNoteJa}</div>

      <div className="footer-actions">
        <button type="button" onClick={onExportBackup}>
          学習履歴を書き出す
        </button>
        <button type="button" onClick={() => fileRef.current?.click()}>
          学習履歴を読み込む
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
            if (window.confirm("ローカルの FSRS 学習履歴をすべてリセットしますか？")) {
              onResetProgress();
            }
          }}
        >
          履歴をリセット
        </button>
      </div>
    </section>
  );
}
