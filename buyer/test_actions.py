import copy
from decimal import Decimal
import unittest

from buyer.actions import validate_action


def fixture():
    run = {'run_id': 'run-1', 'request_revision': 1,
           'evaluated_at': '2026-09-12T21:00:00Z',
           'authority': {'supplier_inquiries': True, 'supplier_negotiation': True,
                         'allow_orders': False, 'budget_cap': '500.00', 'currency': 'USD'},
           'requirements': [{'id': 'r1', 'revision': 1, 'quantity': 6, 'unit': 'can',
                             'specifications': {'material': 'paint'}}],
           'products': {'p1': {'id': 'p1', 'revision': 1, 'source': 'catalog-1', 'unit': 'can',
                               'pack_size': 1, 'minimum_quantity': 1, 'stock': 20,
                               'specifications': {'material': 'paint'}}},
           'suppliers': [{'id': 'v1', 'email': 'one@example.test'},
                         {'id': 'v2', 'email': 'two@example.test'}]}
    quote = {'id': 'q1', 'run_id': 'run-1', 'request_id': 'i1', 'revision': 1,
             'status': 'issued', 'vendor_id': 'v1', 'currency': 'USD', 'total': '270',
             'subtotal': '270', 'fees': [], 'discounts': [], 'taxes': {'status': 'known', 'amount': '0'},
             'created_at': '2026-09-12T20:00:00Z', 'delivery': {'days': 2}, 'evidence_refs': ['supplier-q1'],
             'expires_at': '2026-09-20T00:00:00Z',
             'lines': [{'requirement_id': 'r1', 'product_id': 'p1', 'quantity': 6, 'unit': 'can',
                        'unit_price': '45', 'line_total': '270'}]}
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


