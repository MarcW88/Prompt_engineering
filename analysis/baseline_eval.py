"""§8 — Baseline comparison for prompt reconstruction.

A reproducible, offline runner: for every held-out target, compare the ICL
reconstruction candidates against a simple baseline — the nearest admissible
corpus example — under identical rules (same corpus, same exclusions, same
reproduction metric). No paid calls: the runner evaluates candidates that
were already executed, and reports "not evaluated" honestly for those that
were not.

Parameters and thresholds are fixed before evaluation; they are never
lowered to obtain a validation.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from analysis.reconstruction import ReconstructionExample
from analysis.signatures import build_signature, signature_similarity

# Conventions versionnées — fixées avant évaluation.
REPRODUCTION_THRESHOLD = 0.65
HOLDOUT_SIMILARITY = 0.8  # quasi-variants are excluded, same rule as ICL
MIN_RUNS_FOR_STABILITY = 3


@dataclass(frozen=True)
class HeldOutTarget:
    """A held-out target: its observed same-run searches and, for each
    candidate method, the candidate prompts plus the searches those
    candidates actually produced on the same surface (may be absent)."""
    target_id: str
    observed_queries: List[str]
    icl_candidates: List[Dict]          # {"prompt": str, "observed_queries": [str]|None}
    baseline_candidates: List[Dict]


def nearest_baseline(observed_queries: Sequence[str], examples: Sequence[ReconstructionExample],
                     target_prompt: str = "", exclude_similarity: float = HOLDOUT_SIMILARITY) -> Optional[str]:
    """Simple baseline: return the prompt of the admissible example whose
    observed searches are closest to the target's, excluding the target
    prompt and its quasi-variants (identical leakage rules as the ICL path)."""
    target_signature = build_signature(list(observed_queries))
    holdout_signature = build_signature([target_prompt]) if target_prompt else None
    best_score, best_prompt = -1.0, None
    for example in examples:
        if holdout_signature and signature_similarity(holdout_signature, build_signature([example.prompt])) >= exclude_similarity:
            continue
        score = signature_similarity(target_signature, build_signature(example.fan_outs))
        if score > best_score:
            best_score, best_prompt = score, example.prompt
    return best_prompt


def _reproduction(expected: Sequence[str], observed: Optional[Sequence[str]]) -> Optional[float]:
    if not observed:
        return None
    return round(signature_similarity(build_signature(list(expected)), build_signature(list(observed))), 4)


def evaluate_held_out(targets: Sequence[HeldOutTarget], threshold: float = REPRODUCTION_THRESHOLD) -> Dict:
    """Compare ICL vs baseline on the same held-out set and identical rules."""
    rows = []
    for target in targets:
        icl_scores = [_reproduction(target.observed_queries, c.get("observed_queries")) for c in target.icl_candidates]
        baseline_scores = [_reproduction(target.observed_queries, c.get("observed_queries")) for c in target.baseline_candidates]
        rows.append({
            "target_id": target.target_id,
            "icl_best": max((s for s in icl_scores if s is not None), default=None),
            "icl_evaluated": sum(1 for s in icl_scores if s is not None),
            "baseline_best": max((s for s in baseline_scores if s is not None), default=None),
            "baseline_evaluated": sum(1 for s in baseline_scores if s is not None),
        })
    def _mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None
    icl_best = [row["icl_best"] for row in rows]
    baseline_best = [row["baseline_best"] for row in rows]
    both = [row for row in rows if row["icl_best"] is not None and row["baseline_best"] is not None]
    return {
        "parameters": {"reproduction_threshold": threshold, "holdout_similarity": HOLDOUT_SIMILARITY,
                       "min_runs_for_stability": MIN_RUNS_FOR_STABILITY},
        "targets_total": len(rows),
        "icl_evaluable": sum(1 for s in icl_best if s is not None),
        "baseline_evaluable": sum(1 for s in baseline_best if s is not None),
        "paired_evaluable": len(both),
        "icl_mean_best": _mean(icl_best),
        "baseline_mean_best": _mean(baseline_best),
        "icl_reproduced": sum(1 for s in icl_best if s is not None and s >= threshold),
        "baseline_reproduced": sum(1 for s in baseline_best if s is not None and s >= threshold),
        "icl_beats_baseline": sum(1 for row in both if row["icl_best"] > row["baseline_best"]),
        "baseline_beats_icl": sum(1 for row in both if row["baseline_best"] > row["icl_best"]),
        "ties": sum(1 for row in both if row["baseline_best"] == row["icl_best"]),
        "per_target": rows,
        "limits": [
            "Évaluation hors ligne sur exécutions déjà stockées ; les candidats non exécutés sont exclus du calcul, pas notés zéro.",
            "Un candidat reconstruit est une hypothèse compatible avec les traces, pas la preuve du prompt exact.",
            "Les seuils sont des conventions fixées avant évaluation, non calibrées statistiquement.",
        ],
    }
