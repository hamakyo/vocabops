export type PartOfSpeech =
  | "noun"
  | "verb"
  | "adjective"
  | "adverb"
  | "phrase"
  | "other"
  | string;

export interface VocabularyExample {
  text: string;
  kind: "curated" | "synthetic" | "corpus" | string;
  ja?: string;
}

export interface VocabularyCloze {
  prompt: string;
  answer: string;
}

export interface VocabularyMetrics {
  frequency: {
    github: number | null;
    stackoverflow: number | null;
    docs: number | null;
    llm: number | null;
  };
  document_frequency: number | null;
  se_specificity: number | null;
  llm_lift: number | null;
  model_lift: {
    claude: number | null;
    gpt: number | null;
    gemini: number | null;
  };
}

export interface VocabularyCuration {
  status: "draft" | "reviewed" | "flagged" | string;
  model?: string;
  needs_human_review?: boolean;
  human_edited?: boolean;
  validation_warnings?: string[];
  review_note?: string;
}

export interface VocabularyTerm {
  id: string;
  term: string;
  lemma: string;
  pos: PartOfSpeech;
  ja: {
    gloss: string;
    software_gloss: string;
  };
  cefr: string | null;
  categories: string[];
  forms: string[];
  collocations: string[];
  examples: VocabularyExample[];
  cloze?: VocabularyCloze | null;
  metrics: VocabularyMetrics;
  learning: {
    tier: string;
    priority: number | null;
  };
  provenance: {
    dataset_version: string;
    metric_snapshot: string | null;
    sources: string[];
  };
  curation?: VocabularyCuration;
}

export interface VocabularyDataset {
  dataset: string;
  version: string;
  snapshot_id?: string;
  status?: string;
  note?: string;
  terms: VocabularyTerm[];
}

export type Grade = "again" | "hard" | "good" | "easy";

export type StudyMode = "recognition" | "active-recall" | "cloze";

/** JSON-serializable FSRS card state keyed by stable vocabulary ID. */
export interface SerializedFsrsCard {
  due: string;
  stability: number;
  difficulty: number;
  elapsed_days: number;
  scheduled_days: number;
  learning_steps: number;
  reps: number;
  lapses: number;
  state: number;
  last_review: string | null;
}

export interface ReviewHistoryEntry {
  termId: string;
  grade: Grade;
  mode: StudyMode;
  reviewedAt: string;
  scheduledDays: number;
}

export interface ReviewStore {
  schemaVersion: 1;
  cards: Record<string, SerializedFsrsCard>;
  history: ReviewHistoryEntry[];
  settings: {
    dailyNewLimit: number;
    requestRetention: number;
  };
}
