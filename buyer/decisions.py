"""Validate an explicit contractor answer against its exact current proposal.

The integration must fetch the authoritative comment itself. Never pass a source
object fabricated by Hermes or the supplier; this pure helper cannot authenticate
an API response. Thread resolution is deliberately not an approval signal.
"""
from copy import deepcopy

from .actions import _check_numbers, _current_offer, _id, _records, _scope, _time

CONTRACTOR_ID = '9df6ad27-165e-4534-8e26-800b5a33ab6a'


def validate_proposal(proposal, run, offers=(), candidates=()):
    """Check a proposed substitution before publication; grant no permission.

    Catalog facts must come from a current assessed candidate or the saved public
    product snapshot. A quote line's product ID alone proves no specification.
    """
    if not isinstance(proposal, dict) or not isinstance(run, dict):
        raise ValueError('proposal and run must be objects')
    if any(key in proposal for key in ('decision', 'validated', 'approved_specifications', 'source')):
        raise ValueError('a proposal cannot contain approval or contractor-answer fields')
    _scope(proposal, run)
    if not isinstance(proposal.get('id'), str) or not proposal['id'].strip():
        raise ValueError('proposal needs an immutable id')
    if proposal.get('status', 'pending') != 'pending':
        raise ValueError('proposal is not pending')
    requirements = [r for r in _records(run.get('requirements'))
                    if (r.get('id') or r.get('requirement_id')) == proposal.get('requirement_id')]
    if len(requirements) != 1 or not proposal.get('product_id'):
        raise ValueError('proposal needs a known requirement and product')
    requirement = requirements[0]
    revision = requirement.get('revision', run['request_revision'])
    if proposal.get('requirement_revision', revision) != revision:
        raise ValueError('proposal requirement revision is stale')
    changes = proposal.get('changed_attributes')
    if not isinstance(changes, dict) or not changes or any(value is None for value in changes.values()):
        raise ValueError('proposal needs exact, known changed attributes')
    _check_numbers(changes)
    quote_id, candidate_id = proposal.get('quote_id'), proposal.get('candidate_id')
    if bool(quote_id) == bool(candidate_id):
        raise ValueError('proposal must bind exactly one current quote or candidate')
    if quote_id:
        quote = _current_offer(quote_id, run, offers)
        if proposal.get('quote_revision') != quote.get('revision', 1):
            raise ValueError('proposal must bind the exact current quote revision')
        if not any(line.get('product_id') == proposal['product_id'] and
                   line.get('requirement_id') == proposal['requirement_id'] for line in quote.get('lines', [])):
            raise ValueError('proposal product and requirement are absent from the quote')
    matching = [c for c in _records(candidates) if
                c.get('product_id') == proposal['product_id'] and
                c.get('requirement_id') == proposal['requirement_id'] and
                (not candidate_id or _id(c) == candidate_id)]
    current_products = [p for p in _records(run.get('products')) if p.get('id') == proposal['product_id']]
    if candidate_id and len(matching) != 1:
        raise ValueError('unknown or ambiguous candidate')
    if len(matching) > 1:
        if len(current_products) == 1:
            matching = [c for c in matching if c.get('product_revision') == current_products[0].get('revision')]
        if len(matching) != 1:
            raise ValueError('candidate evidence is ambiguous; reassess the current product')
    if matching:
        candidate = matching[0]
        _scope(candidate, run)
        assessment = candidate.get('assessment', candidate)
        if candidate.get('current') is False or candidate.get('superseded_by'):
            raise ValueError('candidate is no longer current')
        if candidate.get('requirement_revision', revision) != revision:
            raise ValueError('candidate requirement revision is stale')
        if assessment.get('status') not in ('needs_approval', 'approved_substitution'):
            raise ValueError('candidate lacks confirmed substitution evidence')
        if candidate.get('product_revision') in (None, '', 'unknown'):
            raise ValueError('candidate needs a known current product revision')
        if current_products and candidate.get('product_revision') != current_products[0].get('revision'):
            raise ValueError('candidate is based on an old public product revision')
        if candidate_id and proposal.get('product_revision') != candidate.get('product_revision'):
            raise ValueError('proposal needs the current product revision')
        mismatches = {item.get('attribute'): item.get('actual') for item in assessment.get('mismatches', [])}
        if changes != mismatches:
            raise ValueError('changed attributes do not match the candidate evidence')
    elif not candidate_id and len(current_products) == 1:
        product = current_products[0]
        from .discovery import assess_candidate
        assessment = assess_candidate(requirement, product)
        mismatches = {item.get('attribute'): item.get('actual') for item in assessment['mismatches']}
        if assessment['status'] != 'needs_approval' or changes != mismatches:
            raise ValueError('changed attributes do not match the current public product evidence')
    else:
        raise ValueError('assess the current product before proposing its substitution')
    result = deepcopy(proposal)
    result['requirement_revision'] = revision
    result['proposal_validated'] = True
    return result


