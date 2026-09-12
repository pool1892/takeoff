"""Clarification admission and revocation from authoritative task comment evidence."""
from copy import deepcopy
import unittest

from buyer import cli
from buyer.test_cli import FakeAPI, run_state
from bridge import CONTRACTOR
from procurement import Procurement


class ClarificationTests(unittest.TestCase):
    def setUp(self):
        self.state = run_state()
        self.state.update(evidence={}, actions={}, proposals={}, approvals=[], handled_sources=[], events=[])
        self.state['requirements'] = [
            {'id': 'insulation', 'revision': 1, 'quantity': 600, 'unit': 'sq_ft',
             'source_text': 'R-13 fiberglass batts, 15-inch wide, enough for 600 sq ft.',
             'specifications': {'r_value': 'R-13'}, 'missing_essentials': ['facing', 'unrelated_pending']},
            {'id': 'tubing', 'revision': 1, 'quantity': 200, 'unit': 'linear_ft',
             'source_text': 'One red and one blue coil; must work with our fittings.',
             'specifications': {'material': 'PEX'}, 'missing_essentials': ['fitting_system']},
        ]
        self.comment = {'id': 'contractor-answer-1', 'author': {'id': CONTRACTOR},
                        'content': 'Use unfaced batts. Our fittings are DemoPEX expansion fittings.',
                        'created_at': '2026-09-12T23:00:00Z', 'updated_at': '2026-09-12T23:00:00Z'}
        self.api = FakeAPI()
        self.listener = Procurement(self.api, 'buyer-agent', runner=lambda *_: ('session', 'Unused'))
        self.listener.ingest(self.state, [self.comment], [])
        self.snapshots = []

    def persist(self):
        self.snapshots.append(deepcopy(self.state))

    def payload(self, fitting=False, **patch):
        value = {'requirement_id': 'tubing' if fitting else 'insulation',
                 'key': 'fitting_system' if fitting else 'facing',
                 'specification_attribute': 'connection_system' if fitting else 'facing',
                 'value': 'DemoPEX expansion fittings' if fitting else 'unfaced',
                 'source_id': self.comment['id']}
        value.update(patch)
        return value

    def clarify(self, payload=None):
        return cli.execute('clarify', payload or self.payload(), self.state, self.persist, self.api)

    def test_actual_contractor_values_update_exact_specs_and_only_named_gaps(self):
        source_texts = [r['source_text'] for r in self.state['requirements']]
        facing = self.clarify()
        fitting = self.clarify(self.payload(fitting=True))
        insulation, tubing = self.state['requirements']
        self.assertEqual(insulation['specifications']['facing'], 'unfaced')
        self.assertEqual(insulation['missing_essentials'], ['unrelated_pending'])
        self.assertEqual(tubing['specifications']['connection_system'], 'DemoPEX expansion fittings')
        self.assertEqual(tubing['missing_essentials'], [])
        self.assertTrue(facing['validated'])
        self.assertTrue(fitting['validated'])
        self.assertEqual(facing['source_id'], self.comment['id'])
        self.assertEqual([r['revision'] for r in self.state['requirements']], [2, 2])
        self.assertEqual(self.state['request_revision'], 1)
        self.assertEqual([r['source_text'] for r in self.state['requirements']], source_texts)
        self.assertFalse(self.api.calls)

    def test_repeat_after_reload_does_not_increment_revision_or_duplicate_event(self):
        first = deepcopy(self.clarify())
        self.state = deepcopy(self.snapshots[-1])
        before = deepcopy(self.state)
        self.assertEqual(self.clarify(), first)
        self.assertEqual(self.state, before)
        self.assertEqual(self.state['requirements'][0]['revision'], 2)
        self.assertEqual(len([e for e in self.state['events'] if e['type'] == 'clarification']), 1)

    def test_supplier_model_and_unknown_sources_cannot_supply_contractor_intent(self):
        self.state['evidence']['supplier-source'] = {
            'id': 'supplier-source', 'channel': 'supplier_email', 'data': deepcopy(self.comment)}
        self.state['evidence']['model-source'] = {
            'id': 'model-source', 'channel': 'contractor_comment',
            'data': {**self.comment, 'author': {'id': 'buyer-agent'}}}
        for source_id in ('supplier-source', 'model-source', 'missing-source'):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                self.clarify(self.payload(source_id=source_id))
        self.assertEqual(self.state['requirements'][0]['revision'], 1)
        self.assertIn('facing', self.state['requirements'][0]['missing_essentials'])

    def test_deleted_edited_and_changed_timestamp_sources_are_rejected(self):
        for patch in ({'deleted_at': '2026-09-12T23:01:00Z'}, {'edited_at': '2026-09-12T23:01:00Z'},
                      {'updated_at': '2026-09-12T23:01:00Z'}):
            with self.subTest(patch=patch):
                self.state['evidence'][self.comment['id']]['data'] = {**self.comment, **patch}
                with self.assertRaises(ValueError):
                    self.clarify()
        self.assertEqual(self.state['requirements'][0]['revision'], 1)

    def test_value_must_be_present_as_exact_words_not_substring_or_invention(self):
        for payload in (self.payload(value='kraft-faced'), self.payload(value='faced'),
                        self.payload(fitting=True, value='PEX expansion fittings')):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.clarify(payload)

    def test_clarification_key_cannot_rewrite_a_different_attribute(self):
        for patch in ({'key': 'grade'}, {'specification_attribute': 'r_value'}, {'value': ''}, {'value': None}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.clarify(self.payload(**patch))

    def test_source_removed_reopens_missing_essential_once_and_prevents_stale_readmission(self):
        self.clarify()
        self.assertTrue(self.listener.ingest(self.state, [], []))
        requirement = self.state['requirements'][0]
        self.assertNotIn('facing', requirement.get('clarifications', {}))
        self.assertNotIn('facing', requirement['specifications'])
        self.assertIn('facing', requirement['missing_essentials'])
        self.assertEqual(requirement['revision'], 3)
        self.assertFalse(self.listener.ingest(self.state, [], []))
        self.assertEqual(requirement['revision'], 3)
        with self.assertRaises(ValueError):
            self.clarify()

    def test_edited_source_invalidates_facing_and_fitting_but_preserves_source_text(self):
        self.clarify()
        self.clarify(self.payload(fitting=True))
        text = [r['source_text'] for r in self.state['requirements']]
        edited = {**self.comment, 'content': 'Wait for confirmation.', 'updated_at': '2026-09-12T23:01:00Z'}
        self.assertTrue(self.listener.ingest(self.state, [edited], []))
        insulation, tubing = self.state['requirements']
        self.assertIn('facing', insulation['missing_essentials'])
        self.assertIn('fitting_system', tubing['missing_essentials'])
        self.assertNotIn('facing', insulation['specifications'])
        self.assertNotIn('connection_system', tubing['specifications'])
        self.assertEqual([r['revision'] for r in self.state['requirements']], [3, 3])
        self.assertEqual([r['source_text'] for r in self.state['requirements']], text)
        with self.assertRaises(ValueError):
            self.clarify()

    def test_revocation_restores_prior_specification_and_unrelated_gaps(self):
        requirement = self.state['requirements'][0]
        requirement['specifications']['facing'] = 'unresolved prior value'
        self.clarify()
        self.listener.ingest(self.state, [], [])
        self.assertEqual(requirement['specifications']['facing'], 'unresolved prior value')
        self.assertEqual(set(requirement['missing_essentials']), {'facing', 'unrelated_pending'})

    def test_unchanged_source_does_not_revoke_valid_clarification(self):
        self.clarify()
        before = deepcopy(self.state)
        self.assertFalse(self.listener.ingest(self.state, [deepcopy(self.comment)], []))
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
