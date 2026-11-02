"""Dataset complet : couverture, génération par lots résumable, priorités.

Règles (cahier des charges) :
- le dataset complet n'est jamais exécuté automatiquement dans les moteurs ;
- trois provenances : observed / transformed / proposed ;
- les contenus propres de la marque servent de contexte, pas de preuve de demande ;
- arrêt sur couverture atteinte ou budget, jamais sur un chiffre artificiel ;
- chaque lot est reprisable : un lot terminé n'est ni régénéré ni refacturé ;
- la sélection des 200 priorités se fait après consolidation globale.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from analysis.elmo_adapter import build_suggest_prompt, dedupe_key, normalize_prompts
from analysis.qualification import qualify_question

MAX_BATCH_RETRIES = 2


@dataclass
class CoverageCell:
    dimension: str
    value: str
    observed: int = 0
    proposed: int = 0
    covered: bool = False


@dataclass
class Batch:
    batch_id: str
    objective: str
    dimension: str
    value: str
    count: int
    status: str = "pending"          # pending | done | failed
    attempts: int = 0
    model: str = ""
    input_version: str = ""
    produced: int = 0
    error: str = ""


def input_version(source_config: dict, questions: Sequence[dict]) -> str:
    """Empreinte des entrées : config kickoff + textes de questions existantes.
    Versionner les entrées permet de ne pas régénérer un lot sur des données
    identiques et de documenter ce qui a servi."""
    payload = json.dumps(
        {"config": {k: source_config.get(k) for k in ("themes", "competitors", "brand_variants", "domain")},
         "questions": sorted(dedupe_key(q.get("text", "")) for q in questions)},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def _provenance(q: dict) -> str:
    return (q.get("metadata") or {}).get("provenance_label") or q.get("provenance") or "observed"


def compute_coverage(questions: Sequence[dict], source_config: dict) -> List[CoverageCell]:
    """Matrice de couverture sur les dimensions réellement présentes au
    kickoff : thèmes, concurrents, famille marque. Une dimension absente du
    kickoff n'est pas inventée."""
    cells: List[CoverageCell] = []
    qualified = [(q, (q.get("metadata") or {}).get("qualification") or {}) for q in questions]
    all_themes = list(source_config.get("themes", []))
    for priority in source_config.get("priority_themes", []):
        if priority not in all_themes:
            all_themes.append(priority)
    for theme in all_themes:
        hits = [q for q, qual in qualified if qual.get("kickoff_theme") == theme and qual.get("category") in ("non_brand_kickoff", "brand", "comparaison_standard")]
        cells.append(CoverageCell("theme", theme,
                                  observed=sum(1 for q in hits if _provenance(q) != "proposed"),
                                  proposed=sum(1 for q in hits if _provenance(q) == "proposed"),
                                  covered=bool(hits)))
    comp_names = source_config.get("competitors", [])
    for competitor in comp_names:
        hits = [q for q, qual in qualified
                if qual.get("category") in ("brand", "comparaison_standard")
                and competitor.casefold() in (q.get("text") or "").casefold()]
        cells.append(CoverageCell("competitor", competitor, observed=len(hits), covered=bool(hits)))
    brand_hits = [q for q, qual in qualified if qual.get("category") == "brand"]
    cells.append(CoverageCell("family", "brand", observed=len(brand_hits), covered=bool(brand_hits)))
    comp_hits = [q for q, qual in qualified if qual.get("category") == "comparaison_standard"]
    cells.append(CoverageCell("family", "comparaison_standard", observed=len(comp_hits), covered=bool(comp_hits)))
    return cells


def plan_batches(coverage: Sequence[CoverageCell], source_config: dict, version: str,
                 min_per_theme: int = 5, max_per_batch: int = 15) -> List[Batch]:
    """Un lot par manque justifié — pas de lot sans objectif de couverture."""
    batches: List[Batch] = []
    for cell in coverage:
        total = cell.observed + cell.proposed
        if cell.dimension == "theme" and total < min_per_theme:
            want = min(max_per_batch, min_per_theme * 2 - total)
            batches.append(Batch(_batch_id(cell, version), f"couverture du thème kickoff « {cell.value} »",
                                 cell.dimension, cell.value, want, input_version=version))
        if cell.dimension == "competitor" and total == 0:
            batches.append(Batch(_batch_id(cell, version), f"comparaisons standards avec « {cell.value} »",
                                 cell.dimension, cell.value, 3, input_version=version))
        if cell.dimension == "family" and cell.value == "comparaison_standard" and total == 0:
            pass  # couvert par les lots concurrents
        if cell.dimension == "family" and cell.value == "brand" and total < 5:
            batches.append(Batch(_batch_id(cell, version), "questions de marque (avis, dosage, gamme)",
                                 cell.dimension, cell.value, 8, input_version=version))
    return batches


