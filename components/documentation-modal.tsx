import { ArrowRight, CircleDollarSign, Database, FileSearch, FlaskConical, Layers3, ShieldCheck, Sparkles, X } from "lucide-react";

const sections = [
  {
    icon: Database,
    title: "1. Collecter les signaux réels",
    text: "Ajoutez des mots-clés, thèmes, marques, concurrents ou problèmes utilisateurs. Choisissez Reddit, forums, SERP/PAA, Trustpilot ou importez un export Google Search Console. Un budget de collecte limite le nombre de requêtes payantes.",
  },
  {
    icon: Layers3,
    title: "2. Transformer puis regrouper",
    text: "Le workflow transforme les signaux en questions normalisées, retire les doublons, puis les regroupe en clusters sémantiques. Ces clusters représentent des besoins utilisateurs observés.",
  },
  {
    icon: FlaskConical,
    title: "3. Construire le dataset",
    text: "Le Dataset Builder sélectionne un échantillon contrôlé de prompts dans les clusters. L'échantillon exécuté définit le nombre de prompts réellement envoyés aux moteurs.",
  },
  {
    icon: Sparkles,
    title: "4. Observer les moteurs",
    text: "Bright Data exécute les prompts dans ChatGPT, Perplexity ou Gemini et conserve réponses, citations et sources. OpenAI web search complète les fan-outs utilisés pour le reverse engineering.",
  },
  {
    icon: FileSearch,
    title: "5. Valider puis reconstruire",
    text: "Les runs répétés mesurent stabilité, reproduction et qualité. Le reverse engineering utilise les fan-outs observés pour proposer de nouvelles formulations de prompts.",
  },
  {
    icon: ShieldCheck,
    title: "6. Approuver avant export",
    text: "La revue manuelle est volontaire : elle évite d'exporter des candidats instables ou artificiels. Seuls les exemples acceptés automatiquement et approuvés manuellement entrent dans l'export Semactic.",
  },
  {
    icon: CircleDollarSign,
    title: "7. Lire les coûts",
    text: "Coût confirmé signifie montant fourni ou rapproché. Usage only signifie consommation mesurée sans montant encore disponible. Pending indique que le fournisseur n'a pas encore publié la facturation finale.",
  },
];

export function DocumentationModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal docs-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className="eyebrow">DOCUMENTATION</span>
            <h2>Workflow de bout en bout</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <div className="docs-intro">
          <strong>Parcours recommandé</strong>
          <p>Seeds → collecte réelle → questions → clusters → dataset contrôlé → exécution moteurs → validation répétée → reverse engineering → revue manuelle → export Semactic.</p>
          <p className="docs-note">Le bouton « Tester un prompt » est un outil de diagnostic isolé. Il ne remplace pas le workflow fondé sur les signaux réels.</p>
        </div>
        <div className="docs-grid">
          {sections.map(({ icon: Icon, title, text }) => (
            <article key={title}>
              <div><Icon size={18} /><h3>{title}</h3></div>
              <p>{text}</p>
            </article>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="primary" onClick={onClose}>Compris <ArrowRight size={16} /></button>
        </div>
      </section>
    </div>
  );
}
