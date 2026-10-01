"use client";

import { useState } from "react";
import { FolderPlus, X } from "lucide-react";

interface WorkspaceModalProps {
  onClose: () => void;
  onCreated: (project: { id: string; name: string }) => void;
}

export function WorkspaceModal({ onClose, onCreated }: WorkspaceModalProps) {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("FR");
  const [language, setLanguage] = useState("fr");
  const [website, setWebsite] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    const cleanName = name.trim();
    if (!cleanName) return;
    setLoading(true);
    setStatus("Création du workspace…");
    try {
      const slug = `${cleanName.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "workspace"}-${Date.now().toString(36)}`;
      const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: cleanName, slug, website: website.trim() || null, country, language }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Création impossible.");
      const project = data.projects?.[0];
      if (!project) throw new Error("Workspace non retourné par l'API.");
      onCreated({ id: project.id, name: project.name });
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Création impossible.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="modal-head">
          <div><span className="eyebrow">ESPACE DE TRAVAIL</span><h2>Nouveau workspace</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <label>Nom<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex. Client Retail — GEO" /></label>
        <label>Site ou domaine, optionnel<input value={website} onChange={(event) => setWebsite(event.target.value)} placeholder="https://client.com" /></label>
        <div className="form-row">
          <label>Marché<select value={country} onChange={(event) => setCountry(event.target.value)}><option value="FR">France</option><option value="BE">Belgique</option><option value="NL">Pays-Bas</option><option value="DE">Allemagne</option><option value="ES">Espagne</option><option value="IT">Italie</option></select></label>
          <label>Langue<select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="fr">Français</option><option value="nl">Néerlandais</option><option value="de">Allemand</option><option value="es">Espagnol</option><option value="it">Italien</option><option value="en">Anglais</option></select></label>
        </div>
        {status && <p className="import-status">{status}</p>}
        <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Annuler</button><button className="primary" disabled={!name.trim() || loading}><FolderPlus size={17} /> {loading ? "Création…" : "Créer"}</button></div>
      </form>
    </div>
  );
}
