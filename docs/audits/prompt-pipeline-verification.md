# Audit réel du pipeline Prompt Engineering / GEO — 1 novembre 2026

**Verdict : PAS ENCORE PRÊT POUR PILOTE CLIENT.**

Base inspectée : `main`, SHA `c4824d209e451d4aed789b4621d33f5fb636c090`.
Branche : `audit/prompt-pipeline-verification`. Aucune fusion ni aucun déploiement.
Le SHA final est celui du commit qui contient ce rapport (ne pas insérer un SHA autoréférentiel).

## Périmètre et chemin réellement exécuté

Arborescence Git complète inventoriée (arbre `1ea344f63704d766ae1618bcdd13385e5576232a`, non tronqué), puis checkout local de ce SHA.

- Collecte : `app/api/jobs/collect/route.ts` → `lib/data/jobs.ts` → `lib/cloud-run.ts` → `collection_worker.py:run_once` → `_collect`.
- Traitement : `app/api/pipeline/route.ts` → jobs `transform_signals`, `cluster_questions`, `reverse_engineer`.
- Dataset : `app/api/datasets/build/route.ts` / `validate/route.ts` → `_build_dataset` / `_validate_dataset`.
- Reddit : `scrapers/forum_scraper.py` → `scrapers/arctic_shift.py`, fallback JSON public.
- Forums : `sources/discovery.py`, `sources/query_planner.py`, `scrapers/extractors.py`.
- SERP : `scrapers/serp_scraper.py`. Avis : `scrapers/review_scraper.py`. Social : `scrapers/social_scraper.py`.
- Analyse : `analysis/providers/*`, `analysis/models.py`, `analysis/dataset_builder.py`, `dataset_funnel.py`, `dataset_quality.py`, `validation.py`, `signatures.py`, `icl_reconstruction.py`, `reconstruction.py`.
- Stockage cloud : appels REST Supabase dans le worker + `supabase/migrations/*`. Le stockage SQLite `storage/*` et `analysis/workflow.py` constituent un chemin CLI distinct ; leur présence ne prouve pas leur utilisation par le worker.
- Analyse manuelle : `app/api/analyze/route.ts` contient un deuxième parser, corrigé et testé séparément.
- Reconstruction manuelle : `app/api/reconstruct/route.ts` reste un aperçu déterministe ; avertissement explicite ajouté, aucune prétention de validation.
- Configuration : `utils/config_loader.py`, `.env.example`, `config/decathlon.yaml`, `config/_template.yaml`, `Dockerfile`, `requirements.txt`.
- Tests : suite `tests/test_*.py`, nouveaux tests adaptateurs + smoke worker, test Node du parser de production TypeScript.

## Résultats

