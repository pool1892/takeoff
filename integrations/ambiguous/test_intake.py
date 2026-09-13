"""Offline DM intake coverage: source authority, fresh-run binding and uncertain writes."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import BridgeError
import intake
from intake import admit

CONTRACTOR = '99999999-9999-4999-8999-999999999999'
WORKSPACE = '88888888-8888-4888-8888-888888888888'
AGENT = '11111111-1111-4111-8111-111111111111'
CHANNEL = '22222222-2222-4222-8222-222222222222'
MESSAGE = '33333333-3333-4333-8333-333333333333'
PROJECT = '44444444-4444-4444-8444-444444444444'
TASK = '55555555-5555-4555-8555-555555555555'


class FakeAPI:
    def __init__(self):
        self.message = {'id': MESSAGE, 'channel_id': CHANNEL, 'author': {'id': CONTRACTOR},
            'content': 'Please price this house package.\n\nUse unfaced R-13 and DemoPEX expansion fittings.',
            'created_at': '2026-09-12T23:30:00Z', 'edited_at': None}
        self.task = None
        self.creates = 0
        self.lose_response = False
        self.hide_task = False
        self.source_reads = 0
        self.edit_on_recheck = False
        self.members = [{'user_id': CONTRACTOR}]
        self.subscribers = []
        self.calls = []

    def call(self, path, method='GET', body=None, **query):
        self.calls.append((path, method, deepcopy(body)))
        if path == '/api/users/me':
            return {'id': AGENT, 'type': 'agent', 'workspace_id': WORKSPACE}
        if path == '/api/channels':
            assert not query, 'Channel listing does not accept pagination'
            return {'data': [{'id': CHANNEL, 'type': 'dm'}], 'has_more': False}
        if path == '/api/channels/' + CHANNEL:
            return {'id': CHANNEL, 'type': 'dm', 'members': [{'user_id': AGENT}, {'user_id': CONTRACTOR}]}
        if '/messages/' in path:
            self.source_reads += 1
            if self.edit_on_recheck and self.source_reads > 1:
                self.message['edited_at'] = '2026-09-12T23:31:00Z'
            return deepcopy(self.message)
        if path == '/api/projects/' + PROJECT:
            return {'id': PROJECT, 'name': 'Bill’s house build'}
        if path.endswith('/members'):
            if method == 'POST':
                self.members.append(body)
            return {'data': deepcopy(self.members), 'has_more': False}
        if path == '/api/tasks':
            if method == 'POST':
                self.creates += 1
                self.task = dict(body, id=TASK, creator_id=AGENT)
                self.subscribers = [{'user_id': user} for user in body['subscriber_ids']]
                if self.lose_response:
                    self.lose_response = False
                    raise BridgeError('API request failed')
                return {'task': deepcopy(self.task)}
            return {'data': [deepcopy(self.task)] if self.task and not self.hide_task else [], 'has_more': False}
        if path == '/api/tasks/' + TASK:
            return {'task': deepcopy(self.task)}
        if path.endswith('/subscriptions'):
            assert not query, 'Subscription listing does not accept query parameters'
            return {'data': deepcopy(self.subscribers), 'has_more': False}
        if path.endswith('/subscribe'):
            self.subscribers.append(body)
            return body
        raise AssertionError((path, method, body, query))


class IntakeTests(unittest.TestCase):
    def setUp(self):
        identities = patch.multiple(intake, CONTRACTOR=CONTRACTOR, WORKSPACE=WORKSPACE)
        identities.start()
        self.addCleanup(identities.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.api = FakeAPI()
        self.setup = {'enabled': True, 'run_id': 'run_fresh', 'project_id': PROJECT,
            'armed_at': '2026-09-12T23:00:00Z',
            'suppliers': [{'id': 'general', 'email': 'vendor@example.test'}],
            'catalog_urls': ['https://supplier.example.test/public/manifest']}
        self.write_setup()
        (self.home / 'config.json').write_text(json.dumps({'enabled': False, 'run_id': 'run_old'}))

    def write_setup(self):
        (self.home / 'intake-config.json').write_text(json.dumps(self.setup))

    def run_intake(self):
        return admit(self.api, self.home, MESSAGE, AGENT)

    def test_preserves_actual_message_and_activates_only_verified_task_once(self):
        self.api.members = []
        result = self.run_intake()
        self.assertTrue(self.api.task['description'].startswith(self.api.message['content'] + '\n\n---'))
        self.assertEqual(self.api.task['assignee_id'], AGENT)
        self.assertEqual(self.api.task['project_id'], PROJECT)
        self.assertEqual(self.api.subscribers, [{'user_id': CONTRACTOR}])
        self.assertEqual(json.loads((self.home / 'config.json').read_text())['task_ids'], [TASK])
        self.assertEqual(result['task_id'], TASK)
        self.assertEqual(self.run_intake()['task_id'], TASK)
        self.assertEqual(self.api.creates, 1)
        self.assertTrue((self.home / ('config-before-intake-' + MESSAGE + '.json')).exists())

    def test_wrong_author_edited_or_stale_source_never_creates_task(self):
        for change in [{'author': {'id': AGENT}}, {'edited_at': '2026-09-12T23:30:01Z'},
                       {'created_at': '2026-09-12T22:59:00Z'}]:
            with self.subTest(change=change):
                self.api = FakeAPI()
                self.api.message.update(change)
                with self.assertRaises(BridgeError):
                    self.run_intake()
                self.assertEqual(self.api.creates, 0)

    def test_lost_create_response_reconciles_exact_task_without_duplicate(self):
        self.api.lose_response = True
        with self.assertRaises(BridgeError):
            self.run_intake()
        self.assertFalse(json.loads((self.home / 'config.json').read_text())['enabled'])
        self.assertEqual(self.run_intake()['task_id'], TASK)
        self.assertEqual(self.api.creates, 1)

    def test_unknown_create_not_visible_stops_instead_of_retrying(self):
        self.api.lose_response = True
        with self.assertRaises(BridgeError):
            self.run_intake()
        self.api.hide_task = True
        with self.assertRaisesRegex(BridgeError, 'Uncertain task creation'):
            self.run_intake()
        self.assertEqual(self.api.creates, 1)

    def test_edit_between_creation_and_activation_leaves_prior_config_disabled(self):
        self.api.edit_on_recheck = True
        with self.assertRaises(BridgeError):
            self.run_intake()
        self.assertFalse(json.loads((self.home / 'config.json').read_text())['enabled'])

    def test_existing_supplier_run_binding_and_mailbox_mismatch_rejected(self):
        directory = self.home / 'runs'
        directory.mkdir()
        (directory / 'old.json').write_text(json.dumps({'run_id': 'run_fresh', 'task_id': 'another-task'}))
        with self.assertRaisesRegex(BridgeError, 'already has another'):
            self.run_intake()
        self.setup['expected_mailbox_id'] = 'shared-mailbox'
        self.write_setup()
        with self.assertRaisesRegex(BridgeError, 'mailbox'):
            self.run_intake()
        self.assertEqual(self.api.creates, 0)


if __name__ == '__main__':
    unittest.main()
