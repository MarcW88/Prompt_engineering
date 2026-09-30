export interface DatasetBuildInput {
  projectId: string;
  name: string;
  candidatePoolSize: number;
  executionSampleSize: number;
  repetitions: number;
  candidatesPerCluster: number;
  engines: string[];
  personas: string[];
  stages: string[];
  specificityLevels: number[];
  qualityThreshold: number;
  costPerExecutionEur: number;
  maxBudgetEur: number;
}

export function estimateDatasetExecutions(input: Pick<DatasetBuildInput, "executionSampleSize" | "repetitions" | "engines">) {
  return input.executionSampleSize * input.repetitions * input.engines.length;
}
