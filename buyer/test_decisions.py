import copy
import unittest

from buyer.decisions import validate_decision, validate_proposal
from buyer.test_actions import fixture as action_fixture

CONTRACTOR_ID = 'contractor-fixture'


def fixture():
    run, quotes, _ = action_fixture()
    run['contractor_id'] = CONTRACTOR_ID
    run['requirements'][0].update(revision=1, unit='can', specifications={'sheen': 'eggshell'})
    run['products'] = {'p1': {'id': 'p1', 'revision': 3, 'source': 'catalog-1',
                            'unit': 'can', 'pack_size': 1, 'minimum_quantity': 0,
                            'stock': 6, 'specifications': {'sheen': 'satin'}}}
    proposal = {'id': 'proposal-1', 'run_id': 'run-1', 'request_revision': 1,
                'requirement_id': 'r1', 'requirement_revision': 1, 'product_id': 'p1',
                'changed_attributes': {'sheen': 'satin'}, 'quote_id': 'q1', 'quote_revision': 1,
                'created_at': '2026-09-12T20:00:00Z'}
    answer = {**proposal, 'id': 'decision-1', 'proposal_id': 'proposal-1', 'choice': 'approve',
              'source': {'id': 'comment-1', 'author_id': CONTRACTOR_ID,
                         'created_at': '2026-09-12T20:30:00Z'}}
    return run, quotes, proposal, answer


class DecisionsTest(unittest.TestCase):
    def test_authority_uses_the_runs_explicit_contractor_identity(self):
        run, quotes, proposal, answer = fixture()
        run['contractor_id'] = 'another-configured-contractor'
        with self.assertRaisesRegex(ValueError, 'actual contractor'):
            validate_decision(answer, proposal, run, quotes)
        answer['source']['author_id'] = run['contractor_id']
        self.assertTrue(validate_decision(answer, proposal, run, quotes)['validated'])
        for invalid in (None, '', ' ', 123):
            with self.subTest(contractor_id=invalid), self.assertRaisesRegex(ValueError, 'actual contractor'):
                run['contractor_id'] = invalid
                answer['source']['author_id'] = invalid
                validate_decision(answer, proposal, run, quotes)
        run.pop('contractor_id')
        with self.assertRaisesRegex(ValueError, 'actual contractor'):
            validate_decision(answer, proposal, run, quotes)

    def test_approval_is_exact_and_rejection_grants_nothing(self):
        run, quotes, proposal, answer = fixture()
        original = copy.deepcopy(answer)
        result = validate_decision(answer, proposal, run, quotes)
        self.assertEqual(result['decision'], 'approved')
        self.assertEqual(result['approved_specifications'], {'sheen': 'satin'})
        self.assertEqual(result['evidence_refs'], ['comment-1'])
        self.assertEqual(answer, original)
        reject = validate_decision({**answer, 'choice': 'reject'}, proposal, run, quotes)
        self.assertEqual(reject['decision'], 'rejected')
        self.assertEqual(reject['approved_specifications'], {})

    def test_silence_thread_resolution_and_supplier_yes_are_not_approval(self):
        run, quotes, proposal, answer = fixture()
        for choice in (None, '', 'yes', 'resolved', 'approve if cheaper'):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                validate_decision({**answer, 'choice': choice, 'resolved': True}, proposal, run, quotes)
        for author in ('supplier', '', 'another-contractor'):
            with self.subTest(author=author), self.assertRaises(ValueError):
                validate_decision({**answer, 'source': {**answer['source'], 'author_id': author}}, proposal, run, quotes)
        with self.assertRaises(ValueError):
            validate_decision({**answer, 'conditions': {'minimum_savings': 20}}, proposal, run, quotes)

    def test_scope_and_attributes_cannot_expand(self):
        run, quotes, proposal, answer = fixture()
        for patch in ({'run_id': 'old'}, {'request_revision': 0}, {'product_id': 'p2'},
                      {'requirement_id': 'r2'}, {'changed_attributes': {'sheen': 'gloss'}},
                      {'quote_revision': 2}, {'quote_id': 'q2'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_decision({**answer, **patch}, proposal, run, quotes)

    def test_changed_quote_duplicate_and_rejection_stay_effective(self):
        run, quotes, proposal, answer = fixture()
        revised = {**quotes[0], 'id': 'q2', 'revision': 2}
        with self.assertRaises(ValueError):
            validate_decision(answer, proposal, run, [*quotes, revised])
        first = validate_decision({**answer, 'choice': 'reject'}, proposal, run, quotes)
        with self.assertRaises(ValueError):
            validate_decision(answer, proposal, run, quotes, existing_decisions=[first])

    def test_immutable_comment_and_timestamp_required(self):
        run, quotes, proposal, answer = fixture()
        for patch in ({'id': ''}, {'created_at': None}, {'created_at': '2026-09-12T19:59:00Z'},
                      {'created_at': '2026-09-12T20:30:00'}, {'edited_at': '2026-09-12T20:35:00Z'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_decision({**answer, 'source': {**answer['source'], **patch}}, proposal, run, quotes)

    def test_candidate_approval_binds_product_revision(self):
        run, quotes, proposal, answer = fixture()
        for record in (proposal, answer):
            record.pop('quote_id')
            record.pop('quote_revision')
            record.update(candidate_id='c1', product_revision=3)
        candidate = {'id': 'c1', 'run_id': 'run-1', 'request_revision': 1,
                     'product_id': 'p1', 'requirement_id': 'r1', 'product_revision': 3,
                     'status': 'needs_approval',
                     'mismatches': [{'attribute': 'sheen', 'required': 'eggshell', 'actual': 'satin'}]}
        self.assertTrue(validate_decision(answer, proposal, run, candidates=[candidate])['validated'])
        with self.assertRaises(ValueError):
            validate_decision(answer, proposal, run, candidates=[{**candidate, 'product_revision': 4}])

    def test_proposal_can_be_checked_without_manufacturing_an_answer(self):
        run, quotes, proposal, _ = fixture()
        original = copy.deepcopy(proposal)
        checked = validate_proposal(proposal, run, quotes)
        self.assertTrue(checked['proposal_validated'])
        self.assertNotIn('decision', checked)
        self.assertNotIn('validated', checked)
        self.assertNotIn('approved_specifications', checked)
        self.assertEqual(proposal, original)

    def test_proposal_rejects_stale_or_invented_catalog_terms_before_posting(self):
        run, quotes, proposal, _ = fixture()
        for patch in ({'changed_attributes': {'sheen': 'gloss'}}, {'quote_revision': 2},
                      {'requirement_id': 'unknown'}, {'request_revision': 0}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_proposal({**proposal, **patch}, run, quotes)
        run['products']['p1']['stock'] = 0
        with self.assertRaises(ValueError):
            validate_proposal(proposal, run, quotes)


if __name__ == '__main__':
    unittest.main()
