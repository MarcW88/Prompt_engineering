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

## Workflow

1. Import des seeds et collecte depuis GSC, Reddit, forums, avis et SERP/PAA.
2. Normalisation et regroupement des intentions.
3. Construction de signatures de query fan-out.
4. Reconstruction de prompts plausibles avec provenance explicite.
5. Réexécution via Bright Data ou Oxylabs.
6. Mesure de la reproduction, des citations et de la stabilité.
