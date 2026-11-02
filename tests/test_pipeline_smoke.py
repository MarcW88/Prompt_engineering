"""One controlled client run through real worker stages; all providers are fixtures."""
import os
import re
import unittest
from collections import defaultdict
from unittest.mock import Mock, patch

from collection_worker import CollectionWorker
from analysis.models import AnalysisObservation
from analysis.icl_reconstruction import ICLPromptReconstructor
from models.raw_item import RawItem, SourceType


class MemoryRest:
    def __init__(self):
        self.tables = defaultdict(list)
        self.tables['projects'] = [{'id': 'p', 'name': 'Client B', 'country': 'BE', 'language': 'fr'}]
        self.tables['seeds'] = [{'id': 'seed', 'project_id': 'p', 'value': 'chaussures randonnée', 'seed_type': 'keyword', 'priority': 90, 'language': 'fr', 'market': 'BE', 'enabled': True}]
        self.tables['datasets'] = [{'id': 'd', 'project_id': 'p', 'target_size': 3, 'execution_sample_size': 2, 'repetitions': 1, 'engines': ['chatgpt'], 'max_budget_eur': 1, 'cost_per_execution_eur': 0.01, 'build_config': {'quality_threshold': 0.1, 'candidates_per_cluster': 3}}]
        # Un kickoff réel déclare ses thèmes : sans eux, la qualification ne
        # peut pas admettre de questions non-brand (régression audit).
        self.tables['jobs'] = [{'id': 'c1', 'project_id': 'p', 'kind': 'collect_sources', 'input': {'source_config': {'themes': ['chaussures de randonnée', 'confort de marche'], 'brand_variants': ['Client B'], 'competitors': []}}}]

    def request(self, method, table, query='', body=None, prefer='return=representation'):
        rows = list(self.tables[table])
        for key, op, value in re.findall(r'(?:^|&)(\w+)=(eq|in)\.([^&]+)', query):
            if op == 'eq':
                rows = [r for r in rows if str(r.get(key)).lower() == value.lower()]
            else:
                rows = [r for r in rows if str(r.get(key)) in value.strip('()').split(',')]
        if method == 'GET':
            if table == 'cluster_questions':
                rows = [{**r, 'questions': next(q for q in self.tables['questions'] if q['id'] == r['question_id'])} for r in rows]
            return rows
        if method == 'POST':
            values = body if isinstance(body, list) else [body]
            result = []
            for value in values:
                row = {'id': f'{table}-{len(self.tables[table])}', **value}
                self.tables[table].append(row)
                result.append(row)
            return result
        if method == 'PATCH':
            for row in rows: row.update(body)
            return rows
        if method == 'DELETE':
            for row in rows: self.tables[table].remove(row)
            return []
        raise AssertionError(method)


