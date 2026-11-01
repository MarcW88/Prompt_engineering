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

// Classification honnête des traces : un fan-out Bright Data est rapporté par
// le même run ; un fan-out OpenAI provient d'une réexécution indépendante.
export function traceKind(sources: Iterable<string>): string {
  const set = new Set(sources);
  if (!set.size) return "not_exposed";
  if (set.size === 1 && set.has("brightdata")) return "provider_reported";
  if (set.size === 1 && set.has("openai_responses_web_search")) return "independent_reexecution";
  return "mixed";
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
