import type { StudyMode, VocabularyTerm } from "./schema";

export interface CardPresentation {
  effectiveMode: StudyMode;
  fallbackFromCloze: boolean;
  promptLabel: string;
  promptPrimary: string;
  promptSecondary: string | null;
  expectedAnswers: string[];
  answerPrimary: string;
  answerSecondary: string | null;
  exampleEn: string | null;
  exampleJa: string | null;
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Derive a cloze pair on the fly if the dataset record omits a precomputed cloze. */
export function resolveCloze(
  term: VocabularyTerm,
): { prompt: string; answer: string } | null {
  if (term.cloze && term.cloze.prompt && term.cloze.answer) {
    return term.cloze;
  }
  const ex0 = term.examples[0]?.text;
  if (!ex0) return null;
  const cands = Array.from(
    new Set(
      [term.lemma, term.term, ...term.forms]
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    ),
  ).sort((a, b) => b.length - a.length || a.localeCompare(b));
  if (cands.length === 0) return null;
  const re = new RegExp(`\\b(${cands.map(escapeRegex).join("|")})\\b`, "i");
  const match = re.exec(ex0);
  if (!match) return null;
  return {
    prompt: `${ex0.slice(0, match.index)}____${ex0.slice(match.index + match[0].length)}`,
    answer: match[1],
  };
}

export function buildCardPresentation(
  term: VocabularyTerm,
  requestedMode: StudyMode,
): CardPresentation {
  const ex0 = term.examples[0] ?? null;
  const cloze = resolveCloze(term);

  if (requestedMode === "cloze") {
    if (cloze) {
      return {
        effectiveMode: "cloze",
        fallbackFromCloze: false,
        promptLabel: "Cloze — 空欄に入る英単語を想起",
        promptPrimary: cloze.prompt,
        promptSecondary: ex0?.ja ?? term.ja.software_gloss ?? term.ja.gloss,
        expectedAnswers: Array.from(
          new Set([cloze.answer, term.term, term.lemma, ...term.forms]),
        ),
        answerPrimary: cloze.answer,
        answerSecondary: `${term.ja.software_gloss || term.ja.gloss}（${term.term} / ${term.pos}）`,
        exampleEn: ex0?.text ?? null,
        exampleJa: ex0?.ja ?? null,
      };
    }
    // Graceful fallback when a record has no cloze match (e.g. shorthand abbreviation).
    return {
      effectiveMode: "recognition",
      fallbackFromCloze: true,
      promptLabel: "Recognition（cloze 未対応のため切替）",
      promptPrimary: term.term,
      promptSecondary: term.collocations.slice(0, 3).join(" · ") || null,
      expectedAnswers: [],
      answerPrimary: term.ja.software_gloss || term.ja.gloss,
      answerSecondary:
        term.ja.gloss && term.ja.gloss !== term.ja.software_gloss
          ? `一般訳: ${term.ja.gloss}`
          : null,
      exampleEn: ex0?.text ?? null,
      exampleJa: ex0?.ja ?? null,
    };
  }

  if (requestedMode === "active-recall") {
    return {
      effectiveMode: "active-recall",
      fallbackFromCloze: false,
      promptLabel: "Active Recall — 日本語から英語を想起",
      promptPrimary: term.ja.software_gloss || term.ja.gloss,
      promptSecondary:
        term.ja.gloss && term.ja.gloss !== term.ja.software_gloss
          ? `一般訳: ${term.ja.gloss}`
          : null,
      expectedAnswers: Array.from(new Set([term.term, term.lemma, ...term.forms])),
      answerPrimary: term.term,
      answerSecondary: term.collocations.slice(0, 3).join(" · ") || null,
      exampleEn: ex0?.text ?? null,
      exampleJa: ex0?.ja ?? null,
    };
  }

  return {
    effectiveMode: "recognition",
    fallbackFromCloze: false,
    promptLabel: "Recognition — 英語から意味を想起",
    promptPrimary: term.term,
    promptSecondary: term.collocations.slice(0, 3).join(" · ") || null,
    expectedAnswers: [],
    answerPrimary: term.ja.software_gloss || term.ja.gloss,
    answerSecondary:
      term.ja.gloss && term.ja.gloss !== term.ja.software_gloss
        ? `一般訳: ${term.ja.gloss}`
        : null,
    exampleEn: ex0?.text ?? null,
    exampleJa: ex0?.ja ?? null,
  };
}

export function checkTypedAnswer(
  input: string,
  expectedAnswers: readonly string[],
): boolean {
  const normalized = input.trim().toLowerCase();
  if (!normalized) return false;
  return expectedAnswers.some((ans) => ans.trim().toLowerCase() === normalized);
}
