export type Provider = "brightdata" | "oxylabs";
export type Engine = "chatgpt" | "perplexity" | "gemini" | "google_ai_mode";
export type Provenance = "observed" | "reverse_engineered" | "synthetic";

export interface Citation {
  url: string;
  title: string;
}

export interface Observation {
  id: string;
  prompt: string;
  provider: Provider;
  engine: Engine;
  answer: string;
  fanOuts: string[];
  citations: Citation[];
  model: string;
  timestamp: string;
}

export interface PromptRecord {
  id: string;
  prompt: string;
  provenance: Provenance;
  confidence: number;
  status: "validated" | "testing" | "draft";
  engine: Engine;
  fanOuts: number;
  citations: number;
  stability: number;
}
