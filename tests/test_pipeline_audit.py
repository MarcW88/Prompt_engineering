"""Offline regressions for production adapters and worker reconstruction."""
import os
import unittest
import warnings
from unittest.mock import Mock, patch

from analysis.models import AnalysisRequest, AnalysisObservation
from analysis.providers.brightdata import BrightDataProvider
from analysis.icl_reconstruction import ICLPromptReconstructor
from analysis.reconstruction import ReconstructionExample
from collection_worker import CollectionWorker
from scrapers.arctic_shift import ArcticShiftClient
from scrapers.forum_scraper import ForumScraper
from scrapers.review_scraper import ReviewScraper
from scrapers.serp_scraper import SerpScraper
from sources.discovery import SourceDiscovery
from models.seed import Seed
from utils.config_loader import neutral_config


def config():
    c = neutral_config({'id': 'p', 'name': 'Client B', 'language': 'fr', 'country': 'BE'})
    c.seeds = [Seed('chaussures de randonnée')]
    c.scraping.delay_between_requests = 0
    c.scraping.reviews.update(min_text_length=10, max_pages=1)
    return c


class AdapterTests(unittest.TestCase):
    def test_discovery_fallback_on_error_empty_and_unavailable(self):
        for state in (False, True, None):
            d = SourceDiscovery('http://searx', delay=0)
            d.searxng_available = state
            d._searxng_search = Mock(return_value=[])
            d._dataforseo_search = Mock(return_value=[{'url': 'https://forum.test/thread'}])
            self.assertEqual(len(d.search('test')), 1)
            d._dataforseo_search.assert_called_once()
        d._searxng_search.return_value = [{'url': 'https://free.test'}]
        d._dataforseo_search.reset_mock()
        d.search('test')
        d._dataforseo_search.assert_not_called()

    def test_paa_fallback_independent_of_five_suggestions(self):
        s = SerpScraper(config())
        s.auth_header = 'test'
        s._scrape_paa_free = Mock(return_value=[])
        s._scrape_suggestions_free = Mock(return_value=list(range(5)))
        s._scrape_paa_dataforseo = Mock(return_value=['paa'])
        s._scrape_suggestions_dataforseo = Mock(return_value=[])
        self.assertEqual(s._scrape_query('test'), ['paa', 0, 1, 2, 3, 4])
        s._scrape_paa_dataforseo.assert_called_once()
        s._scrape_suggestions_dataforseo.assert_not_called()
        s._scrape_paa_free.return_value = ['free-paa']
        s._scrape_suggestions_free.return_value = []
        s._scrape_query('test2')
        s._scrape_suggestions_dataforseo.assert_called_once()

    def test_arctic_request_period_and_failure(self):
        a = ArcticShiftClient(delay=0)
        a.session.get = Mock(return_value=Mock(json=lambda: {'data': [{'id': 'a'}]}))
        self.assertEqual(a.search_posts('hiking', 'boots', after='2026-01-01')[0]['id'], 'a')
        self.assertEqual(a.session.get.call_args.kwargs['params']['after'], '2026-01-01')
        a.session.get.side_effect = RuntimeError('offline')
        self.assertEqual(a.search_posts('hiking'), [])
        self.assertFalse(a.available)

    def test_reddit_posts_comments_and_json_fallback(self):
        s = ForumScraper(config())
        s.arctic.search_posts = Mock(return_value=[{'id': 'post', 'title': 'Comment choisir mes chaussures de randonnée ?', 'permalink': '/r/hiking/post'}])
        s.arctic._get = Mock(return_value=[{'body': 'Je cherche une semelle confortable pour marcher longtemps.'}])
        items = s._scrape_subreddit('hiking', 1)
        self.assertEqual([i.metadata['signal_kind'] for i in items], ['post', 'comment'])
        self.assertTrue(all(i.metadata['provider'] == 'arctic_shift' for i in items))
        s.arctic.search_posts.return_value = []
        with patch('scrapers.forum_scraper.requests.get', return_value=Mock(status_code=200, json=lambda: {'data': {'children': [{'data': {'title': 'Comment choisir mes chaussures pour marcher ?'}}]}})):
            items = s._scrape_subreddit('hiking', 1)
        self.assertEqual(items[0].metadata['provider'], 'reddit_public_json')

    def test_forum_content_keeps_individual_posts(self):
        s = ForumScraper(config())
        s.discovery.search = Mock(return_value=[{'url': 'https://forum.test/t', 'title': 'Thread', 'snippet': 'snippet'}])
        with patch('scrapers.forum_scraper.extract_url_content', return_value={'engine': 'forumscraper', 'title': 'Thread', 'posts': [{'text': 'Une longue question sur les chaussures pour marcher ?', 'author': 'a'}, {'text': 'Une deuxième réponse sur les semelles de randonnée.', 'author': 'b'}]}):
            items = s._discover_and_extract('shoes', 'test', 1)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.metadata['extractor'] == 'forumscraper' for i in items))

    def test_extractor_requests_in_memory_data(self):
        try:
            import forumscraper
        except Exception:
            self.skipTest("forumscraper requires Python >= 3.10")
        from scrapers.extractors import extract_forum_thread
        def get_thread(url, state, output):
            self.assertIn(forumscraper.Outputs.data, output)
            state['data'] = {'threads': [{'posts': [{'content': 'Un contenu de forum suffisamment long pour extraction.'}]}]}
        with patch.object(forumscraper, 'Extractor', return_value=Mock(get_thread=get_thread)):
            self.assertEqual(len(extract_forum_thread('https://test/thread')['posts']), 1)

    def test_trafilatura_empty_reaches_bs4(self):
        from scrapers.extractors import extract_page_text
        with patch('trafilatura.extract', return_value=None), patch('scrapers.extractors.requests.get', return_value=Mock(ok=True, text='<p>' + 'texte long ' * 20 + '</p>')):
            self.assertIn('texte long', extract_page_text('https://test')['text'])

    def test_trustpilot_structured_and_html_after_paid_failure(self):
        s = ReviewScraper(config())
        s._fetch = Mock(return_value=Mock(text='<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"reviews":[{"rating":2,"text":"Livraison beaucoup trop lente","consumer":{"displayName":"Alice"},"dates":{"publishedDate":"2026-01-01T00:00:00Z"}}]}}}</script>'))
        items = s._scrape_trustpilot({'url': 'https://trust.test'})
        self.assertEqual(items[0].rating, 2)
        self.assertEqual(items[0].metadata['author'], 'Alice')
        self.assertIsNotNone(items[0].date)
        s._scrape_trustpilot_nextdata = Mock(return_value=[])
        s.auth_header = 'test'
        s._scrape_trustpilot_dataforseo = Mock(return_value=[])
        s._scrape_trustpilot_html = Mock(return_value=['html'])
        self.assertEqual(s._scrape_trustpilot({}), ['html'])

    @patch.dict(os.environ, {'GOOGLE_MAPS_SCRAPER_URL': 'https://maps.test', 'GOOGLE_MAPS_SCRAPER_API_KEY': 'test'})
    def test_maps_launch_poll_filter_rawitem(self):
        s = ReviewScraper(config())
        place = {'title': 'Store', 'link': 'https://maps/place', 'reviews': [{'rating': 2, 'text': 'Un service beaucoup trop lent', 'name': 'Alice'}, {'rating': 5, 'text': 'Un service vraiment très bien'}]}
        with patch('scrapers.review_scraper.requests.post', return_value=Mock(status_code=202, json=lambda: {'job_id': 'j'})) as post, patch('scrapers.review_scraper.requests.get', return_value=Mock(status_code=200, json=lambda: {'status': 'completed', 'results': [place]})):
            items = s._scrape_google_reviews({'queries': ['Store BE']})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].rating, 2)
        self.assertEqual(post.call_args.kwargs['headers']['X-API-Key'], 'test')

    def test_all_nested_fanout_blocks(self):
        raw = {'web_search_query': 'one', 'metadata': {'search_model_queries': {'queries': ['two', 'three', 'four']}}, 'blocks': [{'search_queries': [{'q': 'five'}]}, {'queries': ['six']}, {'web_search_queries': ['seven', 'two']}]}
        o = BrightDataProvider().parse_response(AnalysisRequest('prompt'), raw)
        self.assertEqual(o.fan_outs, ['one', 'two', 'three', 'four', 'five', 'six', 'seven'])

    def test_neutral_configs_do_not_share_sources_or_client_defaults(self):
        a, b = config(), config()
        a.sources['forums']['platforms'].append({'name': 'reddit', 'subreddits': ['client-a']})
        self.assertEqual(b.sources['forums']['platforms'], [])
        self.assertEqual(b.sources['reviews']['platforms'], [])
        self.assertNotIn('Decathlon', repr(b))


