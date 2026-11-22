import { CheckCircle2, Plus } from "lucide-react";
import type { PortfolioStats } from "../lib/scheduler";
import { Button, Card } from "./ui/primitives";

interface SessionCompleteProps {
  stats: PortfolioStats;
  sessionReviewed: number;
  onReturnToday: () => void;
  onAddMoreNew: () => void;
}

export function SessionComplete({
  stats,
  sessionReviewed,
  onReturnToday,
  onAddMoreNew,
}: SessionCompleteProps) {
  const retentionLabel =
    stats.averageRetention !== null
      ? `${Math.round(stats.averageRetention * 100)}%`
      : "—";

  return (
    <Card className="p-6 text-center sm:p-8" aria-label="学習完了">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
        <CheckCircle2 className="h-6 w-6" />
      </div>
      <h2 className="text-xl font-bold tracking-tight">
        今日の学習が完了しました
      </h2>
      <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
        期限到来の復習と今日の新規カードは FSRS で次回の復習日時が設定されています。
      </p>

      <div className="my-6 grid grid-cols-2 gap-3 text-left sm:grid-cols-4">
        <div className="rounded-xl border border-zinc-200/80 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/60">
          <div className="text-xl font-semibold tabular-nums">{sessionReviewed}</div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">今回の学習</div>
        </div>
        <div className="rounded-xl border border-zinc-200/80 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/60">
          <div className="text-xl font-semibold tabular-nums">{stats.reviewedToday}</div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">今日の合計</div>
        </div>
        <div className="rounded-xl border border-zinc-200/80 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/60">
          <div className="text-xl font-semibold tabular-nums">{stats.learnedCount}</div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">学習済み</div>
        </div>
        <div className="rounded-xl border border-zinc-200/80 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/60">
          <div className="text-xl font-semibold tabular-nums">{retentionLabel}</div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">推定定着率</div>
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-2.5">
        <Button variant="primary" size="lg" onClick={onReturnToday}>
          今日へ戻る
        </Button>
        {stats.newCount > 0 && (
          <Button size="lg" onClick={onAddMoreNew}>
            <Plus className="h-4 w-4" />
            新規カードを +5 枚追加して続ける
          </Button>
        )}
      </div>
    </Card>
  );
}
