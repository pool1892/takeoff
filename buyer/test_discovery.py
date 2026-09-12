import unittest
from copy import deepcopy
from buyer.discovery import assess_candidate, quantity_for_requirement, requirement_for_product


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.requirement = {'id': 'floor', 'revision': 1, 'source_text': '200 sqft light oak 5mm',
                            'quantity': '200', 'unit': 'sq_ft', 'missing_essentials': [],
                            'specifications': {'thickness_mm': 5, 'finish': 'light oak'}}
        self.product = {'id': 'flooring-a', 'revision': 3, 'vendor_id': 'vendor-a',
                        'name': 'flooring', 'specifications': {'thickness_mm': 5, 'finish': 'light oak'},
                        'unit': 'carton', 'pack_size': 1, 'minimum_quantity': 1, 'stock': 20,
                        'coverage_quantity': '23.64', 'coverage_unit': 'sq_ft', 'source': 'catalog-3'}

    def test_coverage_rounds_whole_cartons_without_invented_waste(self):
        result = quantity_for_requirement(self.requirement, self.product)
        self.assertEqual(result['selling_quantity'], '9')
        self.assertEqual(result['coverage_quantity'], '212.76')
        self.assertEqual(result['excess_quantity'], '12.76')
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'suitable')

    def test_pack_increment_and_moq_use_same_selling_unit(self):
        req = {'quantity': 21, 'unit': 'sheet'}
        product = {'unit': 'sheet', 'pack_size': 10, 'minimum_quantity': 35}
        self.assertEqual(quantity_for_requirement(req, product)['selling_quantity'], '40')

    def test_public_supplier_coverage_names_and_selling_stock(self):
        product = deepcopy(self.product)
        product['units_per_sale_unit'] = product.pop('coverage_quantity')
        product['requirement_unit'] = product.pop('coverage_unit')
        self.assertEqual(quantity_for_requirement(self.requirement, product)['selling_quantity'], '9')
        product['stock'] = 8
        self.assertEqual(assess_candidate(self.requirement, product)['status'], 'unavailable')

    def test_conflicting_coverage_evidence_blocks_candidate(self):
        self.product.update(units_per_sale_unit='20', requirement_unit='sq_ft')
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')

    def test_missing_conversion_is_unknown(self):
        del self.product['coverage_quantity']
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertIn('documented coverage conversion', result['missing_evidence'])
        self.assertIsNone(result['quantity']['selling_quantity'])

    def test_mismatch_and_missing_fact_remain_distinct(self):
        self.product['specifications']['thickness_mm'] = 4
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'needs_approval')
        self.assertEqual(result['mismatches'][0]['attribute'], 'thickness_mm')
        del self.product['specifications']['thickness_mm']
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertEqual(result['mismatches'], [])

    def test_only_validated_exact_current_substitution_is_allowed(self):
        self.product['specifications']['thickness_mm'] = 4
        approval = {'id': 'decision-1', 'requirement_id': 'floor', 'requirement_revision': 1,
                    'product_id': 'flooring-a', 'product_revision': 3, 'decision': 'approved',
                    'approved_specifications': {'thickness_mm': 4}, 'evidence_refs': ['answer-1'],
                    'validated': True}
        result = assess_candidate(self.requirement, self.product, [approval])
        self.assertEqual(result['status'], 'approved_substitution')
        self.assertEqual(result['approval_refs'], ['decision-1'])
        for key, value in (('requirement_revision', 0), ('product_id', 'other'),
                           ('decision', 'rejected'), ('validated', False),
                           ('approved_specifications', {'thickness_mm': 6}), ('product_revision', 2)):
            changed = deepcopy(approval)
            changed[key] = value
            self.assertEqual(assess_candidate(self.requirement, self.product, [changed])['status'],
                             'needs_approval', key)

    def test_missing_essential_remains_unresolved(self):
        self.requirement['missing_essentials'] = ['facing']
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')

    def test_approval_cannot_cross_known_run_scope(self):
        self.requirement.update(run_id='current-run', request_revision=2)
        self.product['specifications']['thickness_mm'] = 4
        approval = {'id': 'decision-1', 'requirement_id': 'floor', 'requirement_revision': 1,
                    'run_id': 'old-run', 'request_revision': 2,
                    'product_id': 'flooring-a', 'decision': 'approved', 'validated': True,
                    'approved_specifications': {'thickness_mm': 4}, 'evidence_refs': ['answer-1']}
        self.assertEqual(assess_candidate(self.requirement, self.product, [approval])['status'], 'needs_approval')
        approval['run_id'] = 'current-run'
        self.assertEqual(assess_candidate(self.requirement, self.product, [approval])['status'], 'approved_substitution')

    def test_unknown_and_insufficient_stock(self):
        self.product['stock'] = None
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')
        self.product['stock'] = 8
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'unavailable')

    def test_numeric_bounds_are_explicit_and_no_name_matching(self):
        self.requirement['specifications']['thickness_mm'] = {'min': 5}
        self.product['name'] = 'unrelated text'
        self.assertTrue(assess_candidate(self.requirement, self.product)['eligible'])
        self.product['specifications']['thickness_mm'] = 4
        self.assertFalse(assess_candidate(self.requirement, self.product)['eligible'])

    def test_input_immutability_and_source_revision(self):
        before = deepcopy(self.product)
        result = assess_candidate(self.requirement, self.product)
        result['product']['stock'] = 0
        self.assertEqual(self.product, before)
        self.assertEqual(result['product_revision'], 3)
        self.assertEqual(result['source'], 'catalog-3')

    def test_invalid_quantities_do_not_crash_or_produce_orders(self):
        for quantity in ('NaN', 'Infinity', -1, True):
            self.requirement['quantity'] = quantity
            result = quantity_for_requirement(self.requirement, self.product)
            self.assertTrue(result['errors'])
            self.assertIsNone(result['selling_quantity'])


