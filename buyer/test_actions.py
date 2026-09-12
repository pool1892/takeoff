import copy
import unittest

from buyer.actions import validate_action


def fixture():
    run = {'run_id': 'run-1', 'request_revision': 1,
           'evaluated_at': '2026-09-12T21:00:00Z',
           'authority': {'supplier_inquiries': True, 'supplier_negotiation': True,
                         'allow_orders': False, 'budget_cap': '500.00', 'currency': 'USD'},
           'requirements': [{'id': 'r1', 'quantity': 6}],
           'suppliers': [{'id': 'v1', 'email': 'one@example.test'},
                         {'id': 'v2', 'email': 'two@example.test'}]}
    quote = {'id': 'q1', 'run_id': 'run-1', 'request_id': 'i1', 'revision': 1,
             'status': 'issued', 'vendor_id': 'v1', 'currency': 'USD', 'total': '270',
             'expires_at': '2026-09-20T00:00:00Z',
             'lines': [{'requirement_id': 'r1', 'product_id': 'p1', 'quantity': 6, 'unit': 'can'}]}
    action = {'id': 'a1', 'type': 'counter', 'run_id': 'run-1', 'request_revision': 1,
              'vendor_id': 'v1', 'message': 'Can you quote $251.37 delivered?',
              'previous_quote_id': 'q1', 'target_total': '251.37', 'currency': 'USD'}
    return run, [quote], action


class ActionsTest(unittest.TestCase):
    def test_model_numeric_choice_preserved_and_inputs_unchanged(self):
        run, quotes, action = fixture()
        original = copy.deepcopy(action)
        result = validate_action(action, run, quotes, [])
        self.assertEqual(result['target_total'], '251.37')
        self.assertFalse(result['is_commitment'])
        self.assertEqual(action, original)

    def test_orders_and_untrusted_destinations_rejected(self):
        for patch in ({'type': 'acceptance'}, {'type': 'order'}, {'to': 'stranger@example.test'},
                      {'vendor_id': 'unknown'}, {'accept_terms': True}):
            run, quotes, action = fixture()
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_action({**action, **patch}, run, quotes, [])

    def test_numeric_and_hard_budget_failures(self):
        for value in ('NaN', 'Infinity', '-2', '0', True, '501'):
            run, quotes, action = fixture()
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action({**action, 'target_total': value}, run, quotes, [])
        run, quotes, action = fixture()
        with self.assertRaises(ValueError):
            validate_action({**action, 'currency': 'EUR'}, run, quotes, [])

    def test_scope_authority_and_budget_exhaustion(self):
        run, quotes, action = fixture()
        for patch in ({'run_id': 'old'}, {'request_revision': 0}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_action({**action, **patch}, run, quotes, [])
        for patch in ({'authority': {}}, {'remaining_actions': 0}, {'actions': [action]},
                      {'execution_deadline': '2026-09-12T20:00:00Z'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_action(action, {**run, **patch}, quotes, [])

    def test_expired_superseded_wrong_supplier_quotes(self):
        run, quotes, action = fixture()
        for patch in ({'expires_at': '2026-09-11T00:00:00Z'}, {'status': 'proposed'},
                      {'vendor_id': 'v2'}, {'run_id': 'old'}, {'request_revision': 0}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_action(action, run, [{**quotes[0], **patch}], [])
        later = {**quotes[0], 'id': 'q2', 'revision': 2}
        with self.assertRaises(ValueError):
            validate_action(action, run, [*quotes, later], [])

    def test_competing_quote_must_exist_and_cover_same_quantity(self):
        run, quotes, action = fixture()
        action['competing_quote_id'] = 'q2'
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        second = {**quotes[0], 'id': 'q2', 'request_id': 'i2', 'vendor_id': 'v2'}
        self.assertTrue(validate_action(action, run, [*quotes, second], [])['validated'])
        second['lines'] = [{**second['lines'][0], 'quantity': 5}]
        with self.assertRaises(ValueError):
            validate_action(action, run, [*quotes, second], [])

    def test_unknown_products_and_invalid_quantities(self):
        run, quotes, action = fixture()
        action['items'] = [{'requirement_id': 'r1', 'product_id': 'unknown', 'quantity': 6}]
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        action['items'][0].update(product_id='p1', quantity=-1)
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])

    def test_recommendation_needs_current_evidence(self):
        run, quotes, _ = fixture()
        action = {'id': 'r', 'type': 'recommend', 'run_id': 'run-1', 'request_revision': 1}
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        result = validate_action({**action, 'quote_ids': ['q1']}, run, quotes, [])
        self.assertFalse(result['is_commitment'])

    def test_derived_prices_cannot_bypass_budget(self):
        run, quotes, action = fixture()
        action.pop('target_total')
        action['items'] = [{'requirement_id': 'r1', 'product_id': 'p1', 'quantity': 6, 'target_unit_price': '100'}]
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        action = {'id': 'rec', 'type': 'recommend', 'run_id': 'run-1', 'request_revision': 1, 'quote_ids': ['q1']}
        with self.assertRaises(ValueError):
            validate_action(action, run, [{**quotes[0], 'total': '501'}], [])

    def test_cited_price_cannot_be_invented(self):
        run, quotes, action = fixture()
        action['competing_total'] = '12'
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        second = {**quotes[0], 'id': 'q2', 'request_id': 'i2', 'vendor_id': 'v2'}
        action['competing_quote_id'] = 'q2'
        with self.assertRaises(ValueError):
            validate_action(action, run, [*quotes, second], [])


if __name__ == '__main__':
    unittest.main()
