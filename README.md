# Prompt Lab

Prompt Lab transforme des signaux utilisateurs réels en prompts GEO, reconstruit les prompts à partir de signatures de query fan-out et valide leur stabilité sur plusieurs moteurs génératifs.

## Application Next.js

L'interface Next.js se trouve à la racine du dépôt afin que Vercel détecte un seul projet.

```bash
npm install
npm run dev
```

Vérifications de production :

```bash
npm run lint
npm run typecheck
npm run build
```

Pour Vercel, conservez la racine du dépôt comme **Root Directory** et ajoutez les variables de `.env.example` dans les paramètres du projet.

## Base de données Supabase

Le schéma de production est versionné dans `supabase/migrations/202609300001_prompt_lab.sql`. Il contient les projets, sources, signaux, questions, clusters, prompts, observations, fan-outs, citations, validations et jobs.

Variables serveur nécessaires :

```bash
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=
```

La clé secrète reste exclusivement utilisée dans les Route Handlers Next.js et ne doit jamais être exposée au navigateur.

## Backend d'analyse Python

Le backend Python contient :

- les connecteurs Bright Data et Oxylabs ;
- les modèles d'observation, de citation et de fan-out ;
- la base SQLite locale ;
- la reconstruction inverse de prompts ;
- les scores de reproduction et de stabilité.

Initialiser la base locale :

```bash
./venv/bin/python analysis_cli.py init-db
```

Importer un export Google Search Console en conservant les requêtes conversationnelles :

```bash
./venv/bin/python main.py --config config/decathlon.yaml --gsc export-gsc.csv --gsc-min-words 10
```

Exécuter les tests :

```bash
./venv/bin/python -m unittest discover -s tests -v
```

## Variables d'environnement

Copiez `.env.example` pour le développement local. Les secrets ne doivent jamais être commités.

Les principaux secrets sont :

- `BRIGHTDATA_API_KEY` et les identifiants de datasets par moteur ;
- `OXYLABS_USERNAME` et `OXYLABS_PASSWORD` ;
- `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD` ;
- `OPENAI_API_KEY` pour les étapes historiques de transformation et clustering.

## Seeds et collecte

Les mots-clés, thèmes, marques, concurrents, produits et problèmes sont normalisés en seeds avec une priorité, une langue et un marché. Reddit, les forums et les PAA utilisent le même planificateur de requêtes.

Les jobs créés par Next.js sont traités par le worker Python :

```bash
./venv/bin/python collection_worker.py --config config/decathlon.yaml --once
```

Sans `--once`, le worker traite les jobs en attente jusqu'à ce que la file soit vide. En production, il doit tourner sur un service Python séparé de Vercel.

## Dataset Builder

Le Dataset Builder construit une matrice contrôlée depuis les clusters GEO : personas, étapes du parcours et niveaux de spécificité. Il crée les prompts candidats, planifie les répétitions par moteur, collecte les fan-outs et classe chaque exemple comme accepté ou rejeté selon son score de qualité.

Le volume d'observations est calculé ainsi :

```text
prompts candidats × répétitions × moteurs
```

Le worker traite les jobs `build_dataset` avec Bright Data par défaut. Utilisez `DATASET_PROVIDER=oxylabs` pour basculer sur Oxylabs lorsque le moteur demandé est pris en charge.

## Pipeline de production

Trois jobs raccordent maintenant le workflow de bout en bout :

- `transform_signals` conserve les questions GSC/PAA observées et transforme les discussions en questions avec OpenAI ;
- `cluster_questions` calcule les embeddings, forme les clusters et sauvegarde les relations question/cluster ;
- `reverse_engineer` charge les exemples acceptés du dataset et reconstruit de nouveaux prompts pour les clusters GEO.

Le bouton **Piloter le workflow** permet de lancer ces étapes et d'en consulter l'état. L'étape de préparation des questions enchaîne automatiquement le clustering après une transformation réussie.

## Workflow

1. Import des seeds et collecte depuis GSC, Reddit, forums, avis et SERP/PAA.
2. Normalisation et regroupement des intentions.
3. Construction d'une matrice de prompts contrôlée depuis les clusters.
4. Exécution répétée via Bright Data ou Oxylabs.
5. Collecte des fan-outs, citations et réponses.
6. Scoring de couverture, reproduction, stabilité et redondance.
7. Sélection du dataset accepté pour le reverse engineering.
8. Reconstruction de nouveaux prompts depuis les signatures validées.
