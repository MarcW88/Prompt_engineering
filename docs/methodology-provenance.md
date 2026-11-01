# Matrice de provenance des méthodes et briques externes

Lot : finalisation pilote Prompt Engineering / GEO (branche `pilot/v5-finalisation`).
Chaque brique externe est documentée avec la version effectivement examinée,
son rôle dans le pipeline, son mode d'utilisation et ses limites. La simple
présence d'un dépôt dans cette liste ne vaut ni intégration ni validation.

## Briques inspectées

### Elmo — `elmohq/elmo`

- **Version examinée** : `main` @ `a781096c5555` (inspectée le 2026-11-01).
- **Fichiers examinés** : `apps/web/src/lib/fanout-analysis.ts`,
  `apps/web/src/server/query-fanout.ts`, `packages/lib/src/rollups/fanout.ts`,
  `packages/config/src/fanout-support.ts`, hooks `use-query-fanout`.
- **Rôle** : plateforme AEO/GEO complète (suivi de prompts, mentions, citations).
- **Constats repris** :
  - `prompt_runs.web_queries` est la source unique des fan-outs par run — notre
    modèle `observations` + `fan_outs` suit la même séparation.
  - Elmo exclut à la lecture (a) les requêtes identiques au prompt et (b) la
    sentinelle `"unavailable"` écrite quand le provider ne expose pas les
    requêtes réelles (OpenRouter/DataForSEO toujours ; Bright Data/Olostep en
    échec d'extraction). Notre `trace_status` (`provider_reported` /
    `independent_reexecution` / `none_reported` / `not_exposed`) rend le même
    constat côté données plutôt qu'à l'affichage.
  - Elmo confirme que les fan-outs ne sont **pas garantis** par Bright Data —
    cohérent avec notre observation terrain (`metadata.search_model_queries`
    absent des réponses ChatGPT réelles).
- **Mode d'utilisation** : référence méthodologique (séparation run/traces,
  règles d'exclusion). Aucun code repris : la brique est couplée à son schéma
  Supabase propre (tables `prompt_runs`, rollups SQL) et à son monorepo.
- **Limite** : pas de migration complète — non imposée par le brief et aucune
  brique ne résout l'absence de traces chez le provider.

### WRA — `umass-aisec/wra`

- **Version examinée** : `main` @ `bb4fccf43243` (papier arXiv 2508.20282).
- **Fichiers examinés** : `README.md`, `prompt_reconstruction/prompt_rewriting.ipynb`,
  `prompt_reconstruction/prompt_reconstruction_evaluation.ipynb` (structure),
  `data/prompts/*`, `data/traces/*`.
- **Rôle** : protocole académique de reconstruction de prompts à partir de
  **domaines visités** enregistrés au niveau réseau (traces d'agents de
  recherche), pas de query fan-outs textuels.
- **Constats repris** :
  - Séparation apprentissage/évaluation : prompts TREC (FEDWEB13, SESSION14,
    DD16) ↔ traces collectées ; notre hold-out du prompt cible et des
    quasi-variantes (similarité < 0,8) applique le même principe.
  - Réécriture guidée par instructions « maximize specificity » : notre ICL
    fait l'inverse — générer le prompt plausible qui a produit les fan-outs —
    car nos traces sont des requêtes de recherche, pas des domaines.
- **Mode d'utilisation** : méthodologie de référence uniquement (protocole
  hold-out, exigence de baseline). Aucun code repris : adaptation nécessaire
  car domaines ≠ fan-outs.
- **Limite** : leur signal d'entrée (trafic réseau) est plus faible que le
  nôtre ; les métriques du papier ne sont pas réutilisables telles quelles.

### OpenQueries — `openqueries/openqueries`

- **Version examinée** : `main` @ `672bd9a67352`.
- **Fichiers examinés** : `apps/extension/lib/extractors.ts`,
  `apps/extension/contents/chatgpt.ts`, `apps/extension/contents/google.ts`.
- **Rôle** : extension navigateur qui extrait les requêtes de recherche
  affichées dans le DOM des conversations ChatGPT/Claude/AI Overviews
  (`[data-search-query]`, `aria-label="search query"`, liens `/search?q=`).
