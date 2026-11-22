import {
  BookOpen,
  Download,
  Gauge,
  Layers,
  Play,
  RotateCcw,
  Sparkles,
  Upload,
} from "lucide-react";
import { useRef } from "react";
import { cn } from "../lib/cn";
import { DATASETS, type DatasetId } from "../lib/dataset";
import { formatCategoryJa } from "../lib/labels";
import type { DailyQueue, PortfolioStats } from "../lib/scheduler";
import type { StudyMode, VocabularyDataset } from "../lib/schema";
import { Button, Card, ProgressBar } from "./ui/primitives";

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

const MODE_OPTIONS: { id: StudyMode; label: string; desc: string }[] = [
  { id: "recognition", label: "英→日", desc: "英語から意味を認識" },
  { id: "active-recall", label: "日→英", desc: "日本語から英語を想起" },
  { id: "cloze", label: "穴埋め", desc: "文脈から単語を補完" },
];

const SELECT_CLASS =
  "h-9 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-2xs transition-colors focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100";

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
  const dueTotal = queue.dueReviewCount + queue.learningCount;
  const retentionLabel =
    stats.averageRetention !== null
      ? `${Math.round(stats.averageRetention * 100)}%`
      : "—";

  const datasetNoteJa =
    datasetId === "core500-draft"
      ? "0.1.0-draft は GPU 生成の未レビュー下書きデータです（訳・例文は随時キュレーション予定）。"
      : "スキーマ確認用のサンプル語彙データセットです。";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>復習待ち</span>
            <Layers className="h-3.5 w-3.5 text-indigo-500" />
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
            {dueTotal}
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>今日の新規</span>
            <Sparkles className="h-3.5 w-3.5 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
            {queue.newAvailableCount}
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>学習済み</span>
            <BookOpen className="h-3.5 w-3.5 text-emerald-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-1 text-2xl font-semibold tracking-tight tabular-nums">
            <span>{stats.learnedCount}</span>
            <span className="text-xs font-normal text-zinc-400">
              / {stats.totalTerms}
            </span>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>推定定着率</span>
            <Gauge className="h-3.5 w-3.5 text-sky-500" />
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
            {retentionLabel}
          </div>
        </Card>
      </div>

      <Card className="p-5 sm:p-6">
        <div className="mb-5">
          <div className="mb-2 flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>学習カバー率</span>
            <span className="tabular-nums">
              {stats.totalTerms > 0
                ? Math.round((stats.learnedCount / stats.totalTerms) * 100)
                : 0}
              %
            </span>
          </div>
          <ProgressBar value={stats.learnedCount} max={stats.totalTerms} />
        </div>

        <div className="mb-5">
          <div className="mb-2 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            出題モード
          </div>
          <div
            className="grid grid-cols-3 gap-2"
            role="group"
            aria-label="出題モード"
          >
            {MODE_OPTIONS.map((opt) => {
              const active = studyMode === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onModeChange(opt.id)}
                  className={cn(
                    "rounded-xl border px-3 py-2.5 text-left transition-all cursor-pointer",
                    active
                      ? "border-indigo-600 bg-indigo-50/80 text-indigo-950 ring-1 ring-indigo-600 dark:border-indigo-400 dark:bg-indigo-950/50 dark:text-indigo-100 dark:ring-indigo-400"
                      : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950/60 dark:text-zinc-300 dark:hover:border-zinc-700",
                  )}
                >
                  <div className="text-sm font-semibold">{opt.label}</div>
                  <div className="mt-0.5 hidden text-[11px] text-zinc-500 dark:text-zinc-400 sm:block">
                    {opt.desc}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label
              htmlFor="dataset-select"
              className="mb-1.5 block text-xs font-medium text-zinc-500 dark:text-zinc-400"
            >
              データセット
            </label>
            <select
              id="dataset-select"
              className={SELECT_CLASS}
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

          <div>
            <label
              htmlFor="category-select"
              className="mb-1.5 block text-xs font-medium text-zinc-500 dark:text-zinc-400"
            >
              カテゴリ
            </label>
            <select
              id="category-select"
              className={SELECT_CLASS}
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

          <div>
            <label
              htmlFor="daily-new-select"
              className="mb-1.5 block text-xs font-medium text-zinc-500 dark:text-zinc-400"
            >
              1日の新規上限
            </label>
            <select
              id="daily-new-select"
              className={SELECT_CLASS}
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

          <div>
            <div className="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              今日の進捗
            </div>
            <div className="flex h-9 items-center rounded-lg border border-zinc-200/80 bg-zinc-50 px-3 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950/60 dark:text-zinc-300">
              <span>
                復習{" "}
                <strong className="font-semibold text-zinc-900 dark:text-zinc-100">
                  {stats.reviewedToday}回
                </strong>
              </span>
              {stats.goodOrEasyRateToday !== null && (
                <span className="ml-3">
                  正答率{" "}
                  <strong className="font-semibold text-emerald-600 dark:text-emerald-400">
                    {Math.round(stats.goodOrEasyRateToday * 100)}%
                  </strong>
                </span>
              )}
            </div>
          </div>
        </div>

        <Button
          variant="primary"
          size="lg"
          className="w-full"
          disabled={queue.items.length === 0}
          onClick={onStartSession}
        >
          <Play className="h-4 w-4 fill-current" />
          {queue.items.length > 0
            ? `今日の学習を始める（${queue.items.length}枚）`
            : "今日の学習は完了しています"}
        </Button>

        <p className="mt-4 rounded-xl border border-zinc-200/70 bg-zinc-50 px-3.5 py-2.5 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-400">
          {datasetNoteJa}
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800">
          <Button size="sm" onClick={onExportBackup}>
            <Download className="h-3.5 w-3.5" />
            履歴を書き出す
          </Button>
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            <Upload className="h-3.5 w-3.5" />
            履歴を読み込む
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              onImportBackup(await file.text());
              e.target.value = "";
            }}
          />
          <div className="flex-1" />
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              if (
                window.confirm(
                  "ローカルの FSRS 学習履歴をすべてリセットしますか？",
                )
              ) {
                onResetProgress();
              }
            }}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            リセット
          </Button>
        </div>
      </Card>
    </div>
  );
}