class CompetingPackageTests(unittest.TestCase):
    def quote(self, ident, vendor, lines):
        normalized = []
        for product, quantity, unit, price in lines:
            normalized.append({'requirement_id': 'r1', 'product_id': product, 'quantity': quantity,
                               'unit': unit, 'unit_price': str(price),
                               'line_total': str(Decimal(str(quantity)) * Decimal(str(price)))})
        total = str(sum((Decimal(line['line_total']) for line in normalized), Decimal(0)))
        return {'id': ident, 'run_id': 'run-1', 'request_id': 'request-' + ident, 'revision': 1,
                'vendor_id': vendor, 'status': 'issued', 'currency': 'USD', 'lines': normalized,
                'subtotal': total, 'total': total, 'fees': [], 'discounts': [],
                'taxes': {'status': 'known', 'amount': '0'}, 'evidence_refs': ['reply-' + ident],
                'created_at': '2026-09-12T20:00:00Z', 'delivery': {'days': 2},
                'expires_at': '2026-09-20T00:00:00Z'}

    def package(self):
        run, _, action = fixture()
        run['requirements'] = [{'id': 'r1', 'revision': 1, 'quantity': 20, 'unit': 'sq_ft',
                                'specifications': {'grade': 'A'}}]
        run['products'] = {
            'p1': {'id': 'p1', 'vendor_id': 'v1', 'revision': 1, 'source': 'catalog-v1',
                   'unit': 'box', 'pack_size': 1, 'minimum_quantity': 1, 'stock': 10,
                   'units_per_sale_unit': 10, 'requirement_unit': 'sq_ft', 'specifications': {'grade': 'A'}},
            'p2': {'id': 'p2', 'vendor_id': 'v2', 'revision': 1, 'source': 'catalog-v2',
                   'unit': 'carton', 'pack_size': 1, 'minimum_quantity': 1, 'stock': 10,
                   'units_per_sale_unit': 20, 'requirement_unit': 'sq_ft', 'specifications': {'grade': 'A'}}}
        quotes = [self.quote('q1', 'v1', [('p1', 2, 'box', 10)]),
                  self.quote('q2', 'v2', [('p2', 1, 'carton', 18)])]
        action.update(competing_quote_id='q2', competing_total='18', target_total='17.75')
        return run, quotes, action

    def test_different_pack_counts_with_same_actual_coverage_are_comparable(self):
        run, quotes, action = self.package()
        before = copy.deepcopy((run, quotes, action))
        checked = validate_action(action, run, quotes, [])
        self.assertTrue(checked['validated'])
        self.assertEqual(checked['target_total'], '17.75')
        self.assertEqual((run, quotes, action), before)

    def test_same_pack_counts_with_different_actual_coverage_are_not_comparable(self):
        run, quotes, action = self.package()
        run['products']['p2'].update(unit='box', units_per_sale_unit=12)
        quotes[1] = self.quote('q2', 'v2', [('p2', 2, 'box', 9)])
        with self.assertRaisesRegex(ValueError, 'same requirement quantities'):
            validate_action(action, run, quotes, [])

    def test_quote_cannot_override_documented_pack_conversion(self):
        for field, value in (('units_per_sale_unit', 10), ('covered_quantity', 10), ('requirement_unit', 'each')):
            run, quotes, action = self.package()
            quotes[1]['lines'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'conflicts with current product facts'):
                validate_action(action, run, quotes, [])

    def test_latest_catalog_facts_override_stale_eligible_candidate(self):
        for change in ({'stock': 0}, {'specifications': {'grade': 'B'}}, {'current': False}):
            run, quotes, action = self.package()
            old = copy.deepcopy(run['products']['p2'])
            run['candidates'] = {'old': {'id': 'old', 'requirement_id': 'r1', 'product_id': 'p2',
                                         'product': old, 'assessment': {'status': 'suitable'}}}
            run['products']['p2'].update(revision=2, **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_action(action, run, quotes, [])

    def test_stale_quote_product_revision_is_not_equivalent(self):
        run, quotes, action = self.package()
        quotes[1]['lines'][0]['product_revision'] = 1
        run['products']['p2']['revision'] = 2
        with self.assertRaisesRegex(ValueError, 'old product revision'):
            validate_action(action, run, quotes, [])

    def test_substitute_requires_exact_current_approval_scope(self):
        run, quotes, action = self.package()
        run['products']['p2']['specifications']['grade'] = 'B'
        approval = {'id': 'approval-1', 'run_id': 'run-1', 'request_revision': 1,
                    'requirement_id': 'r1', 'requirement_revision': 1, 'product_id': 'p2',
                    'product_revision': 1, 'quote_id': 'q2', 'quote_revision': 1,
                    'decision': 'approved', 'validated': True, 'approved_specifications': {'grade': 'B'},
                    'evidence_refs': ['contractor-answer'], 'source': {'created_at': '2026-09-12T20:30:00Z'}}
        with self.assertRaises(ValueError):
            validate_action(action, run, quotes, [])
        self.assertTrue(validate_action(action, run, quotes, [approval])['validated'])
        for patch in ({'requirement_revision': 0}, {'product_revision': 0}, {'quote_revision': 2},
                      {'decision': 'rejected'}, {'validated': False}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_action(action, run, quotes, [{**approval, **patch}])

    def test_red_red_cannot_be_cited_as_equivalent_to_red_blue(self):
        run, _, action = self.package()
        run['requirements'] = [{'id': 'r1', 'revision': 1, 'quantity': 200, 'unit': 'linear_ft',
                                'specifications': {'material': 'PEX'}, 'variants': [
                                    {'id': color, 'quantity': 100, 'unit': 'linear_ft',
                                     'specifications': {'color': color, 'coil_length_ft': 100}}
                                    for color in ('red', 'blue')]}]
        run['products'] = {}
        for vendor in ('v1', 'v2'):
            for color in ('red', 'blue'):
                pid = vendor + '-' + color
                run['products'][pid] = {'id': pid, 'vendor_id': vendor, 'revision': 1, 'source': 'catalog-' + vendor,
                    'unit': 'coil', 'pack_size': 1, 'minimum_quantity': 1, 'stock': 10,
                    'units_per_sale_unit': 100, 'requirement_unit': 'linear_ft',
                    'specifications': {'material': 'PEX', 'color': color, 'coil_length_ft': 100}}
        quotes = [self.quote('q1', 'v1', [('v1-red', 1, 'coil', 10), ('v1-blue', 1, 'coil', 10)]),
                  self.quote('q2', 'v2', [('v2-red', 1, 'coil', 9), ('v2-blue', 1, 'coil', 9)])]
        self.assertTrue(validate_action(action, run, quotes, [])['validated'])
        quotes[1]['lines'][1]['product_id'] = 'v2-red'
        with self.assertRaisesRegex(ValueError, 'variant blue'):
            validate_action(action, run, quotes, [])

    def test_quote_variant_label_cannot_override_product_facts(self):
        run, quotes, action = self.package()
        quotes[1]['lines'][0]['variant'] = 'invented-variant'
        with self.assertRaisesRegex(ValueError, 'quoted variant conflicts'):
            validate_action(action, run, quotes, [])


if __name__ == '__main__':
    unittest.main()