- **Constats repris** : les sélecteurs DOM confirment que ChatGPT **affiche**
  ses requêtes de recherche à l'utilisateur — donc qu'un scrape navigateur
  pourrait les capter là où l'API Bright Data ne les expose pas.
- **Mode d'utilisation** : référence pour un futur adaptateur navigateur ;
  nécessite un accès navigateur non disponible dans ce lot (consigné dans la
  demande d'accès). Aucun code repris.
- **Limite** : traces observées ≠ estimées ; deux conversations indépendantes
  ne donnent pas nécessairement les mêmes requêtes.

### query-fanout-viewer — `LorenzoSchiff/query-fanout-viewer` **(inspecteur retenu)**

- **Version examinée** : `main` @ `268446b465cc`, clone `/tmp` du 1 nov. 2026.
- **Fichier vérifié** : `src/bookmarklet.js` (unique fichier de 46k
  caractères, bookmarklet auto-contenu).
- **Mécanisme réel vérifié** : le bookmarklet parse le payload de
  conversation ChatGPT en mémoire — lots `web.run` → `searchBatches` avec
  requêtes dédupliquées, `groups.entries` tagués `search`/`view` pour les
  résultats, `ref_id` (`turn_index`/`ref_type`) pour la corrélation
  citation-path. Pour Claude il lit les `web_search` tool uses.
- **Décision** : retenu comme inspecteur de contrôle indépendant (un seul,
  conformément au cahier des charges) — OpenQueries reste une référence.
- **Usage prévu** : QA navigateur — l'utilisateur ouvre sa conversation
  ChatGPT, lance le bookmarklet, et compare les requêtes affichées aux
  fan-outs stockés. **Limite honnête** : le contrôle est manuel et par
  conversation ; il ne garantit pas l'observabilité automatisée, et deux
  runs indépendants n'ont pas à produire les mêmes recherches.
- **Preuve** : mécanisme lu dans le source, pas seulement le README.

## Collecteurs (conservés, filiation vérifiée)

| Brique | Usage | Vérification |
|---|---|---|
| Arctic Shift (`arctic-shift.photon-reddit.com`) | posts + commentaires Reddit | Testé en live pendant le smoke : posts/comments réels ; throttling géré par retry + fallback requête large |
| forumscraper | extraction forums (phpBB, XenForo…) | Import paresseux ; test skippé sous Python < 3.10 ; prod = Python 3.12 |
| Trafilatura | extraction contenu générique | Fallback BS4 tagué `engine: "bs4"` (provenance exacte) |
| SearXNG | découverte d'URLs forums | `SEARXNG_URL` requis ; non déployé ⇒ fallback DataForSEO |
| gosom/google-maps-scraper | avis Google | `GOOGLE_MAPS_SCRAPER_URL` requis ; adaptateur présent, service non vérifié en smoke |
| DataForSEO | fallback SERP/PAA/avis | Endpoint autocomplete corrigé (`live/advanced`), testé en live |

## Choix maison (pas de source externe)

- **Sélection des formulations (mode `faithful`)** : regroupement d'intentions
  par similarité de signature lexicale + égalité des tokens de contraintes
  (budget, audience, chiffres). Seuil `intent_similarity_threshold` (défaut
  0,65) configurable par `build_config`. Choix local, pas repris d'Elmo/WRA.
- **Scores** : `pre_execution_score`, `quality_score`, `reproduction_score`
  (lexical, référence) + `semantic_reproduction_score` (complément descriptif).
  Seuils : acceptation `quality_threshold` (0,65 défaut), `validated` = ≥3 runs
  + stabilité ≥ 0,65 + reproduction ≥ seuil.
- **Provenance des traces** : `same_run` / `independent_reexecution` /
  `not_exposed` / erreur de collecte — taxonomie locale alignée sur le constat
  Elmo (traces non garanties) mais formalisée dans le schéma.
- **ICL reconstruction** : retrieval embedding + lexical, exemples segmentés
  par (moteur, surface réelle de trace), hold-out du prompt cible et des
  quasi-variantes (< 0,8). Protocole inspiré du principe hold-out WRA,
  implémentation locale.
