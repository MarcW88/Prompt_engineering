"use client";

import { useEffect, useState } from "react";
import { CircleDollarSign, X } from "lucide-react";

type CostRow = { id: string; provider: string; category: string; amount: number | null; currency: string; quantity: number | null; unit: string | null; cost_status: string; occurred_at: string };
type CostData = { confirmedTotal: number; currency: string; byProvider: Record<string, { confirmed: number; entries: number; pending: number }>; costs: CostRow[] };

export function CostsModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [data, setData] = useState<CostData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!projectId) return;
    fetch(`/api/costs?projectId=${encodeURIComponent(projectId)}`).then(async (response) => {
      const value = await response.json();
      if (!response.ok) throw new Error(value.error ?? "Chargement impossible.");
      return value;
    }).then(setData).catch((reason) => setError(reason instanceof Error ? reason.message : "Chargement impossible."));
  }, [projectId]);
  return <div className="modal-backdrop" onMouseDown={onClose}><div className="modal costs-modal" onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">FACTURATION FOURNISSEURS</span><h2>Coûts réellement confirmés</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div>{error && <p className="form-error">{error}</p>}{data && <><div className="cost-total"><CircleDollarSign size={22} /><div><strong>${data.confirmedTotal.toFixed(4)}</strong><span>sous-total confirmé par les APIs de facturation</span></div></div><div className="cost-providers">{Object.entries(data.byProvider).map(([provider, summary]) => <article key={provider}><span>{provider}</span><strong>${summary.confirmed.toFixed(4)}</strong><small>{summary.pending ? `${summary.pending} coût(s) en attente de rapprochement` : "Coût rapproché"}</small></article>)}</div><div className="cost-ledger">{data.costs.map((row) => <div key={row.id}><span className="cost-provider">{row.provider}</span><div><strong>{row.category}</strong><small>{row.quantity ?? "—"} {row.unit ?? ""} · {new Date(row.occurred_at).toLocaleString("fr-BE")}</small></div><span className={`cost-status ${row.cost_status}`}>{row.amount === null ? row.cost_status.replaceAll("_", " ") : `$${Number(row.amount).toFixed(6)}`}</span></div>)}</div><p className="cost-disclaimer">Le total confirmé n’inclut jamais un montant estimé. OpenAI nécessite une clé Admin pour exposer ses coûts facturés ; son usage reste marqué en attente jusque-là. Google Cloud publie ses coûts avec délai.</p></>}</div></div>;
}
