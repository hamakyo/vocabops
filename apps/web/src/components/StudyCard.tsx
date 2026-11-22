import { useEffect, useState } from "react";
import { buildCardPresentation, checkTypedAnswer } from "../lib/cards";
import {
  formatCategoryJa,
  formatPosJa,
  formatQueueKindJa,
} from "../lib/labels";
import type { GradePreview, QueueItem } from "../lib/scheduler";
import type { Grade, StudyMode } from "../lib/schema";

interface StudyCardProps {
  item: QueueItem;
  remainingCount: number;
  studyMode: StudyMode;
  previews: Record<Grade, GradePreview>;
  retention: number | null;
  onGrade: (grade: Grade) => void;
  onExit: () => void;
}

const RATINGS: { grade: Grade; label: string; keyHint: string }[] = [
  { grade: "again", label: "もう一度", keyHint: "1" },
  { grade: "hard", label: "難しい", keyHint: "2" },
  { grade: "good", label: "普通", keyHint: "3" },
  { grade: "easy", label: "簡単", keyHint: "4" },
];

export function StudyCard({
  item,
  remainingCount,
  studyMode,
  previews,
  retention,
  onGrade,
  onExit,
}: StudyCardProps) {
  const [revealed, setRevealed] = useState(false);
  const [typed, setTyped] = useState("");
  const [checked, setChecked] = useState<boolean | null>(null);

  const { term } = item;
  const presentation = buildCardPresentation(term, studyMode);
  const supportsTyping =
    presentation.effectiveMode === "active-recall" ||
    presentation.effectiveMode === "cloze";

  useEffect(() => {
    setRevealed(false);
    setTyped("");
    setChecked(null);
  }, [term.id, item.card?.reps, studyMode]);

  useEffect(() => {
    const onKeyDown = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        return;
      }
      if (!revealed && (ev.key === " " || ev.key === "Enter")) {
        ev.preventDefault();
        setRevealed(true);
      } else if (revealed) {
        if (ev.key === "1") onGrade("again");
        else if (ev.key === "2") onGrade("hard");
        else if (ev.key === "3") onGrade("good");
        else if (ev.key === "4") onGrade("easy");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [revealed, onGrade]);

  const handleCheck = () => {
    setChecked(checkTypedAnswer(typed, presentation.expectedAnswers));
    setRevealed(true);
  };

  return (
    <section className="card" aria-label="学習カード">
      <div className="card-meta">
        <div className="badge-row">
          <span className="badge badge-kind">{formatQueueKindJa(item.kind)}</span>
          <span className="badge">{formatPosJa(term.pos)}</span>
          {term.cefr && <span className="badge">{term.cefr}</span>}
          {term.curation?.status === "draft" && (
            <span className="badge badge-draft">未レビュー</span>
          )}
          {retention !== null && (
            <span className="badge">定着率 {Math.round(retention * 100)}%</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span>残り {remainingCount} 枚</span>
          <button
            type="button"
            onClick={onExit}
            style={{ padding: "4px 10px", fontSize: 12 }}
          >
            今日へ戻る
          </button>
        </div>
      </div>

      <div className="prompt-label">{presentation.promptLabel}</div>
      <h2
        className={`prompt-main ${
          presentation.effectiveMode === "cloze" ? "sentence" : ""
        }`}
      >
        {presentation.promptPrimary}
      </h2>
      {presentation.promptSecondary && (
        <p className="prompt-sub">{presentation.promptSecondary}</p>
      )}

      {supportsTyping && !revealed && (
        <form
          className="type-row"
          onSubmit={(e) => {
            e.preventDefault();
            handleCheck();
          }}
        >
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="英単語を入力（任意）..."
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit">答え合わせ</button>
        </form>
      )}

      {!revealed ? (
        <button
          type="button"
          className="btn-primary reveal-btn"
          onClick={() => setRevealed(true)}
        >
          答えを見る（Space）
        </button>
      ) : (
        <div className="answer-panel">
          {checked !== null && (
            <div className={`feedback ${checked ? "ok" : "miss"}`}>
              {checked
                ? `一致：「${typed.trim()}」`
                : `入力：「${typed.trim() || "未入力"}」`}
            </div>
          )}

          <p className="answer-main">{presentation.answerPrimary}</p>
          {presentation.answerSecondary && (
            <p className="answer-sub">{presentation.answerSecondary}</p>
          )}

          {presentation.exampleEn && (
            <div className="example-box">
              <div>{presentation.exampleEn}</div>
              {presentation.exampleJa && (
                <div className="example-ja">{presentation.exampleJa}</div>
              )}
            </div>
          )}

          <div className="badge-row" style={{ marginTop: 8 }}>
            {term.categories.map((cat) => (
              <span key={cat} className="badge">
                {formatCategoryJa(cat)}
              </span>
            ))}
            {term.metrics.document_frequency !== null && (
              <span className="badge">
                出現文書数 {term.metrics.document_frequency}
              </span>
            )}
          </div>

          {term.collocations.length > 0 && (
            <p className="prompt-sub" style={{ marginTop: 10, marginBottom: 0 }}>
              よく使う組み合わせ：{term.collocations.slice(0, 4).join(" · ")}
            </p>
          )}

          <div className="rating-grid" role="group" aria-label="記憶度評価">
            {RATINGS.map(({ grade, label, keyHint }) => (
              <button
                key={grade}
                type="button"
                className={`rate-btn ${grade}`}
                onClick={() => onGrade(grade)}
              >
                <span>
                  {label} ({keyHint})
                </span>
                <span className="interval">{previews[grade].intervalLabel}</span>
              </button>
            ))}
          </div>
          <div className="shortcut-hint">
            ショートカット: Space 答え表示 ・ 1 もう一度 ・ 2 難しい ・ 3 普通 ・ 4 簡単
          </div>
        </div>
      )}
    </section>
  );
}
