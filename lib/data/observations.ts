type ObservationLike = {
  answer?: unknown;
  raw_response?: unknown;
  provider?: unknown;
};

// Contrat d'admission unique pour le corpus d'apprentissage, la sélection de
// cibles UI et le worker de reconstruction : réponse non vide, pas d'erreur
// provider, et exécution Bright Data (les fan-outs corpus sont source=brightdata).
export function isEligibleObservation(observation: ObservationLike): boolean {
  const answer = typeof observation.answer === "string" ? observation.answer.trim() : "";
  if (!answer) return false;
  const raw = observation.raw_response;
  if (raw && typeof raw === "object" && (raw as Record<string, unknown>).error) return false;
  return String(observation.provider ?? "") === "brightdata";
}
