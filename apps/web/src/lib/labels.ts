import type { PartOfSpeech } from "./schema";

const POS_LABELS_JA: Record<string, string> = {
  noun: "名詞",
  verb: "動詞",
  adjective: "形容詞",
  adverb: "副詞",
  phrase: "フレーズ",
  other: "その他",
};

const CATEGORY_LABELS_JA: Record<string, string> = {
  core: "基本",
  frontend: "フロントエンド",
  backend: "バックエンド",
  database: "データベース",
  git: "Git",
  cloud: "クラウド",
  security: "セキュリティ",
  testing: "テスト",
  documentation: "ドキュメント",
  architecture: "設計",
  ai: "AI",
  agentic: "エージェント",
  cache: "キャッシュ",
  "llm-native-candidate": "LLM頻出候補",
};

const QUEUE_KIND_LABELS_JA: Record<"review" | "learning" | "new", string> = {
  review: "復習",
  learning: "学習中",
  new: "新規",
};

export function formatPosJa(pos: PartOfSpeech): string {
  return POS_LABELS_JA[pos] ?? pos;
}

export function formatCategoryJa(category: string): string {
  return CATEGORY_LABELS_JA[category] ?? category;
}

export function formatQueueKindJa(kind: "review" | "learning" | "new"): string {
  return QUEUE_KIND_LABELS_JA[kind];
}
