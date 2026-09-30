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

## Workflow

1. Collecte depuis GSC, Reddit, forums, avis et SERP/PAA.
2. Normalisation et regroupement des intentions.
3. Construction de signatures de query fan-out.
4. Reconstruction de prompts plausibles avec provenance explicite.
5. Réexécution via Bright Data ou Oxylabs.
6. Mesure de la reproduction, des citations et de la stabilité.