| Recommandation | État avant audit | Correction effectuée | État après audit | Test associé | Bloquant pilote client |
|---|---|---|---|---|---|
| Reddit Arctic Shift → posts/commentaires → JSON public | ⚠️ Appelé réellement ; posts sans signal_kind explicite, provenance JSON absente, bornes temporelles non transmises | Provenance/type post ajoutés, bornes Arctic et time_filter JSON transmis, options job documentées | ⚠️ Cascade testée ; fallback JSON reste limité aux posts et périodes Reddit prédéfinies, pas de récupération de commentaires JSON ni garantie de bornes exactes | `test_arctic_request_period_and_failure`, `test_reddit_posts_comments_and_json_fallback` | Non pour périmètre Reddit explicite ; oui si commentaires garantis requis |
| Reddit hors Bright Data | ✅ Worker le dirige vers ForumScraper ; datasets SocialScraper limités aux 4 plateformes | Nettoyage env et bloc social Reddit inutilisé | ✅ Pipeline normal confirmé | Inspection `_collect`, `SocialScraper.dataset_env`, smoke | Non |
| Discovery SearXNG → DataForSEO | ❌ `if results or available is False` court-circuitait le fallback en panne | Retour anticipé uniquement avec résultats utiles | ✅ Tests erreurs/indisponibilité/vide et succès | `test_discovery_fallback_on_error_empty_and_unavailable` | Non |
| Forums : forumscraper → Trafilatura → BS4 | ❌ `Outputs.data` absent, donc pas de données thread en mémoire ; Trafilatura vide abandonnait BS4 | Activation sortie mémoire, fallback BS4 sur extraction vide | ⚠️ Posts individuels conservés ; provenance BS4 encore étiquetée trafilatura par wrapper ; moteurs réels non testés en réseau | `test_extractor_requests_in_memory_data`, `test_forum_content_keeps_individual_posts`, `test_trafilatura_empty_reaches_bs4` | Non si forums statiques validés avant pilote |
| Crawl4AI | ❌ Absent | Aucun ajout, conformément au périmètre | ❌ Pages dynamiques non couvertes | Inspection dépendances et appels | Selon les forums choisis |
| PAA et Autocomplete indépendants | ❌ Suggestions gratuites bloquaient fallback PAA | Fallback indépendant de chaque catégorie | ✅ Cas 0 PAA + 5 suggestions testé ; déduplication et types existants conservés | `test_paa_fallback_independent_of_five_suggestions` | Non |
| Google Maps scraper | ⚠️ Appelé avec lancement/polling/RawItem ; config encore Places API ; auth API absente | Config queries/method corrigée ; X-API-Key et statuts 201/202 ; source_config.google_maps_queries pour worker neutre | ⚠️ Contrat simulé testé et comparé à l’exemple officiel ; instance/version, extra_reviews et résultats réels non validés | `test_maps_launch_poll_filter_rawitem` | Oui si Google Reviews inclus |
| Trustpilot structured → DataForSEO → HTML | ❌ NEXT_DATA seulement malgré doc JSON-LD ; réponse vide payante bloquait HTML | JSON-LD ajouté, parsing notes protégé, provider conservé, HTML après fallback payant vide | ⚠️ NEXT_DATA testé ; variantes JSON-LD et HTML réseau non exhaustives | `test_trustpilot_structured_and_html_after_paid_failure`, test DataForSEO existant | Non si source testée avant pilote |
| Social Facebook/Instagram/LinkedIn/X | ⚠️ Mapping datasets et gestion erreurs présents, limites volume présentes | Aucun changement de logique fournisseur ; retrait reliquat Reddit | ⚠️ Limites de volume ≠ plafond financier ; datasets réels et commentaires dépendent des IDs configurés | Inspection run, dataset_env, `_collect_comment_items`, `_record_to_item` | Oui pour pilote payant sans suivi/plafond explicite |
| Tous les blocs fan-outs Bright Data | ❌ Premier bloc seulement ; flat lookup empêchait exploration complémentaire | Traversée de tous les blocs reconnus, chaînes et objets, déduplication ; Python et route manuelle TS | ✅ Formats et blocs multiples vérifiés sur fixtures | `test_all_nested_fanout_blocks`, `tests/fanout_parser.test.mjs` | Non |
| Dataset réel prompt ↔ fan-outs | ⚠️ Exécution et relation prompt→observation→fan_outs existent ; expected_fan_outs est une hypothèse dérivée des questions ; score peut accepter une réponse sans fan-outs | ICL limité aux exemples acceptés ayant des fan-outs Bright Data persistés ; contrôle projet dataset/job | ⚠️ Dataset général accepte toujours answer-only ; export CSV n’inclut pas les fan-outs et peut exporter edited_prompt_text non exécuté | Smoke `_build_dataset`, inspections score/export, tests dataset existants | Oui pour livraison d’un corpus d’apprentissage propre |
| Entrée du reverse engineering | ❌ representative_question + questions passées comme fan-outs | Seulement target_observation_ids du projet, requêtes persistées source brightdata ; pas de substitution questions | ✅ Chemins A génération utilisateur et B reconstruction observée distincts ; original cible exclu du contexte | `test_worker_observed_target_reconstruction_execution_and_persistence`, smoke | Non côté worker ; UI encore bloquante |
| Retrieval ICL sémantique | ❌ Jaccard/signatures seuls | Embeddings cosine dominant 95%, lexical 5%, cache, 12 exemples contexte par défaut | ⚠️ Embeddings testé ; repli lexical averti en cas d’erreur ; grands corpus non batchés/paginés | `test_semantic_retrieval_beats_lexical_and_caches` | Non pour petit corpus contrôlé |
| Absence clé OpenAI / échec ICL | ❌ Repli templates silencieux | Avertissement de classe ; worker refuse absence clé et résultat non ICL ; aperçu API explicitement non validé | ✅ Aucun faux succès ICL dans job worker | `test_icl_fallback_is_visible`, inspection garde worker | Non |
| Validation des reconstruits par exécution | ❌ Brouillons seulement | Provider exécuté pour chaque candidat, observation/fan-outs persistés, scoring existant réutilisé, suivi coûts pending ; 3–5 candidats demandés, 1–4 runs, plafond exécutions obligatoire | ⚠️ Fonctionne sous mocks ; draft après un seul run, validated après ≥3 runs et seuils reproduction/stabilité ; pas encore de sélection adaptative des meilleurs ni réservation financière atomique | Test worker, smoke avec 3 runs et reproduction 1.0 | Oui pour autonomie payante client |
| Isolation client | ❌ Chargement Decathlon puis overrides partiels | Config cloud neutre depuis projet, sources explicitement sélectionnées ; contrôle ownership dataset et observations cibles | ✅ Plus d’héritage forums/Trustpilot/subreddits Decathlon en job cloud ; CLI YAML conservée | `test_neutral_configs_do_not_share_sources_or_client_defaults`, smoke avec chemin Decathlon hostile | Non pour héritage config ; audit auth/RLS hors périmètre |
| Interface / déclenchement bout en bout | ❌ API manuelle templates ; worker ICL mal alimenté | Route pipeline exige cibles et plafond ; route manuelle expose avertissement | ⚠️ UI actuelle ne fournit pas les nouveaux paramètres ; job possible via API structurée seulement | Typecheck, inspection composants et routes | Oui pour pilote via interface |
| Tests et mini pipeline | ⚠️ 33 tests, 1 échec reproductible lié à un test Trustpilot qui faisait un vrai fetch Session | Fixture hermétique ; 15 nouveaux tests Python et 2 Node | ✅ 48 Python + 2 Node réussis ; mocks explicites | Commandes ci-dessous | Non ; ne remplace pas validation infrastructure |