class EvidencePresenceTests(unittest.TestCase):
    def setUp(self):
        self.requirement = {
            'id': 'house-12', 'revision': 2, 'quantity': 12, 'unit': 'sheet',
            'source_text': '12 sheets half-inch cement backer board, 3x5, sold for interior wall tile backing.',
            'specifications': {'material': 'cement backer board',
                               'manufacturer_stated_use': 'interior wall tile backing'},
            'evidence_attributes': ['use_evidence_ref'],
        }
        self.product = {
            'id': 'backer', 'revision': 1, 'unit': 'sheet', 'pack_size': 1,
            'minimum_quantity': 1, 'stock': 20, 'source': 'public-catalog',
            'specifications': {**self.requirement['specifications'],
                               'use_evidence_ref': 'fixture:cement-backer-data'},
        }

    def test_documented_reference_satisfies_presence_without_literal_value(self):
        before = deepcopy(self.requirement)
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'suitable')
        self.assertEqual(result['mismatches'], [])
        self.assertEqual(result['product']['specifications']['use_evidence_ref'],
                         'fixture:cement-backer-data')
        self.assertEqual(self.requirement, before)

    def test_missing_or_empty_reference_blocks_without_substitution(self):
        for value in (None, '', '  ', [], {}, False):
            with self.subTest(value=value):
                self.product['specifications']['use_evidence_ref'] = value
                result = assess_candidate(self.requirement, self.product)
                self.assertEqual(result['status'], 'needs_evidence')
                self.assertIn('product.specifications.use_evidence_ref', result['missing_evidence'])
                self.assertEqual(result['mismatches'], [])

    def test_evidence_presence_does_not_waive_material_or_use(self):
        for attribute, actual in (('material', 'gypsum board'),
                                  ('manufacturer_stated_use', 'floor tile backing')):
            with self.subTest(attribute=attribute):
                product = deepcopy(self.product)
                product['specifications'][attribute] = actual
                result = assess_candidate(self.requirement, product)
                self.assertEqual(result['status'], 'needs_approval')
                self.assertEqual(result['mismatches'][0]['attribute'], attribute)
        del self.product['specifications']['manufacturer_stated_use']
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')

    def test_literal_specifications_are_never_silently_reinterpreted(self):
        self.requirement['specifications']['use_evidence_ref'] = 'required from supplier product information'
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'needs_approval')
        self.assertEqual(result['mismatches'][0]['attribute'], 'use_evidence_ref')

    def test_malformed_evidence_requirement_is_unresolved(self):
        for attributes in ('use_evidence_ref', None, [''], [{}]):
            with self.subTest(attributes=attributes):
                self.requirement['evidence_attributes'] = attributes
                self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')


class VariantAndCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.requirement = {'id': 'pipe', 'revision': 1, 'quantity': 200, 'unit': 'linear_ft',
                            'source_text': 'One red and one blue 100-foot coil; match our fittings.',
                            'specifications': {'material': 'PEX'},
                            'variants': [{'id': color, 'quantity': 100, 'unit': 'linear_ft',
                                          'specifications': {'color': color, 'coil_length_ft': 100}}
                                         for color in ('red', 'blue')]}
        self.product = {'id': 'red-coil', 'revision': 1, 'unit': 'coil', 'pack_size': 1,
                        'minimum_quantity': 1, 'stock': 3, 'source': 'public-catalog',
                        'units_per_sale_unit': '100', 'requirement_unit': 'linear_ft',
                        'specifications': {'material': 'PEX', 'color': 'red', 'coil_length_ft': 100}}

    def test_variant_uses_product_facts_and_retains_one_source_group(self):
        self.product['variant'] = 'blue'  # an unsupported label cannot override facts
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['variant_id'], 'red')
        self.assertEqual(result['requirement_id'], 'pipe')
        self.assertEqual(result['quantity']['selling_quantity'], '1')
        self.assertEqual(result['quantity']['coverage_quantity'], '100')
        child = requirement_for_product(self.requirement, self.product)['requirement']
        self.assertEqual(child['source_text'], self.requirement['source_text'])
        self.assertEqual(child['quantity'], 100)
        self.assertNotIn('variants', child)
        self.assertEqual(assess_candidate(child, self.product)['variant_id'], 'red')

    def test_missing_unmatched_and_ambiguous_variant_are_not_eligible(self):
        del self.product['specifications']['color']
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')
        self.product['specifications']['color'] = 'green'
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'incompatible')
        self.product['specifications']['color'] = 'red'
        self.requirement['variants'][1]['specifications']['color'] = 'red'
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')

    def test_variant_total_cannot_drop_part_of_source_group(self):
        self.requirement['variants'].pop()
        result = assess_candidate(self.requirement, self.product)
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertIn('variant quantities must sum to the parent requirement quantity', result['missing_evidence'])

    def test_supplier_cannot_resolve_contractor_fitting_intent(self):
        self.product['specifications']['connection_system'] = 'Example expansion fittings'
        self.product['unresolved_clarifications'] = [
            {'key': 'fitting_system', 'owner': 'contractor', 'required_before_recommendation': True,
             'status': 'resolved', 'answer': 'Example expansion fittings'}]
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')
        self.requirement['specifications']['connection_system'] = 'Example expansion fittings'
        answer = {'value': 'Example expansion fittings', 'specification_attribute': 'connection_system',
                  'source_id': 'contractor-comment-1', 'validated': True}
        self.requirement['clarifications'] = {'fitting_system': answer}
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'suitable')
        answer['validated'] = False
        self.assertEqual(assess_candidate(self.requirement, self.product)['status'], 'needs_evidence')

    def tape(self):
        req = {'id': 'tape', 'revision': 1, 'quantity': 3, 'unit': 'roll', 'specifications': {},
               'compatibility': [{'requirement_id': 'wrap', 'product_attribute': 'approved_wrap_family',
                                  'related_attribute': 'product_family', 'evidence_attributes': ['approval_evidence_ref']}]}
        product = {'id': 'tape-a', 'revision': 1, 'unit': 'roll', 'pack_size': 1, 'minimum_quantity': 1,
                   'stock': 10, 'source': 'tape-catalog', 'related_requirements': ['wrap'],
                   'specifications': {'approved_wrap_family': 'Wrap A', 'approval_evidence_ref': 'fixture:approval-data'}}
        wrap = {'id': 'wrap-a', 'revision': 1, 'source': 'wrap-catalog',
                'specifications': {'product_family': 'Wrap A'}}
        return req, product, wrap

    def test_dependency_rechecks_exact_chosen_wrap_and_records_evidence(self):
        req, product, wrap = self.tape()
        result = assess_candidate(req, product, selected_products={'wrap': [wrap]})
        self.assertEqual(result['status'], 'suitable')
        self.assertEqual(result['compatibility']['checks'][0]['evidence']['approval_evidence_ref'], 'fixture:approval-data')
        wrap['specifications']['product_family'] = 'Wrap B'
        wrap['revision'] = 2
        result = assess_candidate(req, product, selected_products={'wrap': [wrap]})
        self.assertEqual(result['status'], 'incompatible')
        self.assertEqual(result['compatibility']['checks'][0]['related_product_revision'], 2)

    def test_missing_dependency_or_evidence_never_silently_matches(self):
        req, product, wrap = self.tape()
        self.assertEqual(assess_candidate(req, product)['status'], 'needs_evidence')
        del product['specifications']['approval_evidence_ref']
        self.assertEqual(assess_candidate(req, product, selected_products={'wrap': [wrap]})['status'], 'needs_evidence')
        req['compatibility'] = []
        self.assertIn('documented compatibility rule for wrap', assess_candidate(req, product)['missing_evidence'])

    def test_every_related_product_must_match_and_unknown_facts_stay_unknown(self):
        req, product, wrap = self.tape()
        other = {'id': 'other-wrap', 'source': 'other-catalog', 'specifications': {}}
        result = assess_candidate(req, product, selected_products={'wrap': [wrap, other]})
        self.assertEqual(result['status'], 'needs_evidence')
        other['specifications']['product_family'] = 'Wrap B'
        self.assertEqual(assess_candidate(req, product, selected_products={'wrap': [wrap, other]})['status'], 'incompatible')

    def test_documented_roof_use_scope_and_conditions_are_required(self):
        req = {'id': 'underlayment', 'revision': 1, 'quantity': 600, 'unit': 'sq_ft',
               'specifications': {'material': 'synthetic'},
               'compatibility': [{'requirement_id': 'roof',
                   'product_specifications': {'use': 'under architectural asphalt shingles'},
                   'related_specifications': {'material': 'asphalt', 'type': 'architectural shingles'},
                   'evidence_attributes': ['use_evidence_ref', 'installed_coverage_conditions']}]}
        product = {'id': 'underlayment-a', 'unit': 'roll', 'pack_size': 1, 'minimum_quantity': 1, 'stock': 4,
                   'units_per_sale_unit': 500, 'requirement_unit': 'sq_ft', 'source': 'public-catalog',
                   'related_requirements': ['roof'], 'specifications': {'material': 'synthetic',
                       'use': 'under architectural asphalt shingles', 'use_evidence_ref': 'fixture:roof-system',
                       'installed_coverage_conditions': 'Coverage accounts for documented laps.'}}
        roof = {'id': 'roof-a', 'source': 'public-catalog',
                'specifications': {'material': 'asphalt', 'type': 'architectural shingles'}}
        self.assertEqual(assess_candidate(req, product, selected_products={'roof': [roof]})['status'], 'suitable')
        del product['specifications']['installed_coverage_conditions']
        self.assertEqual(assess_candidate(req, product, selected_products={'roof': [roof]})['status'], 'needs_evidence')


if __name__ == '__main__':
    unittest.main()
