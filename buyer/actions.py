"""Validate Hermes-selected actions. This module chooses no tactics or prices.

Inputs must be trusted run state and saved supplier evidence. Validation is not a
transport: the caller must persist and deduplicate an action before sending it.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _records(value):
    return list(value.values()) if isinstance(value, dict) else list(value or ())


def _id(record):
    return record.get('id') or record.get('quote_id') or record.get('candidate_id')


def _number(value, field, allow_zero=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{field} must be a finite positive number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{field} must be a finite positive number') from None
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f'{field} must be a finite positive number')
    return result


def _time(value):
    if not isinstance(value, str):
        raise ValueError('source and expiry times must be ISO timestamps')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('source and expiry times must be ISO timestamps') from None
    if result.tzinfo is None:
        raise ValueError('timestamps require a timezone')
    return result


def _scope(record, run):
    if not run.get('run_id') or record.get('run_id') != run['run_id']:
        raise ValueError('run_id does not match the active run')
    revision = run.get('request_revision')
    if revision is None or record.get('request_revision') != revision:
        raise ValueError('request_revision is stale or missing')


def _current_offer(quote_id, run, offers):
    records = _records(offers)
    matches = [offer for offer in records if _id(offer) == quote_id]
    if not quote_id or len(matches) != 1:
        raise ValueError('quote identity is unknown or ambiguous')
    offer = matches[0]
    if offer.get('run_id') != run.get('run_id'):
        raise ValueError('quote belongs to a different run')
    if offer.get('request_revision', run.get('request_revision')) != run.get('request_revision'):
        raise ValueError('quote belongs to an old request revision')
    if offer.get('status') not in ('issued', 'confirmed') or offer.get('current') is False or offer.get('superseded_by'):
        raise ValueError('quote is not current and confirmed')
    if offer.get('valid') is False:
        raise ValueError('quote has invalid or unresolved terms')
    current_ids = run.get('current_quote_ids')
    if current_ids is not None and quote_id not in current_ids:
        raise ValueError('quote is not in the current quote set')
    for other in records:
        same_request = (offer.get('request_id') is not None and
                        other.get('request_id') == offer.get('request_id'))
        if other.get('previous_quote_id') == quote_id or (same_request and
                other.get('run_id') == offer.get('run_id') and
                other.get('vendor_id') == offer.get('vendor_id') and
                _number(other.get('revision', 1), 'quote revision') >
                _number(offer.get('revision', 1), 'quote revision')):
            raise ValueError('quote has been superseded')
    if not offer.get('expires_at'):
        raise ValueError('quote validity is unknown')
    now = _time(run['evaluated_at']) if run.get('evaluated_at') else datetime.now(timezone.utc)
    if _time(offer['expires_at']) <= now:
        raise ValueError('quote has expired')
    return offer


def _check_numbers(value):
    positive = {'quantity', 'target_total', 'total', 'unit_price', 'target_unit_price',
                'price', 'amount', 'proposed_total', 'competing_total', 'budget_cap'}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in positive:
                _number(item, key)
            elif key in ('delivery_days', 'max_delivery_days'):
                _number(item, key, allow_zero=True)
            if isinstance(item, (dict, list)):
                _check_numbers(item)
    elif isinstance(value, list):
        for item in value:
            _check_numbers(item)


def _comparable_package(offer, run, offers, decisions):
    """Validate the quoted subset and measure real requirement/variant coverage.

    Reuse buying-plan guards rather than trusting sale counts or stale candidate
    eligibility. A quote above budget can still be negotiated; the action's
    proposed target remains subject to the independent budget checks below.
    """
    from .planning import evaluate_plan

    raw = offer.get('raw', offer)
    included = {line.get('requirement_id') for line in raw.get('lines', [])}
    requirements = [r for r in _records(run.get('requirements')) if r.get('id') in included]
    if not included or {r.get('id') for r in requirements} != included:
        raise ValueError('competing package has unknown or missing requirement scope')
    scope = deepcopy(run)
    scope['requirements'] = requirements
    scope['quotes'] = _records(offers)
    scope['authority'] = dict(scope.get('authority') or {})
    scope['authority'].pop('budget_cap', None)
    scope['constraints'] = dict(scope.get('constraints') or {})
    scope['constraints'].pop('budget', None)
    revisions = {r['id']: r.get('revision', run.get('request_revision')) for r in requirements}
    scope['candidates'] = [c for c in _records(scope.get('candidates'))
        if c.get('current') is not False and not c.get('superseded_by')
        and c.get('run_id', run.get('run_id')) == run.get('run_id')
        and c.get('request_revision', run.get('request_revision')) == run.get('request_revision')
        and c.get('requirement_revision', revisions.get(c.get('requirement_id'))) == revisions.get(c.get('requirement_id'))]
    plan = evaluate_plan(scope, [offer], approvals=_records(decisions), now=run.get('evaluated_at'))
    if not plan['complete']:
        raise ValueError('competing package is not currently eligible: ' + '; '.join(plan['blockers'][:3]))
    coverage = {}
    for selected in plan['selected_offers']:
        for line in selected['lines']:
            assessment = line['assessment']
            product = assessment['product']
            if product.get('current') is False or product.get('superseded_by'):
                raise ValueError('competing package product is no longer current')
            if line.get('product_revision') is not None and line['product_revision'] != product.get('revision'):
                raise ValueError('competing quote refers to an old product revision')
            amount = _number(line['coverage_quantity'], 'normalized coverage')
            per_sale = amount / _number(line['quantity'], 'selling quantity')
            if (line.get('units_per_sale_unit') is not None and
                    _number(line['units_per_sale_unit'], 'quoted coverage per sale unit') != per_sale):
                raise ValueError('quoted coverage conversion conflicts with current product facts')
            if (line.get('covered_quantity') is not None and
                    _number(line['covered_quantity'], 'quoted covered quantity') != amount):
                raise ValueError('quoted covered quantity conflicts with current product facts')
            if line.get('requirement_unit') is not None and line['requirement_unit'] != line['coverage_unit']:
                raise ValueError('quoted requirement unit conflicts with current product facts')
            if line.get('variant') is not None and line['variant'] != assessment.get('variant_id'):
                raise ValueError('quoted variant conflicts with required product variant')
            key = (line['requirement_id'], assessment.get('variant_id') or '', line['coverage_unit'])
            coverage[key] = coverage.get(key, Decimal(0)) + amount
    return coverage, plan['total_basis']


def validate_action(action, run, offers, decisions):
    """Return a validated copy or raise ValueError; never send or select a move.

    `inquiry` is accepted as the supplier protocol spelling of `inquire`.
    Run authority must explicitly delegate supplier_inquiries/negotiation.
    Recommendation validation here is a scope check, not package feasibility;
    the caller must also use the deterministic package evaluator.
    """
    if not isinstance(action, dict) or not isinstance(run, dict):
        raise ValueError('action and run must be objects')
    _scope(action, run)
    if not isinstance(action.get('id'), str) or not action['id'].strip():
        raise ValueError('action needs an immutable id')
    kind = action.get('type')
    if kind == 'inquiry':
        kind = 'inquire'
    if kind not in ('inquire', 'counter', 'recommend'):
        raise ValueError('only inquire, counter, and recommend are permitted; no orders')
    if any(action.get(key) for key in ('place_order', 'accept_terms', 'commit', 'acceptance')):
        raise ValueError('orders and acceptance are outside buyer authority')
    for prior in _records(run.get('actions')):
        if _id(prior) == action['id']:
            raise ValueError('duplicate action id; reconcile the saved action instead')
    authority = run.get('authority') or {}
    permission = 'supplier_inquiries' if kind == 'inquire' else 'supplier_negotiation'
    if kind != 'recommend' and authority.get(permission) is not True:
        raise ValueError(f'{permission} is not delegated')
    remaining = run.get('remaining_actions')
    if remaining is not None and _number(remaining, 'remaining_actions', True) == 0:
        raise ValueError('action budget exhausted')
    if run.get('execution_deadline'):
        now = _time(run['evaluated_at']) if run.get('evaluated_at') else datetime.now(timezone.utc)
        if _time(run['execution_deadline']) <= now:
            raise ValueError('execution deadline reached')
    _check_numbers(action)
    vendor_id = action.get('vendor_id')
    supplier = None
    if kind != 'recommend' or vendor_id is not None:
        matches = [s for s in _records(run.get('suppliers')) if (s.get('id') or s.get('vendor_id')) == vendor_id]
        if not vendor_id or len(matches) != 1:
            raise ValueError('unknown or ambiguous supplier destination')
        supplier = matches[0]
        known_destinations = {supplier[k] for k in ('email', 'url', 'channel_id') if supplier.get(k)}
        for key in ('destination', 'to', 'email', 'url', 'channel_id'):
            if key in action and action[key] not in known_destinations:
                raise ValueError('destination does not match the configured supplier')
        if not isinstance(action.get('message'), str) or not action['message'].strip():
            raise ValueError('supplier action requires a message')
    previous = None
    if kind == 'counter' or action.get('previous_quote_id'):
        previous = _current_offer(action.get('previous_quote_id'), run, offers)
        if previous.get('vendor_id') != vendor_id:
            raise ValueError('counter references another supplier quote')
    quotes = []
    for quote_id in action.get('quote_ids', []):
        quotes.append(_current_offer(quote_id, run, offers))
    if action.get('quote_id'):
        quotes.append(_current_offer(action['quote_id'], run, offers))
    if kind == 'recommend' and not quotes:
        raise ValueError('recommendation needs current quote references')
    competing = action.get('competing_quote_ids', [])
    if action.get('competing_quote_id'):
        competing = [*competing, action['competing_quote_id']]
    comparison = _comparable_package(previous, run, offers, decisions) if previous and competing else None
    for quote_id in competing:
        alternative = _current_offer(quote_id, run, offers)
        if 'competing_total' in action and (len(competing) != 1 or
                _number(action['competing_total'], 'competing_total') !=
                _number(alternative.get('total'), 'competing quote total')):
            raise ValueError('claimed competing total does not match its confirmed quote')
        if alternative.get('vendor_id') == vendor_id:
            raise ValueError('competing quote must come from another supplier')
        alternative_comparison = _comparable_package(alternative, run, offers, decisions)
        if comparison:
            if comparison != alternative_comparison:
                raise ValueError('competing quote does not cover the same requirement quantities, variants, and tax basis')
            if previous.get('currency') != alternative.get('currency'):
                raise ValueError('competing quote currency differs')
    if 'competing_total' in action and not competing:
        raise ValueError('claimed competing total needs a confirmed quote reference')
    requirements = {r.get('id') or r.get('requirement_id'): r for r in _records(run.get('requirements'))}
    for line in action.get('items', action.get('lines', [])):
        if line.get('requirement_id') not in requirements:
            raise ValueError('action names an unknown requirement')
        if 'quantity' in line:
            _number(line['quantity'], 'quantity')
        if line.get('product_id'):
            known = [c for c in _records(run.get('candidates'))
                     if c.get('product_id') == line['product_id'] and c.get('requirement_id') == line['requirement_id']]
            quoted = [l for q in _records(offers) if q.get('run_id') == run['run_id']
                      for l in q.get('lines', []) if l.get('product_id') == line['product_id']
                      and l.get('requirement_id') == line['requirement_id']]
            if not known and not quoted:
                raise ValueError('action names a product without candidate or quote evidence')
    for decision_id in action.get('decision_refs', []):
        matches = [d for d in _records(decisions) if _id(d) == decision_id]
        if len(matches) != 1:
            raise ValueError('unknown decision reference')
        decision = matches[0]
        _scope(decision, run)
        if decision.get('validated') is not True or decision.get('decision') != 'approved':
            raise ValueError('decision reference is not a validated approval')
        if decision.get('quote_id'):
            _current_offer(decision['quote_id'], run, offers)
    cap = authority.get('budget_cap')
    if cap is not None:
        limit = _number(cap, 'budget_cap')
        for field in ('target_total', 'total', 'proposed_total'):
            if field in action:
                if action.get('currency') != authority.get('currency') or not authority.get('currency'):
                    raise ValueError('action currency must match the explicit budget currency')
                if _number(action[field], field) > limit:
                    raise ValueError('action exceeds the explicit hard budget')
        proposed_lines = action.get('items', action.get('lines', []))
        priced_lines = [line for line in proposed_lines if 'unit_price' in line or 'target_unit_price' in line]
        if priced_lines:
            if action.get('currency') != authority.get('currency') or not authority.get('currency'):
                raise ValueError('proposed line prices need the budget currency')
            line_cost = sum((_number(line.get('quantity'), 'quantity') *
                             _number(line.get('target_unit_price', line.get('unit_price')), 'unit_price')
                             for line in priced_lines), Decimal(0))
            if line_cost > limit:
                raise ValueError('proposed line prices exceed the explicit hard budget')
        if kind == 'recommend':
            if len({_id(quote) for quote in quotes}) != len(quotes):
                raise ValueError('recommendation repeats a quote')
            if any(q.get('currency') != authority.get('currency') for q in quotes):
                raise ValueError('recommended quotes do not match the budget currency')
            if sum((_number(q.get('total'), 'quote total') for q in quotes), Decimal(0)) > limit:
                raise ValueError('recommended quotes exceed the explicit hard budget')
    result = deepcopy(action)
    result['type'] = kind
    result['validated'] = True
    result['is_commitment'] = False
    return result