def validate_decision(answer, proposal, run, offers=(), candidates=(), existing_decisions=()):
    """Return a scoped approved/rejected record, or raise ValueError.

    Answers repeat proposal scope exactly. `source` is supplied by the trusted
    transport, containing immutable id, author_id, created_at. No answer,
    implicit assent, edited comments, stale offers, and duplicates are rejected.
    """
    if not isinstance(answer, dict):
        raise ValueError('answer must be an object')
    checked = validate_proposal(proposal, run, offers, candidates)
    _scope(answer, run)
    if answer.get('proposal_id') != proposal['id']:
        raise ValueError('answer does not identify the exact proposal')
    if not isinstance(answer.get('id'), str) or not answer['id'].strip():
        raise ValueError('decision needs an immutable id')
    if answer.get('choice') not in ('approve', 'reject'):
        raise ValueError('an explicit approve or reject choice is required')
    if answer.get('conditions') or answer.get('conditional'):
        raise ValueError('conditional answers require a new concrete proposal')
    for field in ('requirement_id', 'product_id', 'changed_attributes'):
        if answer.get(field) != proposal.get(field):
            raise ValueError(f'answer {field} does not match the exact proposal')
    source = answer.get('source')
    if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not source['id'].strip():
        raise ValueError('answer needs an immutable source comment id')
    if run.get('contractor_id', CONTRACTOR_ID) != CONTRACTOR_ID or source.get('author_id') != CONTRACTOR_ID:
        raise ValueError('only the actual contractor can answer this proposal')
    answered_at = _time(source.get('created_at'))
    if source.get('deleted_at') or source.get('edited_at') or source.get('updated_at') not in (None, source['created_at']):
        raise ValueError('edited or deleted answers require a new explicit comment')
    if proposal.get('created_at') and answered_at < _time(proposal['created_at']):
        raise ValueError('answer predates the proposal')
    if proposal.get('expires_at') and answered_at >= _time(proposal['expires_at']):
        raise ValueError('answer arrived after proposal expiry')
    for prior in _records(existing_decisions):
        if (_id(prior) == answer['id'] or (prior.get('source') or {}).get('id') == source['id'] or
                prior.get('proposal_id') == proposal['id']):
            raise ValueError('duplicate or previously answered proposal; preserve the existing decision')
    fields = ('quote_id', 'quote_revision') if proposal.get('quote_id') else ('candidate_id', 'product_revision')
    for field in fields:
        if answer.get(field) != proposal.get(field):
            raise ValueError(f'answer {field} does not match the proposal')
    reference = {field: proposal[field] for field in fields}
    result = {key: deepcopy(proposal[key]) for key in
              ('run_id', 'request_revision', 'requirement_id', 'product_id', 'changed_attributes')}
    result.update(id=answer['id'], proposal_id=proposal['id'], requirement_revision=checked['requirement_revision'],
                  decision='approved' if answer['choice'] == 'approve' else 'rejected',
                  approved_specifications=deepcopy(proposal['changed_attributes']) if answer['choice'] == 'approve' else {},
                  source=deepcopy(source), evidence_refs=[source['id']], validated=True, **reference)
    result['proposal'] = deepcopy(proposal)
    return result