class PipelineSmokeTests(unittest.TestCase):
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture', 'DATASET_PROVIDER': 'brightdata'})
    def test_client_pipeline_with_observed_fanouts(self):
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        w.config_path = 'config/decathlon.yaml'  # Deliberately hostile default; must never leak.
        w.fanout_extractor = None
        w._report = Mock()
        w._brightdata_account_cost = Mock(return_value=None)
        job = {'id': 'j', 'project_id': 'p', 'input': {'sources': ['reddit', 'forum', 'serp'], 'query_budget': 3, 'source_config': {'subreddits': ['hiking'], 'forum_urls': ['https://forum.test']}}}
        question = 'Quelles chaussures confortables pour la randonnée ?'
        question_budget = 'Quel budget prévoir pour des chaussures de randonnée ?'
        fixture_items = [
            RawItem(source_type=SourceType.FORUM, platform='reddit', raw_text=question, title=question, url='https://reddit.test', metadata={'language': 'fr'}),
            RawItem(source_type=SourceType.FORUM, platform='forum', raw_text=question_budget, title=question_budget, url='https://forum.test', metadata={'language': 'fr'}),
        ]
        with patch('collection_worker.ForumScraper.run', return_value=fixture_items), patch('collection_worker.SerpScraper.run', return_value=[RawItem(source_type=SourceType.SERP, platform='paa', url='https://google.test', raw_text=question, title=question, metadata={'language': 'fr'})]):
            w._collect(job)
        self.assertEqual(len(w.db.tables['signals']), 3)
        with patch('analysis.question_pipeline._detect_language', return_value='fr'):
            w._transform_signals(job)
        with patch('collection_worker.OpenAIProcessor') as processor:
            processor.return_value.embeddings.return_value = [[1., 0.]] * 3
            w._cluster_questions(job)
        self.assertEqual(len(w.db.tables['clusters']), 1)
        provider = Mock()
        provider.batch_size = 10
        def observe(request):
            return AnalysisObservation(request.prompt, 'brightdata', request.engine, answer='Une réponse utile. ' * 40, fan_outs=['chaussures randonnée confort semelle', 'chaussures randonnée comparatif'], metadata=dict(request.metadata))
        provider.execute_many.side_effect = lambda requests: [observe(r) for r in requests]
        provider.execute.side_effect = observe
        with patch('collection_worker.BrightDataProvider', return_value=provider):
            built = w._build_dataset({**job, 'input': {'dataset_id': 'd'}})
        # Deux intentions distinctes (confort vs budget) → deux candidats fidèles,
        # formulations sources conservées sans préambule.
        self.assertEqual(built['executions'], 2)
        self.assertEqual(built['accepted'], 2)
        texts = [p['text'] for p in w.db.tables['prompts']]
        self.assertIn(question, texts)
        self.assertIn(question_budget, texts)
        self.assertTrue(w.db.tables['fan_outs'])
        target_id = w.db.tables['observations'][0]['id']
        # Mock network generation, keep the actual ICL candidate construction and worker validation.
        with patch('collection_worker.BrightDataProvider', return_value=provider), patch.object(ICLPromptReconstructor, '_rank_examples', return_value=[(0.9, __import__('analysis.reconstruction', fromlist=['ReconstructionExample']).ReconstructionExample('training', ['observed']))]), patch.object(ICLPromptReconstructor, '_generate_with_llm', return_value=['Quel modèle de chaussures choisir pour marcher confortablement ?']):
            result = w._reverse_engineer({**job, 'input': {'target_observation_ids': [target_id], 'max_validation_executions': 9, 'validation_runs': 3}})
        self.assertEqual(result['executions'], 4)  # +1 run baseline
        self.assertEqual(result['validated'], 1)
        final = w.db.tables['prompts'][-1]
        self.assertEqual(final['metadata']['target_observation_id'], target_id)
        self.assertEqual(final['expected_fan_outs'], ['chaussures randonnée confort semelle', 'chaussures randonnée comparatif'])
        self.assertNotIn('Decathlon', repr(w.db.tables))

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture'})
    def test_reexecution_is_a_separate_observation(self):
        """Le fallback OpenAI produit sa propre observation liée au run parent ;
        les fan-outs du run Bright Data restent vides (traces non exposées)."""
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        extractor = Mock()
        extractor.extract.return_value = {
            'queries': ['fallback query'], 'answer': 'réponse fallback',
            'model': 'gpt-5.4-mini', 'response_id': 'resp-1',
            'search_calls': 1, 'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        w.fanout_extractor = extractor
        prompt = {'id': 'pr-1'}
        parent = AnalysisObservation('prompt test', 'brightdata', 'chatgpt', answer='réponse', fan_outs=[])
        job = {'id': 'j', 'project_id': 'p'}
        parent_id = w._persist_observation(prompt, parent, job=job)
        observations = w.db.tables['observations']
        self.assertEqual(len(observations), 2)
        child = observations[1]
        self.assertEqual(child['provider'], 'openai')
        self.assertEqual(child['engine'], 'openai_web_search')
        self.assertEqual(child['raw_response']['relation'], 'independent_reexecution')
        self.assertEqual(child['raw_response']['parent_observation_id'], parent_id)
        # Les fan-outs vivent sur la réexécution, pas sur le run Bright Data.
        fan_outs = w.db.tables['fan_outs']
        self.assertTrue(all(f['observation_id'] == child['id'] for f in fan_outs))
        self.assertTrue(all(f['metadata']['relation'] == 'independent_reexecution' for f in fan_outs))
        self.assertEqual(child['answer'], 'réponse fallback')
        # Le coût de la réexécution est comptabilisé.
        self.assertTrue(any(c['provider'] == 'openai' and c['category'] == 'fan_out_reexecution' for c in w.db.tables['analysis_costs']))

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture'})
    def test_openai_surface_target_executes_via_extractor(self):
        """Une cible de la surface openai_web_search est réexécutée par
        l'extracteur OpenAI — jamais par Bright Data."""
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        w.db.tables['projects'] = [{'id': 'p', 'language': 'fr', 'country': 'BE'}]
        w.db.tables['prompts'] = [
            {'id': 'pr-train', 'project_id': 'p', 'text': 'prompt entrainement', 'cluster_id': 'c'},
            {'id': 'pr-target', 'project_id': 'p', 'text': 'prompt cible', 'cluster_id': 'c'},
        ]
        w.db.tables['dataset_examples'] = [{'prompt_id': 'pr-train', 'status': 'accepted'}]
        w.db.tables['observations'] = [
            {'id': 'obs-train', 'prompt_id': 'pr-train', 'engine': 'openai_web_search', 'provider': 'openai', 'answer': 'réponse', 'raw_response': {}},
            {'id': 'obs-target', 'prompt_id': 'pr-target', 'engine': 'openai_web_search', 'provider': 'openai', 'answer': 'réponse', 'raw_response': {}},
        ]
        w.db.tables['fan_outs'] = [
            {'observation_id': 'obs-train', 'query': 'train query', 'source': 'openai_responses_web_search'},
            {'observation_id': 'obs-target', 'query': 'target query', 'source': 'openai_responses_web_search'},
        ]
        w._report = Mock()
        w._record_cost = Mock()
        w.fanout_extractor = Mock()
        w.fanout_extractor.extract.side_effect = lambda request: {
            'queries': ['target query'], 'answer': 'réponse', 'model': 'm',
            'response_id': 'r1', 'search_calls': 1, 'usage': {},
        }
        job = {'id': 'j', 'project_id': 'p', 'input': {
            'target_observation_ids': ['obs-target'],
            'max_validation_executions': 9, 'validation_runs': 3, 'max_targets': 1,
        }}
        with patch.object(ICLPromptReconstructor, '_generate_with_llm', return_value=['candidat']):
            result = w._reverse_engineer(job)
        self.assertEqual(result['executions'], 4)  # 3 runs candidat + 1 run baseline même surface
        self.assertEqual(w.fanout_extractor.extract.call_count, 4)
        self.assertEqual(result['validated'], 1)
        self.assertTrue(all(o['engine'] == 'openai_web_search' for o in w.db.tables['observations'][2:]))

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture'})
    def test_adaptive_validation_mixed_candidates(self):
        """Un candidat qui échoue au premier run ne reçoit aucune répétition ;
        le contexte ICL ne contient que des exemples du même moteur."""
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        w.db.tables['projects'] = [{'id': 'p', 'language': 'fr', 'country': 'BE'}]
        w.db.tables['prompts'] = [
            {'id': 'pr-train', 'project_id': 'p', 'text': 'prompt entrainement', 'cluster_id': 'c'},
            {'id': 'pr-target', 'project_id': 'p', 'text': 'prompt cible', 'cluster_id': 'c'},
        ]
        w.db.tables['dataset_examples'] = [{'prompt_id': 'pr-train', 'status': 'accepted'}]
        w.db.tables['observations'] = [
            {'id': 'obs-train', 'prompt_id': 'pr-train', 'engine': 'chatgpt', 'provider': 'brightdata', 'answer': 'réponse', 'raw_response': {}},
            {'id': 'obs-train-gemini', 'prompt_id': 'pr-train', 'engine': 'gemini', 'provider': 'brightdata', 'answer': 'réponse', 'raw_response': {}},
            {'id': 'obs-target', 'prompt_id': 'pr-target', 'engine': 'chatgpt', 'provider': 'brightdata', 'answer': 'réponse', 'raw_response': {}},
            {'id': 'obs-errored', 'prompt_id': 'pr-target', 'engine': 'chatgpt', 'provider': 'brightdata', 'answer': '', 'raw_response': {'error': 'timeout'}},
        ]
        w.db.tables['fan_outs'] = [
            {'observation_id': 'obs-train', 'query': 'train query', 'source': 'brightdata'},
            {'observation_id': 'obs-train-gemini', 'query': 'gemini trace', 'source': 'brightdata'},
            {'observation_id': 'obs-target', 'query': 'target query', 'source': 'brightdata'},
        ]
        w._report = Mock()
        w._record_cost = Mock()
        contexts = []

        def generate(self, *args, **kwargs):
            contexts.append([e.engine for e in self.examples])
            return ['candidat gagnant', 'candidat perdant']

        provider = Mock()
        provider.batch_size = 10
        provider.execute.side_effect = lambda request: AnalysisObservation(
            request.prompt, 'brightdata', request.engine,
            answer='réponse' if 'gagnant' in request.prompt else '',
            fan_outs=['target query'] if 'gagnant' in request.prompt else [],
            raw_response={} if 'gagnant' in request.prompt else {'error': 'failed'},
        )
        job = {'id': 'j', 'project_id': 'p', 'input': {
            'target_observation_ids': ['obs-target', 'obs-errored'],
            'max_validation_executions': 20, 'validation_runs': 3, 'max_targets': 2,
        }}
        with patch('collection_worker.BrightDataProvider', return_value=provider), \
             patch.object(ICLPromptReconstructor, '_generate_with_llm', generate):
            result = w._reverse_engineer(job)
        # obs-errored est écartée par le contrat d'admission (answer vide + error).
        self.assertEqual(result['executions'], 5)  # 1 perdant + 3 gagnant + 1 baseline
        self.assertEqual(result['validated'], 1)
        # Segmentation moteur : pas de trace Gemini dans le contexte d'une cible ChatGPT.
        self.assertTrue(contexts)
        for engines in contexts:
            self.assertNotIn('gemini', engines)

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture'})
    def test_edited_version_drives_icl_examples(self):
        """Un run exécuté sur « texte édité » produit un exemple ICL portant
        le texte édité — jamais l'ancienne formulation de prompts.text."""
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        w.db.tables['projects'] = [{'id': 'p', 'language': 'fr', 'country': 'BE'}]
        w.db.tables['prompts'] = [
            {'id': 'pr-train', 'project_id': 'p', 'text': 'ancien texte', 'cluster_id': 'c'},
            {'id': 'pr-target', 'project_id': 'p', 'text': 'prompt cible', 'cluster_id': 'c'},
        ]
        w.db.tables['dataset_examples'] = [{'prompt_id': 'pr-train', 'status': 'accepted'}]
        w.db.tables['observations'] = [
            {'id': 'obs-train', 'prompt_id': 'pr-train', 'engine': 'chatgpt', 'provider': 'brightdata',
             'answer': 'réponse', 'raw_response': {'executed_text': 'texte édité'}},
            {'id': 'obs-target', 'prompt_id': 'pr-target', 'engine': 'chatgpt', 'provider': 'brightdata',
             'answer': 'réponse', 'raw_response': {}},
        ]
        w.db.tables['fan_outs'] = [
            {'observation_id': 'obs-train', 'query': 'train query', 'source': 'brightdata'},
            {'observation_id': 'obs-target', 'query': 'target query', 'source': 'brightdata'},
        ]
        w._report = Mock()
        w._record_cost = Mock()
        contexts = []

        def generate(self, *args, **kwargs):
            contexts.append([e.prompt for e in self.examples])
            return ['candidat gagnant']

        provider = Mock()
        provider.batch_size = 10
        provider.execute.side_effect = lambda request: AnalysisObservation(
            request.prompt, 'brightdata', request.engine,
            answer='réponse', fan_outs=['target query'], raw_response={},
        )
        job = {'id': 'j', 'project_id': 'p', 'input': {
            'target_observation_ids': ['obs-target'],
            'max_validation_executions': 9, 'validation_runs': 1, 'max_targets': 1,
        }}
        with patch('collection_worker.BrightDataProvider', return_value=provider), \
             patch.object(ICLPromptReconstructor, '_generate_with_llm', generate):
            w._reverse_engineer(job)
        self.assertTrue(contexts)
        for example_texts in contexts:
            self.assertIn('texte édité', example_texts)
            self.assertNotIn('ancien texte', example_texts)


class FanoutFallbackFlagTests(unittest.TestCase):
    def _worker(self, enabled):
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = MemoryRest()
        w.fanout_extractor = Mock()
        w.fanout_fallback_enabled = enabled
        w._record_cost = Mock()
        return w

    def _observation(self):
        return AnalysisObservation(
            'prompt test', 'dataforseo', 'chatgpt',
            answer='une réponse sans traces', fan_outs=[], raw_response={},
        )

    def test_disabled_flag_never_triggers_auxiliary_call(self):
        w = self._worker(False)
        w._persist_reexecution = Mock(side_effect=AssertionError('auxiliary call fired'))
        w._persist_observation({'id': 'p1'}, self._observation(), job={'id': 'j'})
        w._persist_reexecution.assert_not_called()
        # L'observation principale est tout de même persistée.
        self.assertEqual(len(w.db.tables['observations']), 1)

    def test_enabled_flag_calls_extractor_once_per_untraced_observation(self):
        w = self._worker(True)
        extractor_obs = Mock()
        extractor_obs.__bool__ = lambda self: True
        w.fanout_extractor.extract = Mock(return_value={
            'response_id': 'r1', 'model': 'gpt-x', 'search_calls': 1,
            'queries': ['q1'], 'usage': {'input_tokens': 1}, 'answer': 'a',
        })
        w._persist_observation({'id': 'p1'}, self._observation(), job={'id': 'j'})
        w.fanout_extractor.extract.assert_called_once()
        # La réexécution est une observation séparée, liée et marquée.
        self.assertEqual(len(w.db.tables['observations']), 2)
        self.assertEqual(w.db.tables['observations'][1]['relation'], 'independent_reexecution')