def _batch_id(cell: CoverageCell, version: str) -> str:
    return f"{cell.dimension}:{dedupe_key(cell.value)[:30]}"


def completed_batch_ids(questions: Sequence[dict]) -> set:
    return {(q.get("metadata") or {}).get("batch_id") for q in questions
            if (q.get("metadata") or {}).get("batch_id")}


def run_batches(batches: List[Batch], llm_fn: Callable[[str, int], Dict],
                existing_prompts: Sequence[str], completed: set) -> List[Dict]:
    """Exécute les lots restants. ``llm_fn(prompt_text, count)`` renvoie
    {"prompts": [...], "model": str, "usage": {...}} — l'appel est payant et
    n'est invoqué que pour les lots non terminés. Retries bornés, réponses
    partielles acceptées puis le lot est marqué selon son résultat réel."""
    produced: List[Dict] = []
    known = {dedupe_key(t) for t in existing_prompts}
    for batch in batches:
        if batch.batch_id in completed:
            batch.status = "done"
            continue
        batch.attempts += 1
        try:
            result = llm_fn(batch.objective, batch.count)
            batch.model = result.get("model", "")
            items = normalize_prompts(result.get("prompts", []), batch.count, existing=known)
            for item in items:
                known.add(item["prompt"])
                item["batch_id"] = batch.batch_id
                item["batch_objective"] = batch.objective
            produced.extend(items)
            batch.produced = len(items)
            batch.status = "done" if items else "failed"
            if not items:
                batch.error = "réponse vide ou 100 % doublons"
        except Exception as exc:  # retry borné
            batch.error = str(exc)
            batch.status = "failed"
            if batch.attempts < MAX_BATCH_RETRIES:
                try:
                    result = llm_fn(batch.objective, batch.count)
                    batch.model = result.get("model", "")
                    items = normalize_prompts(result.get("prompts", []), batch.count, existing=known)
                    for item in items:
                        known.add(item["prompt"])
                        item["batch_id"] = batch.batch_id
                        item["batch_objective"] = batch.objective
                    produced.extend(items)
                    batch.produced = len(items)
                    batch.status = "done" if items else "failed"
                except Exception as exc2:
                    batch.error = str(exc2)
    return produced


def proposed_rows(project_id: str, items: Sequence[Dict], source_config: dict, language: str,
                  batch_map: Dict[str, Batch]) -> List[dict]:
    """Lignes `questions` provenance=proposed : jamais présentées comme
    collectées ; qualification calculée par le même code que les observées."""
    brand_variants = [*(source_config.get("brand_variants") or [])]
    competitors = source_config.get("competitors") or []
    themes = source_config.get("themes") or []
    rows = []
    for i, item in enumerate(items):
        qual = qualify_question(item["prompt"], brand_variants, competitors, themes)
        batch = batch_map.get(item.get("batch_id", ""))
        rows.append({
            "project_id": project_id, "text": item["prompt"], "provenance": "synthetic",
            "language": language, "confidence": 0.6,
            "metadata": {
                "intent": "buyer",
                "provenance_label": "proposed",
                "batch_id": item.get("batch_id"),
                "batch_objective": item.get("batch_objective"),
                "formulation_id": f"prop:{item['batch_id']}:{i}",
                "intent_id": item.get("batch_id"),
                "generation_model": batch.model if batch else "",
                "tags": item.get("tags", []),
                "qualification": qual,
            },
        })
    return rows


