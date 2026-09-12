import unittest
from copy import deepcopy
from buyer.quotes import normalize_quote


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.raw = {'id': 'q-1', 'run_id': 'run-1', 'request_id': 'inquiry-1', 'vendor_id': 'vendor-a',
                    'revision': 2, 'status': 'issued', 'currency': 'USD',
                    'lines': [{'product_id': 'p1', 'requirement_id': 'r1', 'quantity': 3,
                               'unit': 'carton', 'unit_price': '9.99', 'line_total': '29.97'}],
                    'subtotal': '29.97', 'discounts': [{'amount': '2.00', 'code': 'bundle'}],
                    'fees': [{'amount': '5.00', 'name': 'delivery'}],
                    'taxes': {'status': 'known', 'amount': '0.00'}, 'total': '32.97',
                    'delivery': {'days': 3, 'slot_id': 'slot-1'}, 'expires_at': '2026-09-14T00:00:00Z',
                    'evidence_refs': ['supplier-reply-1']}
        self.now = '2026-09-12T22:00:00Z'

    def normalize(self, **kwargs):
        return normalize_quote(self.raw, now=self.now, **kwargs)

    def test_issued_offer_exact_arithmetic_and_preserved_terms(self):
        before = deepcopy(self.raw)
        result = self.normalize()
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['computed_total'], '32.97')
        self.assertEqual(result['raw'], before)
        self.assertEqual(self.raw, before)
        self.assertEqual(result['revision'], 2)

    def test_unknown_tax_and_fees_never_become_zero(self):
        del self.raw['taxes']
        del self.raw['fees']
        result = self.normalize()
        self.assertFalse(result['valid'])
        self.assertIn('taxes', result['unresolved'])
        self.assertIn('fees', result['unresolved'])
        self.assertEqual(result['taxes']['status'], 'unknown')

    def test_known_tax_is_added_and_exclusion_requires_agreement(self):
        self.raw['taxes'] = {'status': 'known', 'amount': '1.23'}
        self.raw['total'] = '34.20'
        self.assertTrue(self.normalize()['valid'])
        self.raw['taxes'] = {'status': 'excluded'}
        self.raw['total'] = '32.97'
        self.assertIn('taxes', self.normalize()['unresolved'])
        self.raw['taxes']['agreed'] = True
        self.assertTrue(self.normalize()['valid'])

    def test_arithmetic_changes_are_detected(self):
        self.raw['lines'][0]['unit_price'] = '8.99'
        errors = self.normalize()['errors']
        self.assertIn('lines[0].line_total arithmetic mismatch', errors)
        self.assertIn('subtotal arithmetic mismatch', errors)
        self.assertIn('total arithmetic mismatch', errors)

    def test_proposal_expiry_and_currency_cannot_pass(self):
        self.raw.update(status='proposed', currency='EUR', expires_at=self.now)
        result = self.normalize()
        self.assertFalse(result['valid'])
        self.assertIn('quote is not supplier-issued', result['errors'])
        self.assertIn('quote expired', result['errors'])
        self.assertIn('unsupported currency', result['errors'])

    def test_late_reply_stays_bound_to_its_own_inquiry(self):
        result = self.normalize(evidence={'id': 'message-2', 'request_id': 'inquiry-2'})
        self.assertIn('source request_id mismatch', result['errors'])
        self.assertEqual(result['request_id'], 'inquiry-1')
        self.assertIn('message-2', result['evidence_refs'])

    def test_missing_line_and_delivery_facts_are_explicit(self):
        del self.raw['lines'][0]['unit']
        del self.raw['delivery']
        result = self.normalize()
        self.assertIn('lines[0].unit', result['unresolved'])
        self.assertIn('delivery', result['unresolved'])
        self.assertFalse(result['valid'])

    def test_source_is_required_and_quote_id_alias_is_retained(self):
        self.raw['quote_id'] = self.raw.pop('id')
        self.raw['evidence_refs'] = []
        self.assertFalse(self.normalize()['valid'])
        result = self.normalize(evidence={'id': 'http-result-1', 'vendor_id': 'vendor-a'})
        self.assertTrue(result['valid'])
        self.assertEqual(result['id'], 'q-1')

    def test_blank_identity_and_malformed_terms_do_not_pass(self):
        self.raw.update(request_id='', revision=True, lines=[None], fees=[None], evidence_refs='source')
        result = self.normalize()
        self.assertFalse(result['valid'])
        self.assertIn('request_id', result['unresolved'])
        self.assertIn('revision must be a positive integer', result['errors'])
        self.assertIn('lines[0] must be an object', result['errors'])

    def test_completely_missing_quote_returns_gaps(self):
        result = normalize_quote({}, now=self.now)
        self.assertFalse(result['valid'])
        self.assertIn('lines', result['unresolved'])
        self.assertIn('taxes', result['unresolved'])

    def test_supplier_fixture_tax_contract_is_explicit_and_preserved(self):
        del self.raw['taxes']
        self.raw['tax_treatment'] = 'all_fixture_taxes_included'
        result = self.normalize()
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['taxes']['amount'], '0.00')
        self.assertEqual(result['taxes']['scope'], 'synthetic supplier fixture')
        self.assertEqual(result['tax_treatment'], self.raw['tax_treatment'])
        self.assertEqual(result['raw'], self.raw)
        self.raw['tax_treatment'] = 'unspecified'
        self.assertIn('taxes', self.normalize()['unresolved'])


if __name__ == '__main__':
    unittest.main()