class ReconstructionTests(unittest.TestCase):
    def test_semantic_retrieval_beats_lexical_and_caches(self):
        r = ICLPromptReconstructor([ReconstructionExample('similar meaning', ['semantic']), ReconstructionExample('overlap', ['target'])], api_key='test')
        # Target text equals second example, so use separate target wording.
        with patch('analysis.icl_reconstruction.requests.post', return_value=Mock(json=lambda: {'data': [{'index': 0, 'embedding': [1, 0]}, {'index': 1, 'embedding': [1, 0]}, {'index': 2, 'embedding': [0, 1]}]})) as post:
            ranked = r._rank_examples(['target phrase'])
            self.assertEqual(ranked[0][1].prompt, 'similar meaning')
            r._rank_examples(['target phrase'])
            self.assertEqual(post.call_count, 1)

    @patch.dict(os.environ, {}, clear=True)
    def test_icl_fallback_is_visible(self):
        r = ICLPromptReconstructor([])
        with warnings.catch_warnings(record=True) as recorded:
            result = r.reconstruct(['observed search'])
        self.assertTrue(recorded)
        self.assertEqual(result[0].metadata['method'], 'deterministic_fallback')

    def test_worker_observed_target_reconstruction_execution_and_persistence(self):
        from analysis.models import PromptCandidate, PromptProvenance
        calls = []
        def db(method, table, query='', body=None, prefer='return=representation'):
            calls.append((method, table, query, body))
            if method == 'GET':
                if table == 'dataset_examples': return [{'prompt_id': 'train'}]
                if table == 'projects': return [{'language': 'fr', 'country': 'BE'}]
                if table == 'prompts': return [{'id': 'train', 'text': 'Original training prompt', 'cluster_id': 'c'}, {'id': 'target-p', 'text': 'Held out original', 'cluster_id': 'c'}]
                if table == 'observations':
                    if 'target-p' in query: return [{'id': 'target-o', 'prompt_id': 'target-p', 'engine': 'chatgpt', 'provider': 'brightdata', 'answer': 'ok', 'raw_response': {}}]
                    return [{'id': 'train-o', 'prompt_id': 'train', 'engine': 'chatgpt', 'provider': 'brightdata', 'answer': 'ok', 'raw_response': {}}]
                if table == 'fan_outs': return [{'observation_id': 'train-o', 'query': 'observed boots query', 'source': 'brightdata'}]
            if method == 'POST' and table == 'prompts': return [{'id': 'new', **body[0]}]
            if method == 'POST' and table == 'observations': return [{'id': 'new-o'}]
            return []
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = Mock(request=Mock(side_effect=db))
        w._record_cost = Mock()
        candidate = PromptCandidate('Reconstructed prompt', PromptProvenance.REVERSE_ENGINEERED, expected_fan_outs=['observed boots query'], metadata={'method': 'icl_retrieval'})
        provider = Mock(execute=Mock(return_value=AnalysisObservation('Reconstructed prompt', 'brightdata', 'chatgpt', answer='answer', fan_outs=['observed boots query'])))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch('collection_worker.BrightDataProvider', return_value=provider), patch.object(ICLPromptReconstructor, 'reconstruct', return_value=[candidate]) as reconstruct:
            result = w._reverse_engineer({'id': 'j', 'project_id': 'p', 'input': {'target_observation_ids': ['target-o'], 'max_validation_executions': 9, 'validation_runs': 3}})
        self.assertEqual(reconstruct.call_args.args[0], ['observed boots query'])
        self.assertEqual(provider.execute.call_count, 4)  # 3 runs candidat + 1 run baseline
        self.assertEqual(result['validated'], 1)
        updates = [body for method, table, _, body in calls if method == 'PATCH' and table == 'prompts']
        self.assertEqual(updates[-1]['status'], 'validated')
        self.assertEqual(updates[-1]['metadata']['reproduction_score'], 1)
        self.assertTrue(any(table == 'fan_outs' and method == 'POST' for method, table, _, _ in calls))

    def test_record_cost_estimates_pending_amount(self):
        calls = []
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = Mock(request=Mock(side_effect=lambda method, table, query='', body=None, prefer='r': calls.append(body) or [{}]))
        w._record_cost({'id': 'j', 'project_id': 'p'}, 'brightdata', 'reconstruction_validation',
            quantity=4, unit='executions', cost_status='pending_reconciliation', estimated_unit_cost=0.05)
        self.assertEqual(calls[0][0]['amount'], 0.2)
        w._record_cost({'id': 'j', 'project_id': 'p'}, 'brightdata', 'web_scraper_api',
            amount=0.5, cost_status='account_delta', estimated_unit_cost=0.05)
        self.assertEqual(calls[1][0]['amount'], 0.5)  # l'estimation ne remplace pas un montant réel

    def test_settle_reservation_holds_pending_and_releases_reconciled(self):
        rows = [
            {'amount': 0.4, 'cost_status': 'account_delta'},
            {'amount': 0.15, 'cost_status': 'pending_reconciliation'},
            {'amount': 0.09, 'cost_status': 'usage_only'},
        ]
        w = CollectionWorker.__new__(CollectionWorker)
        w.db = Mock(request=Mock(return_value=rows))
        settlement = w._settle_reservation({'id': 'j'})
        self.assertEqual(settlement['reserved_cost_eur'], 0.24)
        self.assertTrue(settlement['reservation_open'])
        w.db = Mock(request=Mock(return_value=[{'amount': 0.4, 'cost_status': 'account_delta'}]))
        settlement = w._settle_reservation({'id': 'j'})
        self.assertEqual(settlement['reserved_cost_eur'], 0)
        self.assertFalse(settlement['reservation_open'])

if __name__ == '__main__': unittest.main()
