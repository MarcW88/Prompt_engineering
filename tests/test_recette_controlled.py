"""§12 recette — corpus contrôlé regroupant les cas exigés : définition,
comparaison, paraphrases, demande longue à contraintes, observation en erreur,
réponse sans traces, traces OpenAI same-run et réexécution liée à un parent.
Tout est en fixtures : aucun appel payant."""
import unittest
from unittest.mock import Mock

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder, QuestionItem
from test_pipeline_smoke import MemoryRest
from collection_worker import CollectionWorker, ELIGIBLE_PROVIDERS, same_run_fan_out_source


class ControlledCorpusTests(unittest.TestCase):
    def test_controlled_corpus_end_to_end(self):
        # 1) Constitution fidèle : définition courte, comparaison, paraphrases,
        #    longue demande à contraintes — tout admissible, intentions préservées.
        cluster = ClusterInput(
            id="c1", label="mixte",
            representative_question="trail running définition",
            questions=[
                "trail vs course sur route",
                "définition trail running",
                "trail running c'est quoi",
                QuestionItem("Quelles chaussures de trail pour un budget de 80 euros en Belgique ?", "observed"),
            ],
            question_count=5, source_count=2, language="fr")
        candidates = DatasetBuilder().build([cluster], DatasetBuildConfig(candidates_per_cluster=4))
        texts = [candidate.text for candidate in candidates]
        # Expressions courtes conservées telles quelles.
        self.assertIn("trail running définition", texts)
        # L'intention contrainte (budget + lieu) survit au plafond avant les variantes.
        self.assertIn("Quelles chaussures de trail pour un budget de 80 euros en Belgique ?", texts)
        intents = {candidate.metadata["intent_id"] for candidate in candidates}
        self.assertGreaterEqual(len(intents), 2)

        # 2) Contrat d'éligibilité : erreur et réponse sans traces écartées
        #    proprement, surfaces OpenAI et Bright Data admises.
        worker = CollectionWorker.__new__(CollectionWorker)
        worker.db = MemoryRest()
        worker.db.tables['projects'] = [{'id': 'p', 'language': 'fr', 'country': 'BE'}]
        worker.db.tables['prompts'] = [
            {'id': 'pr-ok', 'project_id': 'p', 'text': 'prompt sain', 'cluster_id': 'c'},
            {'id': 'pr-err', 'project_id': 'p', 'text': 'prompt en erreur', 'cluster_id': 'c'},
            {'id': 'pr-notrace', 'project_id': 'p', 'text': 'prompt sans traces', 'cluster_id': 'c'},
            {'id': 'pr-openai', 'project_id': 'p', 'text': 'prompt surface openai', 'cluster_id': 'c'},
        ]
        worker.db.tables['dataset_examples'] = [
            {'prompt_id': 'pr-ok', 'status': 'accepted'},
            {'prompt_id': 'pr-openai', 'status': 'accepted'},
        ]
        worker.db.tables['observations'] = [
            {'id': 'obs-ok', 'prompt_id': 'pr-ok', 'engine': 'chatgpt', 'provider': 'brightdata',
             'answer': 'réponse', 'raw_response': {}},
            {'id': 'obs-err', 'prompt_id': 'pr-err', 'engine': 'chatgpt', 'provider': 'brightdata',
             'answer': '', 'raw_response': {'error': 'wait_element_timeout'}},
            {'id': 'obs-notrace', 'prompt_id': 'pr-notrace', 'engine': 'chatgpt', 'provider': 'brightdata',
             'answer': 'réponse valide sans recherches', 'raw_response': {}},
            {'id': 'obs-openai', 'prompt_id': 'pr-openai', 'engine': 'openai_web_search', 'provider': 'openai',
             'answer': 'réponse', 'raw_response': {'relation': 'independent_reexecution', 'parent_observation_id': 'obs-parent'}},
        ]
        worker.db.tables['fan_outs'] = [
            {'observation_id': 'obs-ok', 'query': 'requête bd', 'source': 'brightdata'},
            {'observation_id': 'obs-openai', 'query': 'requête openai', 'source': 'openai_responses_web_search'},
        ]
        rows = worker.db.tables['observations']
        # Éligibilité = réponse non vide, pas d'erreur, provider admissible ;
        # une réponse valide sans traces reste consultable mais ne prouve rien.
        eligible = [row for row in rows
                    if row['provider'] in ELIGIBLE_PROVIDERS
                    and str(row.get('answer') or '').strip()
                    and not (row.get('raw_response') or {}).get('error')]
        self.assertEqual({row['id'] for row in eligible}, {'obs-ok', 'obs-notrace', 'obs-openai'})
        # Corpus strict : seules les observations avec des fan-outs de la
        # source same-run attendue pour leur surface entrent dans le corpus.
        fan_outs = worker.db.tables['fan_outs']
        corpus = [row for row in eligible
                  if any(f['observation_id'] == row['id'] and f['source'] == same_run_fan_out_source(row['provider'], row['engine'])
                         for f in fan_outs)]
        self.assertEqual({row['id'] for row in corpus}, {'obs-ok', 'obs-openai'})
        # La surface détermine la source same-run attendue, jamais un autre moteur.
        self.assertEqual(same_run_fan_out_source('brightdata', 'chatgpt'), 'brightdata')
        self.assertEqual(same_run_fan_out_source('openai', 'openai_web_search'), 'openai_responses_web_search')
        # La réexécution garde son lien parent et sa relation, sans se fondre
        # dans les traces du run initial.
        reexecution = [row for row in rows if row['id'] == 'obs-openai'][0]
        self.assertEqual(reexecution['raw_response']['relation'], 'independent_reexecution')
        self.assertEqual(reexecution['raw_response']['parent_observation_id'], 'obs-parent')


if __name__ == "__main__":
    unittest.main()
