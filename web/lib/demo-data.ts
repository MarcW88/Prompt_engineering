import type { PromptRecord } from "./types";

export const promptRecords: PromptRecord[] = [
  { id: "P-024", prompt: "Quelles chaussures de trail choisir pour débuter sur terrain humide ?", provenance: "reverse_engineered", confidence: 92, status: "validated", engine: "chatgpt", fanOuts: 6, citations: 8, stability: 87 },
  { id: "P-023", prompt: "Quel vélo électrique convient le mieux aux trajets quotidiens en ville ?", provenance: "observed", confidence: 100, status: "validated", engine: "perplexity", fanOuts: 5, citations: 11, stability: 91 },
  { id: "P-022", prompt: "Comment choisir une tente légère pour une randonnée de plusieurs jours ?", provenance: "reverse_engineered", confidence: 84, status: "testing", engine: "gemini", fanOuts: 7, citations: 6, stability: 72 },
  { id: "P-021", prompt: "Quels critères regarder avant d'acheter un tapis de course compact ?", provenance: "observed", confidence: 100, status: "validated", engine: "chatgpt", fanOuts: 4, citations: 7, stability: 89 },
  { id: "P-020", prompt: "Peux-tu comparer les principaux types de montres GPS pour le running ?", provenance: "synthetic", confidence: 48, status: "draft", engine: "google_ai_mode", fanOuts: 0, citations: 0, stability: 0 },
];

export const chartData = [
  { date: "24 sept.", prompts: 126, stable: 74 },
  { date: "25 sept.", prompts: 168, stable: 78 },
  { date: "26 sept.", prompts: 224, stable: 76 },
  { date: "27 sept.", prompts: 286, stable: 81 },
  { date: "28 sept.", prompts: 342, stable: 83 },
  { date: "29 sept.", prompts: 416, stable: 86 },
  { date: "30 sept.", prompts: 487, stable: 88 },
];
