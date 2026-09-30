export interface DatasetBuildInput {
  projectId: string;
  name: string;
  targetSize: number;
  repetitions: number;
  candidatesPerCluster: number;
  engines: string[];
  personas: string[];
  stages: string[];
  specificityLevels: number[];
  qualityThreshold: number;
}

export function estimateDatasetExecutions(input: Pick<DatasetBuildInput, "targetSize" | "repetitions" | "engines">) {
  return input.targetSize * input.repetitions * input.engines.length;
}
