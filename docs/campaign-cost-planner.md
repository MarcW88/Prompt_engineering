# Prévision d’une campagne

Entrées : setup de collecte → « Estimer l’analyse complète », ou « Coûts réels » → « Estimer une nouvelle analyse ».

Le simulateur accepte 1–10 000 prompts finaux, questions courtes ou demandes contextualisées. Le format ne multiplie pas artificiellement le tarif : les utilisateurs précisent le modèle et un coût par exécution incluant ses tokens/recherches. Le défaut 0,02 € est repris du Dataset Builder et explicitement qualifié d’hypothèse, jamais de tarif fournisseur.

Calcul :

- Candidats issus des sources = plafond(prompts finaux non reconstruits / taux de rétention).
- Chaque candidat passe une fois sur chaque moteur. Seuls les finalistes ont les répétitions supplémentaires. « 3 passages » signifie trois au total, pas un screening plus trois validations.
- Pour la part reconstruite, le nombre de cibles est calculé à partir du taux de rétention et des 3–5 candidats par cible. Les candidats sont testés sur la première surface, plus une baseline/cible. Leur premier passage est réutilisé dans les répétitions ; les autres surfaces testent les finalistes. Les cibles sont répartissables en jobs de dix au plus. Il s’agit d’un scénario de travail, pas d’une modification du worker.
- S’ajoutent collecte toutes sources, préparation/embeddings, ICL par cible, infrastructure, marge explicite et dépenses déjà engagées. Ces dernières doivent exclure les opérations futures déjà chiffrées dans le scénario pour éviter le double comptage.

Une cellule vide est inconnue. La somme des postes chiffrés reste un **sous-total partiel** jusqu’à la saisie de tous les coûts nécessaires. La comparaison au plafond reste indéterminée si le plan ou l’engagement existant est incomplet. Un zéro est un choix explicite de l’utilisateur. La marge n’est ni un plafond garanti ni un intervalle statistique.

Le setup transmet au simulateur son estimation de collecte et les noms des sources, sans en désactiver aucune. La simulation n’appelle aucun provider, ne crée pas de job, ne change pas le plafond projet et ne configure pas implicitement les étapes de collecte/exécution. Son export JSON inclut paramètres, hypothèses, quantités, lignes de coût et inconnus. Les dépenses réalisées restent dans le journal existant.

Limites : les tarifs ne sont pas synchronisés avec les comptes fournisseurs ; la rétention n’est pas calibrée ; le nombre de prompts distincts et la couverture des seeds ne sont pas garantis. L’estimation doit être rapprochée du journal et les tarifs actualisés avant engagement. La recommandation historique de collecte reste accessible avec un libellé explicitement indicatif ; elle n’est pas utilisée par ce nouveau calcul.

Vérification : `node --test tests/campaign_estimate.test.mjs tests/fanout_parser.test.mjs`, `npx tsc --noEmit`, `npm run lint`, `npm run build`. Les tests couvrent plusieurs volumes, les moteurs/répétitions, les rejets, les inconnus, les marges/engagements et la reconstruction avec baseline sans double comptage.

## Scénario complet par défaut

Les quatre surfaces proposées sont sélectionnées à l’ouverture. Le mode prudent applique le plus grand prix renseigné aux surfaces chiffrées ; une valeur inconnue reste inconnue. Les tarifs saisis et effectifs sont tous deux exportés. Retirer une surface recalcule immédiatement les quantités et le coût. Le tarif commun initial de 0,02 EUR est explicitement une hypothèse, également sur OpenAI, pas un plafond fournisseur. Perplexity reste exclu compte tenu du précédent défaut provider. Le catalogue exprime les surfaces proposées, pas une vérification live de leurs clés, datasets ou fonctionnement. Aucun paramètre de lancement ni budget n’est modifié.
