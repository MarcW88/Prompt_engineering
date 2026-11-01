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
        question = 'Comment choisir des chaussures confortables pour la randonnée ?'
        fixture_items = [RawItem(source_type=SourceType.FORUM, platform=platform, raw_text=question, title=question, url=f'https://{platform}.test', metadata={'language': 'fr'}) for platform in ('reddit', 'forum')]
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
        self.assertEqual(built['executions'], 2)
        self.assertEqual(built['accepted'], 2)
        self.assertTrue(w.db.tables['fan_outs'])
        target_id = w.db.tables['observations'][0]['id']
        # Mock network generation, keep the actual ICL candidate construction and worker validation.
        with patch('collection_worker.BrightDataProvider', return_value=provider), patch.object(ICLPromptReconstructor, '_rank_examples', return_value=[(0.9, __import__('analysis.reconstruction', fromlist=['ReconstructionExample']).ReconstructionExample('training', ['observed']))]), patch.object(ICLPromptReconstructor, '_generate_with_llm', return_value=['Quel modèle de chaussures choisir pour marcher confortablement ?']):
            result = w._reverse_engineer({**job, 'input': {'target_observation_ids': [target_id], 'max_validation_executions': 9, 'validation_runs': 3}})
        self.assertEqual(result['executions'], 3)
        self.assertEqual(result['validated'], 1)
        final = w.db.tables['prompts'][-1]
        self.assertEqual(final['metadata']['target_observation_id'], target_id)
        self.assertEqual(final['expected_fan_outs'], ['chaussures randonnée confort semelle', 'chaussures randonnée comparatif'])
        self.assertNotIn('Decathlon', repr(w.db.tables))
