import { ArrowLeft, CheckCircle2, Eye, Keyboard, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { buildCardPresentation, checkTypedAnswer } from "../lib/cards";
import { cn } from "../lib/cn";
import {
  formatCategoryJa,
  formatPosJa,
  formatQueueKindJa,
} from "../lib/labels";
import type { GradePreview, QueueItem } from "../lib/scheduler";
import type { Grade, StudyMode } from "../lib/schema";
import { Badge, Button, Card, ProgressBar } from "./ui/primitives";

interface StudyCardProps {
  item: QueueItem;
  remainingCount: number;
  sessionTotal: number;
  sessionCompleted: number;
  studyMode: StudyMode;
  previews: Record<Grade, GradePreview>;
  retention: number | null;
  onGrade: (grade: Grade) => void;
  onExit: () => void;
}

const RATINGS: {
  grade: Grade;
  label: string;
  keyHint: string;
  styles: string;
}[] = [
  {
    grade: "again",
    label: "もう一度",
    keyHint: "1",
    styles:
      "border-rose-200 bg-rose-50/70 text-rose-700 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300 dark:hover:bg-rose-950/70",
  },
  {
    grade: "hard",
    label: "難しい",
    keyHint: "2",
    styles:
      "border-amber-200 bg-amber-50/70 text-amber-800 hover:bg-amber-100 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-950/70",
  },
  {
    grade: "good",
    label: "普通",
    keyHint: "3",
    styles:
      "border-emerald-200 bg-emerald-50/70 text-emerald-800 hover:bg-emerald-100 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300 dark:hover:bg-emerald-950/70",
  },
  {
    grade: "easy",
    label: "簡単",
    keyHint: "4",
    styles:
      "border-sky-200 bg-sky-50/70 text-sky-800 hover:bg-sky-100 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-300 dark:hover:bg-sky-950/70",
  },
];

export function StudyCard({
  item,
  remainingCount,
  sessionTotal,
  sessionCompleted,
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
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <Button size="sm" variant="ghost" onClick={onExit} className="-ml-2">
          <ArrowLeft className="h-3.5 w-3.5" />
          今日へ戻る
        </Button>
        <div className="flex flex-1 items-center gap-3">
          <ProgressBar
            value={sessionCompleted}
            max={Math.max(sessionTotal, sessionCompleted + remainingCount)}
          />
          <span className="shrink-0 text-xs font-medium text-zinc-500 tabular-nums dark:text-zinc-400">
            残り {remainingCount} 枚
          </span>
        </div>
      </div>

      <Card className="p-5 sm:p-7" aria-label="学習カード">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="indigo">{formatQueueKindJa(item.kind)}</Badge>
            <Badge>{formatPosJa(term.pos)}</Badge>
            {term.cefr && <Badge variant="outline">{term.cefr}</Badge>}
            {term.curation?.status === "draft" && (
              <Badge variant="amber">未レビュー</Badge>
            )}
            {retention !== null && (
              <Badge variant="emerald">定着率 {Math.round(retention * 100)}%</Badge>
            )}
          </div>
          <span className="font-mono text-[11px] text-zinc-400">{term.id}</span>
        </div>

        <div className="mb-2 text-xs font-medium text-zinc-500 dark:text-zinc-400">
          {presentation.promptLabel}
        </div>
        <h2
          className={cn(
            "font-bold tracking-tight text-zinc-950 dark:text-zinc-50",
            presentation.effectiveMode === "cloze"
              ? "text-xl leading-relaxed sm:text-2xl"
              : "text-3xl leading-snug sm:text-4xl",
          )}
        >
          {presentation.promptPrimary}
        </h2>
        {presentation.promptSecondary && (
          <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
            {presentation.promptSecondary}
          </p>
        )}

        {supportsTyping && !revealed && (
          <form
            className="mt-5 flex gap-2"
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
              className="h-10 flex-1 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-sm text-zinc-900 focus:border-indigo-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            />
            <Button type="submit" className="h-10 rounded-xl px-4">
              答え合わせ
            </Button>
          </form>
        )}

        {!revealed ? (
          <Button
            variant="primary"
            size="lg"
            className="mt-6 w-full"
            onClick={() => setRevealed(true)}
          >
            <Eye className="h-4 w-4" />
            答えを見る（Space）
          </Button>
        ) : (
          <div className="mt-6 border-t border-zinc-200/80 pt-6 dark:border-zinc-800">
            {checked !== null && (
              <div
                className={cn(
                  "mb-3 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium",
                  checked
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
                    : "bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300",
                )}
              >
                {checked ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {checked
                  ? `一致：「${typed.trim()}」`
                  : `入力：「${typed.trim() || "未入力"}」`}
              </div>
            )}

            <p className="text-xl font-bold text-zinc-950 dark:text-zinc-50">
              {presentation.answerPrimary}
            </p>
            {presentation.answerSecondary && (
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                {presentation.answerSecondary}
              </p>
            )}

            {presentation.exampleEn && (
              <div className="mt-4 rounded-xl border border-zinc-200/80 bg-zinc-50/90 p-4 dark:border-zinc-800 dark:bg-zinc-950/60">
                <p className="text-sm font-medium leading-relaxed text-zinc-900 dark:text-zinc-100">
                  {presentation.exampleEn}
                </p>
                {presentation.exampleJa && (
                  <p className="mt-1.5 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                    {presentation.exampleJa}
                  </p>
                )}
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              {term.categories.map((cat) => (
                <Badge key={cat}>{formatCategoryJa(cat)}</Badge>
              ))}
              {term.metrics.document_frequency !== null && (
                <Badge variant="outline">
                  出現文書数 {term.metrics.document_frequency}
                </Badge>
              )}
            </div>

            {term.collocations.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                <span>よく使う組み合わせ:</span>
                {term.collocations.slice(0, 4).map((col) => (
                  <span
                    key={col}
                    className="rounded-md bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                  >
                    {col}
                  </span>
                ))}
              </div>
            )}

            <div
              className="mt-6 grid grid-cols-2 gap-2.5 sm:grid-cols-4"
              role="group"
              aria-label="記憶度評価"
            >
              {RATINGS.map(({ grade, label, keyHint, styles }) => (
                <button
                  key={grade}
                  type="button"
                  onClick={() => onGrade(grade)}
                  className={cn(
                    "flex min-h-15 flex-col items-center justify-center gap-0.5 rounded-xl border px-3 py-2.5 transition-colors cursor-pointer",
                    styles,
                  )}
                >
                  <span className="text-sm font-semibold">
                    {label}{" "}
                    <span className="text-[11px] opacity-70">({keyHint})</span>
                  </span>
                  <span className="text-[11px] opacity-80">
                    {previews[grade].intervalLabel}
                  </span>
                </button>
              ))}
            </div>

            <div className="mt-3 flex items-center justify-center gap-1.5 text-[11px] text-zinc-400">
              <Keyboard className="h-3 w-3" />
              <span>Space 答え表示 ・ 1 もう一度 ・ 2 難しい ・ 3 普通 ・ 4 簡単</span>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
