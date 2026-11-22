import type { PortfolioStats } from "../lib/scheduler";

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
    <section className="card" aria-label="学習完了">
      <h2 style={{ marginTop: 0 }}>今日の学習が完了しました</h2>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>
        期限到来の復習と今日の新規カードは FSRS で次回の復習日時が設定されています。
      </p>

      <div className="metrics-grid">
        <div className="metric-tile">
          <div className="metric-value">{sessionReviewed}</div>
          <div className="metric-label">今回の学習</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{stats.reviewedToday}</div>
          <div className="metric-label">今日の合計</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{stats.learnedCount}</div>
          <div className="metric-label">学習済み</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{retentionLabel}</div>
          <div className="metric-label">推定定着率</div>
        </div>
      </div>

      <div className="cta-row">
        <button type="button" className="btn-primary" onClick={onReturnToday}>
          今日へ戻る
        </button>
        {stats.newCount > 0 && (
          <button type="button" onClick={onAddMoreNew}>
            新規カードを +5 枚追加して続ける
          </button>
        )}
      </div>
    </section>
  );
}
