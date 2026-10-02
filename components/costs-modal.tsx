"use client";

import { useEffect, useState } from "react";
import { CircleDollarSign, X } from "lucide-react";

type CostRow = { id: string; provider: string; category: string; amount: number | null; currency: string; quantity: number | null; unit: string | null; cost_status: string; occurred_at: string };
type CostData = { confirmedTotal: number; currency: string; byProvider: Record<string, { confirmed: number; entries: number; pending: number }>; costs: CostRow[] };
type BudgetData = { configuredTotal: number; confirmedEur: number; remainingEur: number; spentPercent: number; recommendation: { tier: string; score: number; totalEur: number; corpusTarget: [number, number]; reasons: string[]; allocations: Record<string, number> } };

export function CostsModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [data, setData] = useState<CostData | null>(null);
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [totalEur, setTotalEur] = useState(8);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!projectId) return;
    Promise.all([
      fetch(`/api/costs?projectId=${encodeURIComponent(projectId)}`).then(async (response) => { const value = await response.json(); if (!response.ok) throw new Error(value.error ?? "Chargement impossible."); return value; }),
      fetch(`/api/budget?projectId=${encodeURIComponent(projectId)}`).then(async (response) => { const value = await response.json(); if (!response.ok) throw new Error(value.error ?? "Budget indisponible."); return value; }),
    ]).then(([costData, budgetData]) => { setData(costData); setBudget(budgetData); setTotalEur(budgetData.configuredTotal); }).catch((reason) => setError(reason instanceof Error ? reason.message : "Chargement impossible."));
  }, [projectId]);
  async function saveBudget() {
    if (!projectId) return;
    const response = await fetch("/api/budget", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, totalEur, profile: { mode: "manual" } }) });
    const value = await response.json();
    if (!response.ok) { setError(value.error ?? "Mise à jour impossible."); return; }
    setBudget((current) => current ? { ...current, configuredTotal: value.totalEur, remainingEur: Math.max(0, value.totalEur - current.confirmedEur), spentPercent: Math.min(100, Math.round(current.confirmedEur / value.totalEur * 100)) } : current);
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><div className="modal costs-modal" onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">BUDGET GLOBAL</span><h2>Budget et coûts du workflow</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div>{error && <p className="form-error">{error}</p>}{budget && <><div className="cost-total"><CircleDollarSign size={22} /><div><strong>{budget.confirmedEur.toFixed(2)} € / {budget.configuredTotal.toFixed(2)} €</strong><span>{budget.remainingEur.toFixed(2)} € restant · coûts confirmés convertis en EUR</span></div></div><div className="dataset-estimate"><p><strong>Profil {budget.recommendation.tier}</strong> · score d’empreinte {budget.recommendation.score}/100 · corpus cible {budget.recommendation.corpusTarget[0].toLocaleString("fr-FR")}–{budget.recommendation.corpusTarget[1].toLocaleString("fr-FR")} signaux.</p><p>Recommandation automatique : {budget.recommendation.totalEur.toFixed(2)} € — {budget.recommendation.reasons.join(" · ")}</p></div><div className="form-row compact"><label>Plafond global (€)<input type="number" min="1" max="30" step="1" value={totalEur} onChange={(event) => setTotalEur(Number(event.target.value))} /><small>Au-delà de 30 €, segmentez l’audit.</small></label><button type="button" className="secondary" onClick={() => void saveBudget()}>Enregistrer</button></div><div className="cost-providers">{Object.entries(budget.recommendation.allocations).map(([stage, amount]) => <article key={stage}><span>{stage.replaceAll("_", " ")}</span><strong>{amount.toFixed(2)} €</strong><small>Enveloppe recommandée</small></article>)}</div></>}{data && <><div className="cost-providers">{Object.entries(data.byProvider).map(([provider, summary]) => <article key={provider}><span>{provider}</span><strong>${summary.confirmed.toFixed(4)}</strong><small>{summary.pending ? `${summary.pending} coût(s) en attente de rapprochement` : "Coût rapproché"}</small></article>)}</div><div className="cost-ledger">{data.costs.map((row) => <div key={row.id}><span className="cost-provider">{row.provider}</span><div><strong>{row.category}</strong><small>{row.quantity ?? "—"} {row.unit ?? ""} · {new Date(row.occurred_at).toLocaleString("fr-BE")}</small></div><span className={`cost-status ${row.cost_status}`}>{row.amount === null ? row.cost_status.replaceAll("_", " ") : `$${Number(row.amount).toFixed(6)}`}</span></div>)}</div><p className="cost-disclaimer">Le total confirmé n’inclut jamais un montant estimé. OpenAI nécessite une clé Admin pour exposer ses coûts facturés ; son usage reste marqué en attente jusque-là. Google Cloud publie ses coûts avec délai.</p></>}</div></div>;
}
