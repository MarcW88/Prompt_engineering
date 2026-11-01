type ObservationLike = {
  answer?: unknown;
  raw_response?: unknown;
  provider?: unknown;
};

// Sources de fan-outs admises : uniquement des requêtes rapportées par un
// provider (Bright Data dans la réponse moteur, ou fallback OpenAI web search
// quand Bright Data n'expose pas les requêtes). Jamais de requêtes dérivées
// des mots-clés du prompt ou saisies manuellement.
export const OBSERVED_FAN_OUT_SOURCES = ["brightdata", "openai_responses_web_search"];

export function observedFanOutSourceFilter(): string {
  return `source=in.(${OBSERVED_FAN_OUT_SOURCES.join(",")})`;
}

// Contrat d'admission unique pour le corpus d'apprentissage, la sélection de
// cibles UI et le worker de reconstruction : réponse non vide, pas d'erreur
// provider, et exécution Bright Data.
export function isEligibleObservation(observation: ObservationLike): boolean {
  const answer = typeof observation.answer === "string" ? observation.answer.trim() : "";
  if (!answer) return false;
  const raw = observation.raw_response;
  if (raw && typeof raw === "object" && (raw as Record<string, unknown>).error) return false;
  return String(observation.provider ?? "") === "brightdata";
}
