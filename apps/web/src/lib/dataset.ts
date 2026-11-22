import core500DraftRaw from "@data/releases/0.1.0-draft/vocabulary.json";
import sampleRaw from "@data/sample.json";
import type { VocabularyDataset } from "./schema";

export type DatasetId = "core500-draft" | "sample";

export interface DatasetOption {
  id: DatasetId;
  label: string;
  dataset: VocabularyDataset;
}

export const CORE500_DATASET = core500DraftRaw as VocabularyDataset;
export const SAMPLE_DATASET = sampleRaw as VocabularyDataset;

export const DATASETS: readonly DatasetOption[] = [
  {
    id: "core500-draft",
    label: `Core 500 (${CORE500_DATASET.version}, ${CORE500_DATASET.terms.length} entries)`,
    dataset: CORE500_DATASET,
  },
  {
    id: "sample",
    label: `Sample Schema Deck (${SAMPLE_DATASET.terms.length} entries)`,
    dataset: SAMPLE_DATASET,
  },
];

export function getDatasetById(id: DatasetId): VocabularyDataset {
  return id === "sample" ? SAMPLE_DATASET : CORE500_DATASET;
}

export function listCategories(dataset: VocabularyDataset): string[] {
  const set = new Set<string>();
  for (const term of dataset.terms) {
    for (const cat of term.categories) {
      set.add(cat);
    }
  }
  return Array.from(set).sort();
}
