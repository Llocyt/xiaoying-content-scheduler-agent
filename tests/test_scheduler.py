import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from scheduler.agent import run_agent
from scheduler.domain import validate_request
from scheduler.model import MockModel, ModelError, OpenAICompatibleModel
from scheduler.tools import BusinessTools

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'data/fixtures.json').read_text(encoding='utf-8'))
S18, S19 = '2026-11-01T18:00+08:00', '2026-11-01T19:00+08:00'


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'drafts.sqlite'

    def request(self, **updates):
        return validate_request(dict({'request_id': 'test-1', 'asset_id': 'M01',
                                      'requested_slot': S19, 'hard_requirement': True}, **updates))

    def tools(self, request=None, **options):
        return BusinessTools(request or self.request(), FIXTURE, self.db, **options)

    def run_case(self, **updates):
        request = self.request(**updates)
        return run_agent(request, MockModel(), self.tools(request))

    def count(self):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT count(*) FROM drafts').fetchone()[0]

    def ready(self, tools, candidate=S19):
        tools.read_asset(tools.request['asset_id'])
        tools.check_rules()
        tools.query_slots(candidate)

    def test_normal_schedule(self):
        result = self.run_case()['result']
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['save']['save_status'], 'saved')
        self.assertFalse(result['published'])

    def test_conflict_requires_confirmation(self):
        report = self.run_case(requested_slot=S18)
        self.assertEqual(report['result']['status'], 'pending_confirmation')
        self.assertEqual(report['result']['suggested_slot'], S19)
        self.assertEqual(report['input']['requested_slot'], S18)
        self.assertTrue(report['result']['pending_items'])
        queries = [x for x in report['trace'] if x['tool'] == 'query_slots']
        self.assertEqual(len(queries), 2)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)

    def test_confirmed_alternative(self):
        report = self.run_case(requested_slot=S18, confirmed_slot=S19)
        self.assertEqual(report['result']['status'], 'completed')
        self.assertEqual(report['result']['save']['confirmation_status'], 'confirmed')

    def test_confirm_original_pending_draft_no_duplicate(self):
        pending = self.run_case(requested_slot=S18)
        confirmed = self.run_case(requested_slot=S18, confirmed_slot=S19)
        self.assertEqual(confirmed['result']['save']['save_status'], 'updated')
        self.assertEqual(pending['result']['save']['draft_id'], confirmed['result']['save']['draft_id'])
        self.assertEqual(self.count(), 1)
        replay = self.run_case(requested_slot=S18, confirmed_slot=S19)
        self.assertEqual(replay['result']['save']['save_status'], 'existing')

    def test_confirmation_rechecks_competing_reservation(self):
        self.run_case(requested_slot=S18)
        self.run_case(request_id='competitor')
        request = self.request(requested_slot=S18, confirmed_slot=S19)
        tools = self.tools(request)
        self.ready(tools)
        self.assertFalse(tools.save_draft(S19)['ok'])
        with tools.connect() as db:
            payload = json.loads(db.execute('SELECT payload FROM drafts WHERE request_id=?', ('test-1',)).fetchone()[0])
        self.assertEqual(payload['confirmation_status'], 'pending')

    def test_rules_changed_before_save(self):
        tools = self.tools()
        self.ready(tools)
        tools.fixture['assets']['M01']['rights'] = 'denied'
        self.assertEqual(tools.save_draft(S19)['error'], 'review_changed_before_save')
        self.assertEqual(self.count(), 0)

    def test_returned_receipt_cannot_modify_ledger(self):
        tools = self.tools()
        self.ready(tools)
        receipt = tools.save_draft(S19)
        receipt['confirmation_status'] = 'invented'
        self.assertEqual(tools.saved['confirmation_status'], 'confirmed')

    def test_flexible_time(self):
        self.assertEqual(self.run_case(requested_slot=S18, hard_requirement=False)['result']['status'], 'completed')

    def test_missing_information(self):
        report = self.run_case(asset_id='M02')
        self.assertEqual(report['result']['status'], 'incomplete')
        self.assertIn('lookup_metadata', [s['tool'] for s in report['trace']])
        self.assertEqual(self.count(), 0)

    def test_metadata_recovery(self):
        self.assertEqual(self.run_case(asset_id='M04')['result']['status'], 'completed')

    def test_rule_risk(self):
        self.assertEqual(self.run_case(asset_id='M03')['result']['status'], 'blocked')
        self.assertEqual(self.count(), 0)

    def test_rights_risk(self):
        self.assertEqual(self.run_case(asset_id='M06')['result']['status'], 'blocked')

    def test_human_review(self):
        self.assertEqual(self.run_case(asset_id='M05')['result']['status'], 'review_required')

    def test_unknown_asset(self):
        self.assertEqual(self.run_case(asset_id='absent')['result']['status'], 'incomplete')

    def test_duplicate(self):
        first, second = self.run_case(), self.run_case()
        self.assertEqual(second['result']['save']['save_status'], 'existing')
        self.assertEqual(first['result']['save']['draft_id'], second['result']['save']['draft_id'])
        self.assertEqual(self.count(), 1)

    def test_idempotency_key_cannot_change_payload(self):
        self.run_case()
        report = self.run_case(asset_id='M04')
        self.assertEqual(report['result']['save']['error'], 'idempotency_key_conflict')
        self.assertEqual(self.count(), 1)

    def test_save_failure(self):
        request = self.request()
        report = run_agent(request, MockModel(), self.tools(request, fail_save=True))
        self.assertEqual(report['result']['status'], 'save_failed')
        self.assertEqual(report['result']['save']['save_status'], 'failed')
        self.assertEqual(self.count(), 0)

    def test_step_limit(self):
        request = self.request()
        result = run_agent(request, MockModel(), self.tools(request), max_steps=1)
        self.assertEqual(result['result']['status'], 'step_limit')
        self.assertEqual(result['steps_used'], 1)
        self.assertEqual(self.count(), 0)

    def test_save_before_review_denied(self):
        tools = self.tools()
        tools.query_slots(S19)
        self.assertEqual(tools.save_draft(S19)['error'], 'review_not_passed')

    def test_save_without_query_denied(self):
        tools = self.tools()
        tools.read_asset('M01')
        tools.check_rules()
        self.assertEqual(tools.save_draft(S19)['error'], 'query_available_slot_first')

    def test_blocked_asset_cannot_bypass_review(self):
        tools = self.tools(self.request(asset_id='M03'))
        self.ready(tools)
        self.assertFalse(tools.save_draft(S19)['ok'])

    def test_wrong_asset_denied(self):
        self.assertFalse(self.tools().read_asset('M04')['ok'])

    def test_unknown_tool_denied(self):
        self.assertEqual(self.tools().execute('publish', {})['error'], 'unknown_tool')

    def test_changed_occupancy_rechecked_on_save(self):
        tools = self.tools()
        self.ready(tools)
        tools.fixture['occupied'].append(S19)
        self.assertEqual(tools.save_draft(S19)['error'], 'slot_became_unavailable')
        self.assertEqual(self.count(), 0)

    def test_two_requests_cannot_reserve_one_slot(self):
        a, b = self.tools(), self.tools(self.request(request_id='test-2'))
        self.ready(a)
        self.ready(b)
        self.assertTrue(a.save_draft(S19)['ok'])
        self.assertFalse(b.save_draft(S19)['ok'])
        self.assertEqual(self.count(), 1)

    def test_concurrent_duplicate_is_atomic(self):
        a, b = self.tools(), self.tools()
        self.ready(a)
        self.ready(b)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda t: t.save_draft(S19), [a, b]))
        self.assertEqual({r['save_status'] for r in results}, {'saved', 'existing'})
        self.assertEqual(self.count(), 1)

    def test_no_available_slot(self):
        request = self.request()
        tools = self.tools(request)
        tools.fixture['occupied'] = list(tools.fixture['slots'])
        self.assertEqual(run_agent(request, MockModel(), tools)['result']['status'], 'incomplete')

    def test_invalid_requests(self):
        for change in ({'requested_slot': '2026-11-01T19:00'}, {'hard_requirement': 'true'},
                       {'requested_slot': '2026-11-01T19:30+08:00'}, {'asset_id': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.request(**change)

    def test_cross_day_denied(self):
        self.assertFalse(self.tools().query_slots('2026-11-02T19:00+08:00')['ok'])

    def test_invalid_arguments(self):
        self.assertFalse(self.tools().execute('read_asset', {'bad': 1})['ok'])
        self.assertFalse(self.tools().execute('query_slots', {'slot': 'bad'})['ok'])

    def test_malformed_model_action(self):
        class BadModel:
            mode = 'mock'
            def decide(self, *_):
                return {'tool': 'save_draft'}
        self.assertEqual(run_agent(self.request(), BadModel(), self.tools())['result']['status'], 'model_error')

    def test_hallucinated_completion_cannot_save(self):
        class LiarModel:
            mode = 'mock'
            def decide(self, *_):
                return {'tool': 'finish', 'arguments': {}, 'reason': 'Saved and published!'}
        result = run_agent(self.request(), LiarModel(), self.tools())['result']
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['save']['save_status'], 'not_attempted')
        self.assertFalse(result['published'])
        self.assertNotIn('Saved and published!', result['decision_summary'])

    def test_live_missing_config_no_fallback(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ModelError):
            OpenAICompatibleModel()

    def test_live_adapter_serializes_observations(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return json.dumps({'choices': [{'message': {'content': json.dumps({
                    'tool': 'check_rules', 'arguments': {}, 'reason': 'Read result received.'})}}]}).encode()
        with patch.dict(os.environ, {'MODEL_API_KEY': 'fake-test-key', 'MODEL_NAME': 'test-model'}):
            model = OpenAICompatibleModel()
            with patch('urllib.request.OpenerDirector.open', return_value=Response()) as call:
                decision = model.decide(self.request(), [{'tool': 'read_asset', 'observation': {'ok': True}}])
                payload = json.loads(call.call_args.args[0].data)
                self.assertIn('read_asset', payload['messages'][1]['content'])
                self.assertEqual(decision['tool'], 'check_rules')


if __name__ == '__main__':
    unittest.main()
