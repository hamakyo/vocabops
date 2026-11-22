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
    <section className="card" aria-label="Session complete">
      <h2 style={{ marginTop: 0 }}>Session complete</h2>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>
        All due reviews and today&apos;s new cards are scheduled via FSRS.
      </p>

      <div className="metrics-grid">
        <div className="metric-tile">
          <div className="metric-value">{sessionReviewed}</div>
          <div className="metric-label">This session</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{stats.reviewedToday}</div>
          <div className="metric-label">Reviewed today</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{stats.learnedCount}</div>
          <div className="metric-label">Total learned</div>
        </div>
        <div className="metric-tile">
          <div className="metric-value">{retentionLabel}</div>
          <div className="metric-label">Est. retention</div>
        </div>
      </div>

      <div className="cta-row">
        <button type="button" className="btn-primary" onClick={onReturnToday}>
          Back to Today
        </button>
        {stats.newCount > 0 && (
          <button type="button" onClick={onAddMoreNew}>
            Study +5 more new cards
          </button>
        )}
      </div>
    </section>
  );
}
