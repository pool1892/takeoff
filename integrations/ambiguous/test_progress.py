"""Progress reporting stays factual, paced and safe across uncertain delivery."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import BridgeError, CONTRACTOR
from progress import notify_progress, overview

AGENT = '11111111-1111-4111-8111-111111111111'
CHANNEL = '22222222-2222-4222-8222-222222222222'
TASK = '33333333-3333-4333-8333-333333333333'


class FakeAPI:
    def __init__(self):
        self.messages = []
        self.posts = 0
        self.fail_after_send = False
        self.group = False
        self.now = 1000

    def call(self, path, method='GET', body=None, **query):
        if path == '/api/channels':
            assert not query
            return {'data': [{'id': CHANNEL, 'type': 'dm'}]}
        if path == '/api/channels/' + CHANNEL:
            return {'type': 'dm', 'members': [{'user_id': AGENT}, {'user_id': CONTRACTOR}]
                    + ([{'user_id': 'third-person'}] if self.group else [])}
        if path.endswith('/messages'):
            if method == 'GET':
                return {'data': deepcopy(self.messages), 'has_more': False}
            self.posts += 1
            row = {'id': str(self.posts), 'content': body['content'], 'author': {'id': AGENT},
                   'created_at': datetime.fromtimestamp(self.now, timezone.utc).isoformat()}
            self.messages.append(row)
            if self.fail_after_send:
                self.fail_after_send = False
                raise BridgeError('Transport interrupted')
            return row
        raise AssertionError((path, method, query))


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.state = {'task_id': TASK, 'agent_id': AGENT, 'run_id': 'run-private', 'request_revision': 1,
            'phase': 'ready', 'requirements': [{'id': 'house-01', 'missing_essentials': []}],
            'products': {}, 'candidates': {}, 'evidence': {}, 'actions': {}, 'proposals': {},
            'suppliers': [{'id': 'v1'}, {'id': 'v2'}, {'id': 'v3'}], 'quotes': {}}
        self.saved = []

    def notify(self, now=1000):
        self.api.now = now
        return notify_progress(self.api, self.state, lambda: self.saved.append(deepcopy(self.state)), now=now)

    def test_first_overview_then_unchanged_and_meaningful_change_throttled(self):
        self.assertEqual(self.notify()['status'], 'sent')
        self.assertEqual(self.notify(1001)['status'], 'unchanged')
        self.state['products'] = {'p': {'id': 'p'}}
        self.assertEqual(self.notify(1020)['status'], 'throttled')
        self.assertEqual(self.notify(1060)['status'], 'sent')
        self.assertEqual(self.api.posts, 2)

    def test_counts_confirmed_work_and_hides_unvalidated_proposal_and_raw_errors(self):
        self.state['requirements'] = [{'id': f'house-{n:02}', 'missing_essentials': ['facing'] if n == 10 else
                                      ['fitting_system'] if n == 16 else []} for n in range(1, 26)]
        self.state['products'] = {str(n): {'id': str(n), 'source': 'catalog:general:product-' + str(n)} for n in range(67)}
        self.state['evidence'] = {'catalog_hash1': {'channel': 'website', 'url': 'https://catalog.example/one',
                                                  'data': {'catalog': {'products': [{'id': 'one'}]}}},
                                 'catalog_hash2': {'channel': 'website', 'url': 'https://catalog.example/two',
                                                  'data': {'products': [{'id': 'two'}]}},
                                 'catalog_hash3': {'channel': 'website', 'url': 'https://catalog.example/three',
                                                  'data': {'products': [{'id': 'three'}]}},
                                 'manifest': {'channel': 'website', 'url': 'https://catalog.example/manifest',
                                              'data': {'vendors': [{'id': 'general'}]}},
                                 'reply': {'channel': 'supplier_email', 'vendor_id': 'v1', 'body': 'PRIVATE TEXT'}}
        self.state['actions'] = {v: {'status': 'sent', 'result': {'id': 'remote'}, 'input': {'vendor_id': v}}
                                 for v in ['v1', 'v2', 'v3']}
        self.state['proposals'] = {'unsafe': {'status': 'pending', 'input': {'question': 'PRIVATE PROPOSAL'}}}
        self.state['continuation_blocker'] = 'PRIVATE GUARD'
        metrics, body = overview(self.state, 1000)
        self.assertEqual((metrics['requirements'], metrics['products'], metrics['sent'], metrics['replied']), (25, 67, 3, 1))
        self.assertEqual(metrics['catalogs'], 3)
        self.assertIn('67 products found across 3 catalogs', body)
        self.assertIn('insulation facing', body)
        self.assertIn('PEX fitting system', body)
        self.assertEqual(metrics['approvals'], 0)
        self.assertNotIn('PRIVATE', body)
        self.assertNotIn('run-private', body)

    def test_uncertain_post_is_reconciled_without_duplicate(self):
        self.api.fail_after_send = True
        self.assertEqual(self.notify()['status'], 'deferred')
        self.assertEqual(self.notify(1060)['status'], 'unchanged')
        self.assertEqual(self.api.posts, 1)
        self.assertEqual(next(iter(self.state['progress_notifications']['records'].values()))['status'], 'sent')

    def test_unseen_uncertain_send_is_not_retried_and_final_can_still_send(self):
        self.api.fail_after_send = True
        self.notify()
        self.api.messages = []
        self.assertEqual(self.notify(1060)['status'], 'pending_reconciliation')
        self.assertEqual(self.api.posts, 1)
        self.state.update(phase='complete', plan={'complete': True, 'blockers': []})
        self.assertEqual(self.notify(1061)['status'], 'sent')
        self.assertIn('recommendation is ready', self.api.messages[-1]['content'])
        self.assertEqual(self.api.posts, 2)

    def test_final_bypasses_interval_but_incomplete_plan_does_not_claim_completion(self):
        self.notify()
        self.state.update(phase='complete', plan={'complete': False, 'blockers': ['secret blocker']})
        self.assertNotIn('recommendation is ready', overview(self.state, 1001)[1])
        self.state['plan'] = {'complete': True, 'blockers': []}
        self.assertEqual(self.notify(1002)['status'], 'sent')
        self.assertEqual(self.notify(1003)['status'], 'unchanged')

    def test_group_dm_or_persistence_failure_never_sends_and_does_not_raise(self):
        self.api.group = True
        self.assertEqual(self.notify()['status'], 'deferred')
        self.assertEqual(self.api.posts, 0)
        def failed_persist():
            raise OSError('private filesystem path')
        result = notify_progress(self.api, deepcopy(self.state), failed_persist, now=1100)
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(self.api.posts, 0)


if __name__ == '__main__':
    unittest.main()