def select_priorities(questions: Sequence[dict], source_config: dict, target: int = 200):
    """Sélection des N priorités après consolidation globale — même code de
    quotas que le lancement (select_with_quotas). Retourne les prompts avec
    leurs IDs, justification de sélection ou de report, déficits et arrondi.

    Justification de sélection : quota de catégorie atteint + diversité des
    thèmes ; justification de report : hors quota, hors périmètre, ou
    corporate. Aucune part égale imposée entre marque et comparaison : les
    deux familles doivent être présentes, leur répartition reflète l'offre."""
    from analysis.models import PromptCandidate, PromptProvenance
    from analysis.qualification import select_with_quotas
    from analysis.dataset_funnel import stratified_sample

    brand_variants = source_config.get("brand_variants") or []
    competitors = source_config.get("competitors") or []
    themes = source_config.get("themes") or []
    candidates = []
    for q in questions:
        meta = dict(q.get("metadata") or {})
        qual = meta.get("qualification") or qualify_question(q.get("text") or "", brand_variants, competitors, themes)
        if meta.get("intent") == "corporate":
            qual = {"category": "hors_périmètre", "kickoff_theme": "", "justification": "contenu corporate — contexte métier, pas demande acheteur"}
        meta["qualification"] = qual
        meta["question_id"] = q.get("id", "")
        meta["cluster_id"] = meta.get("intent_id") or q.get("id", "")
        meta["provenance_label"] = _provenance(q)
        candidates.append(PromptCandidate(text=q.get("text") or "", provenance=PromptProvenance.OBSERVED,
                                          source_reference=str(q.get("id", "")), metadata=meta))
    selected, deficits = select_with_quotas(candidates, target, stratified_sample, max_per_cluster=999)
    selected_ids = {c.id for c in selected}
    priorities, deferred = [], []
    for c in candidates:
        qual = c.metadata["qualification"]
        entry = {"question_id": c.metadata["question_id"], "text": c.text, "category": qual["category"],
                 "kickoff_theme": qual.get("kickoff_theme", ""), "provenance": c.metadata["provenance_label"],
                 "qualification_justification": qual.get("justification", "")}
        if c.id in selected_ids:
            entry["selection_reason"] = f"dans le quota « {qual['category']} » — diversité des thèmes préservée"
            priorities.append(entry)
        else:
            entry["defer_reason"] = ("hors périmètre" if qual["category"] == "hors_périmètre"
                                     else f"quota « {qual['category']} » atteint ou doublon de texte")
            deferred.append(entry)
    from collections import Counter
    counts = Counter(e["category"] for e in priorities)
    report = {
        "target": target, "selected": len(priorities), "counts": dict(counts),
        "deficits": deficits, "rounding": f"30 = round(0.15×{target}) ; parts marque/comparaison selon l'offre réelle, jamais imposées égales",
        "compliant": counts.get("brand", 0) > 0 and counts.get("comparaison_standard", 0) > 0
                     and counts.get("brand", 0) + counts.get("comparaison_standard", 0) <= int(round(target * 0.15)),
        "priorities": priorities, "deferred": deferred,
    }
    return report


def build_kickoff_context(source_config: dict) -> str:
    parts = []
    for key, label in (("themes", "thèmes"), ("priority_themes", "thèmes prioritaires"),
                       ("products", "produits"), ("competitors", "concurrents"),
                       ("brand_variants", "variantes de marque"), ("domain", "domaine"),
                       ("kickoff_notes", "notes")):
        values = source_config.get(key) or []
        if values:
            parts.append(f"{label}: {', '.join(values) if isinstance(values, list) else values}")
    return "\n".join(parts)


def make_llm_call(api_key: str, *, model: str = "gpt-4o-mini") -> Callable[[str, int], Dict]:
    """Appel OpenAI structuré pour la génération par lots. Payant : chaque
    appel produit une ligne analysis_costs côté appelant."""
    import requests as _requests

    def call(objective: str, count: int) -> Dict:
        prompt = (
            f"Generate {count} French buyer questions for the objective: {objective}.\n"
            'Return strict JSON {"prompts": [{"prompt": str, "tags": [str]}]}. '
            "Real phrasing people type into ChatGPT — full questions or contextualized "
            "requests accepted, no trivial paraphrases, no personas unless needed.")
        resp = _requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": 0.7,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = json.loads(data["choices"][0]["message"]["content"])
        return {"prompts": content.get("prompts", []), "model": model,
                "usage": data.get("usage", {})}
    return call