## Contrats et limites précises

Le contrat Google Maps a été comparé au code officiel `gosom/google-maps-scraper`, `examples/examples-api/python/scrape.py` (POST `/api/v1/scrape`, `X-API-Key`, polling GET `/api/v1/jobs/{job_id}`, `status=completed`, `results`). Cela ne prouve ni l’installation de cette version chez le client ni l’activation des avis.

L’extraction secondaire OpenAI lorsque Bright Data ne fournit pas de fan-outs reste présente pour les datasets généraux et est marquée `openai_responses_web_search`. Ce sont les recherches d’une autre exécution/moteur ; elles sont désormais exclues de l’apprentissage et des cibles Bright Data de reconstruction. Ne pas les présenter comme traces ChatGPT/Gemini réellement capturées par Bright Data.

Les exemples sont chargés par jointure logique vers observations/fan_outs, pas par le champ expected_fan_outs du prompt. Une absence de cible ne devient jamais une question utilisateur déguisée. L’API reçoit :

```json
{
  "projectId": "UUID_DU_PROJET",
  "stage": "reverse_engineer",
  "input": {
    "target_observation_ids": ["UUID_OBSERVATION_BRIGHTDATA_DU_PROJET"],
    "max_targets": 1,
    "max_candidates_per_cluster": 3,
    "validation_runs": 3,
    "max_validation_executions": 9,
    "reproduction_threshold": 0.65
  }
}
```

Aucun appel payant réel n’a été lancé pour valider ce patch. La quantité d’exécutions est bornée ; ce n’est pas un plafond monétaire garanti. Les coûts embeddings/chat ne sont pas encore entièrement inscrits dans analysis_costs. Les requêtes Supabase larges peuvent être tronquées par la pagination serveur sur de grands corpus. La sélection des exemples n’est pas encore filtrée par engine/modèle ; les évaluations multi-moteurs doivent donc être segmentées avant pilote.

## Validation exécutée

- Base originale isolée en worktree : 33 tests, 32 réussis, 1 échec (`test_collects_trustpilot_reviews_from_dataforseo` recevait 13 avis live au lieu de sa fixture). Le test mockait requests.get alors que BaseScraper utilise Session.get ; correction du test, pas manipulation du résultat métier.
- Branche audit : `./venv/bin/python -m unittest discover -s tests -v` : **48 réussis, 0 échec**.
- `node --test tests/fanout_parser.test.mjs` : **2 réussis, 0 échec**.
- `./venv/bin/python -m compileall -q analysis storage analysis_cli.py collection_worker.py scrapers sources utils` : succès.
- `npm run typecheck` : succès.
- `npm run lint` : 0 erreur ; 2 avertissements préexistants useMemo dans components/seed-modal.tsx.
- `git diff --check` : succès.
- Pas de build déployé, pas de navigateur production, pas de migrations appliquées, pas de contrôle des secrets ou de l’état Cloud Run/Supabase.

Le smoke test appelle réellement `_collect`, `_transform_signals`, `_cluster_questions`, `_build_dataset`, `_reverse_engineer` ; seules les sources externes, embeddings/LLM et API moteur sont simulés. Une base REST mémoire conserve les liens entre objets. Résultat : 3 signaux, 1 cluster, 2 prompts exécutés et acceptés, fan-outs persistés, 1 reconstruction exécutée 3 fois et validée avec reproduction_score=1.0.

## Avant le pilote

1. Relier l’UI au choix des observations réelles et au plan de validation. Afficher explicitement génération depuis signaux / reconstruction depuis traces.
2. Fournir un export corpus observé distinct de l’export métier : prompt original exécuté, observation_id, moteur/provider/modèle, fan-outs, répétitions et statut. Ne pas substituer edited_prompt_text sans réexécution.
3. Segmenter exemples et scoring par moteur, vérifier complétude des runs et réserver les coûts de manière atomique ; inclure embeddings/chat et dépenses concurrentes.
4. Vérifier sur l’infrastructure cible SearXNG, DataForSEO, google-maps-scraper avec API key/version, Arctic Shift et datasets Bright Data ; un mini run borné par source suffit avant extension.
5. Si forums dynamiques requis : prévoir Crawl4AI dans une mission distincte. Si commentaires Reddit garantis requis : compléter le fallback JSON.
