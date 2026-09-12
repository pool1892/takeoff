#!/usr/bin/env python3
"""Hermes procurement tools. Input is JSON from a local file or stdin.

Examples: python /workspace/buyer/cli.py --task-id UUID snapshot
          python /workspace/buyer/cli.py --task-id UUID send --input inquiry.json
All mutations persist before transmission. Commands never place orders.
"""
from copy import deepcopy
from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations' / 'ambiguous'))
from buyer import store
from bridge import API, BridgeError, NoRedirect, safe_reply


def comment(api, state, persist, action_id, content, parent_id=None):
    """Reconcile uncertain comments; never blindly repeat a non-idempotent POST."""
    records = state.setdefault('publications', {})
    body = {'content': safe_reply(content)}
    if parent_id:
        body['parent_id'] = parent_id
    prior = records.get(action_id)
    if prior:
        if prior['body'] != body:
            raise ValueError('Publication ID was already used for different content')
        if prior.get('remote_id'):
            return prior['remote_id']
        def recent(c):
            try:
                return datetime.fromisoformat(c['created_at'].replace('Z', '+00:00')) >= datetime.fromisoformat(prior['at'].replace('Z', '+00:00'))
            except (KeyError, ValueError, TypeError):
                return False
        matches = [c for c in comments(api, state['task_id'])
                   if (c.get('author') or {}).get('id') == state['agent_id']
                   and c.get('content') == body['content']
                   and c.get('parent_id') == parent_id and not c.get('deleted_at')
                   and not c.get('edited_at') and recent(c)]
        if len(matches) != 1:
            raise ValueError('Comment delivery uncertain; reconcile before retrying')
        prior['remote_id'] = matches[-1]['id']
        persist()
        return prior['remote_id']
    records[action_id] = {'body': body, 'status': 'sending', 'at': store.now()}
    persist()
    sent = api.call(f"/api/tasks/{state['task_id']}/comments", 'POST', body)
    if not sent.get('id'):
        raise ValueError('Comment response lacks a confirmed ID')
    records[action_id].update(status='sent', remote_id=sent['id'])
    persist()
    return sent['id']


def comments(api, task_id):
    result, offset = [], 0
    while True:
        page = api.call(f'/api/tasks/{task_id}/comments', limit=100, offset=offset)
        rows = page.get('data', [])
        for row in rows:
            result.append(row)
            result.extend(row.get('replies') or [])
        if not page.get('has_more'):
            return result
        if not rows:
            raise ValueError('Task comment pagination did not advance')
        offset += len(rows)


def json_objects(text):
    decoder = json.JSONDecoder()
    for pos, char in enumerate(text):
        if char in '{[':
            try:
                yield decoder.raw_decode(text[pos:])[0]
            except (ValueError, RecursionError):
                continue


def contains(value, target):
    if value == target:
        return True
    if isinstance(value, dict):
        return any(contains(v, target) for v in value.values())
    if isinstance(value, list):
        return any(contains(v, target) for v in value)
    return False


def all_products(value):
    if isinstance(value, dict):
        if isinstance(value.get('products'), list):
            yield from value['products']
        for key, child in value.items():
            if key != 'products':
                yield from all_products(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_products(child)


def execute(command, payload, state, persist, api):
    if not state:
        raise ValueError('Task has not been admitted by the procurement listener')
    if state.get('paused') and command not in ('snapshot', 'publish'):
        raise ValueError('Task is paused or its source changed; await reconciliation')
    if command == 'snapshot':
        return state
    if command == 'requirements':
        requirements = payload['requirements']
        if not isinstance(requirements, list) or not requirements:
            raise ValueError('Provide requirements derived from the original source')
        ids = [r.get('id') for r in requirements]
        if len(set(ids)) != len(ids) or any(not x for x in ids):
            raise ValueError('Requirements need unique IDs')
        for requirement in requirements:
            if not requirement.get('source_text') or not requirement.get('unit'):
                raise ValueError('Preserve source text and explicit quantity unit for each requirement')
            requirement['revision'] = state['request_revision']
            requirement['run_id'] = state['run_id']
            requirement['request_revision'] = state['request_revision']
        if state.get('requirements') and state['requirements'] != requirements:
            raise ValueError('Existing requirements are immutable within this request revision')
        if state.get('requirements') and payload.get('constraints', state.get('constraints', {})) != state.get('constraints', {}):
            raise ValueError('Existing constraints cannot change without contractor evidence')
        state['requirements'] = requirements
        state['constraints'] = payload.get('constraints', state.get('constraints', {}))
        if payload.get('budget_cap') is not None:
            from decimal import Decimal
            cap = Decimal(str(payload['budget_cap']))
            if not cap.is_finite() or cap <= 0:
                raise ValueError('Budget must be positive and finite')
            state['authority']['budget_cap'] = str(cap)
        store.event(state, 'requirements', requirements)
        persist()
        return {'recorded': len(requirements)}
    if command == 'clarify':
        from bridge import CONTRACTOR
        requirement = next(r for r in state['requirements'] if r['id'] == payload['requirement_id'])
        source = state.get('evidence', {}).get(payload['source_id'], {})
        actual = source.get('data', {})
        if (source.get('channel') != 'contractor_comment' or (actual.get('author') or {}).get('id') != CONTRACTOR
                or actual.get('deleted_at') or actual.get('edited_at')
                or actual.get('updated_at') not in (None, actual.get('created_at'))):
            raise ValueError('Clarification requires the current unedited contractor comment')
        key, attribute, value = payload['key'], payload['specification_attribute'], payload['value']
        if key not in ('facing', 'fitting_system') or attribute != {'facing': 'facing', 'fitting_system': 'connection_system'}[key]:
            raise ValueError('Clarify currently supports the documented facing and fitting essentials')
        if not isinstance(value, str) or not value.strip() or value.casefold() not in actual.get('content', '').casefold():
            raise ValueError('Clarification value must be explicitly present in the contractor answer')
        existing = requirement.setdefault('clarifications', {}).get(key)
        if existing:
            if existing.get('source_id') == payload['source_id'] and existing.get('value') == value:
                return existing
            raise ValueError('A different clarification requires reconciliation of its earlier answer')
        record = {'value': value, 'specification_attribute': attribute, 'source_id': payload['source_id'],
                  'validated': True, 'prior_specification': requirement.get('specifications', {}).get(attribute)}
        requirement['clarifications'][key] = record
        requirement.setdefault('specifications', {})[attribute] = value
        requirement['missing_essentials'] = [m for m in requirement.get('missing_essentials', []) if m != key]
        requirement['revision'] = requirement.get('revision', 1) + 1
        store.event(state, 'clarification', {'requirement_id': requirement['id'], 'key': key, 'source_id': payload['source_id']})
        persist()
        return record
    if command == 'catalog':
        url = payload['url']
        parsed = urllib.parse.urlsplit(url)
        allowed = {urllib.parse.urlsplit(u).hostname for u in state.get('catalog_urls', [])}
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('Catalog URL must use the configured public HTTPS supplier host')
        request = urllib.request.Request(url, headers={'Accept': 'application/json', 'ngrok-skip-browser-warning': 'takeoff'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Catalog exceeds the supported response size')
        data = json.loads(raw)
        source_id = 'catalog_' + store.digest({'url': url, 'data': data})[:20]
        state.setdefault('evidence', {})[source_id] = {'id': source_id, 'channel': 'website', 'url': url,
            'observed_at': store.now(), 'data': data, 'mode': 'live_remote_simulated_business'}
        products = list(all_products(data))
        for product in products:
            if isinstance(product, dict) and product.get('id'):
                p = deepcopy(product)
                p.setdefault('source', source_id)
                p.setdefault('revision', store.digest(product)[:16])
                state.setdefault('products', {})[p['id']] = p
        store.event(state, 'catalog', {'source_id': source_id, 'products': len(products)})
        persist()
        return {'source_id': source_id, 'data': data}
    if command == 'assess':
        from buyer.discovery import assess_candidate
        requirement = next(r for r in state['requirements'] if r['id'] == payload['requirement_id'])
        product = state['products'][payload['product_id']]
        cid = 'candidate_' + store.digest([requirement['id'], product['id'], product.get('revision')])[:20]
        assessment = assess_candidate(requirement, product, state.get('approvals', []))
        candidate = {**assessment, 'id': cid, 'candidate_id': cid, 'run_id': state['run_id'],
            'request_revision': state['request_revision'], 'requirement_id': requirement['id'],
            'product_id': product['id'], 'product_revision': product['revision'], 'product': product,
            'assessment': assessment}
        state.setdefault('candidates', {})[cid] = candidate
        persist()
        return candidate
    if command == 'send':
        from buyer.actions import validate_action
        action_id = store.identifier(payload['id'])
        prior = state.setdefault('actions', {}).get(action_id)
        if prior:
            if prior['input'] != payload:
                raise ValueError('Action ID cannot be reused with a different payload')
            if prior.get('result'):
                result = prior['result']
                return {'action_id': action_id, 'mail_id': result.get('id'), 'delivery_status': result.get('delivery_status')}
            body = prior['body']
        else:
            action = validate_action(payload, state, current_quotes(state), state.get('approvals', []))
            if action['type'] not in ('inquire', 'counter'):
                raise ValueError('Send permits inquiries and counters only')
            supplier = next(s for s in state['suppliers'] if s['id'] == action['vendor_id'])
            envelope = {'schema_version': 'takeoff.supplier.v1', 'type': 'inquiry' if action['type'] == 'inquire' else 'counter',
                'run_id': state['run_id'], 'vendor_id': supplier['id'], 'message': safe_reply(action['message']), 'request_id': action_id}
            for key in ('previous_quote_id', 'target_total', 'currency', 'items'):
                if key in action:
                    envelope[key] = action[key]
            body = {'to': [supplier['email']], 'subject': f"Takeoff {state['run_id']} {action_id}",
                'body_text': json.dumps(envelope), 'idempotency_key': 'takeoff-' + state['task_id'] + '-' + action_id,
                'undo_send_seconds': 0, 'include_signature': False}
            state['actions'][action_id] = {'id': action_id, 'input': payload, 'body': body, 'status': 'sending', 'at': store.now()}
            state['remaining_actions'] = state.get('remaining_actions', 40) - 1
            persist()
        result = api.call('/api/mail/send', 'POST', body)
        state['actions'][action_id].update(result=result, status=result.get('delivery_status', 'unknown'))
        store.event(state, 'supplier_send', {'action_id': action_id, 'delivery_status': result.get('delivery_status'), 'mail_id': result.get('id')})
        persist()
        return {'action_id': action_id, 'mail_id': result.get('id'), 'delivery_status': result.get('delivery_status')}
    if command == 'offer':
        from buyer.quotes import normalize_quote
        source = state['evidence'][payload['source_id']]
        quote = payload['quote']
        trees = [source['data']] if 'data' in source else list(json_objects(source.get('body', '')))
        if not any(contains(tree, quote) for tree in trees):
            raise ValueError('Quote must be an exact supplier JSON object preserved in source evidence')
        if quote.get('run_id') != state['run_id'] or quote.get('vendor_id') != source.get('vendor_id', quote.get('vendor_id')):
            raise ValueError('Quote run or supplier does not match the source')
        qid = store.identifier(quote.get('quote_id', quote.get('id')))
        existing = state.setdefault('quotes', {}).get(qid)
        if existing and existing != quote:
            raise ValueError('Quote identity already has different terms; obtain a new revision')
        state['quotes'][qid] = deepcopy(quote)
        state.setdefault('quote_sources', {})[qid] = source['id']
        store.event(state, 'quote', {'quote_id': qid, 'source_id': source['id']})
        persist()
        return normalize_quote(quote, evidence=source)
    if command == 'decision':
        from buyer.decisions import validate_proposal
        proposal = deepcopy(payload['proposal'])
        pid = store.identifier(proposal['id'])
        if proposal.get('run_id') != state['run_id'] or proposal.get('request_revision') != state['request_revision']:
            raise ValueError('Decision is not scoped to the current request')
        prior = state.setdefault('proposals', {}).get(pid)
        if prior:
            if prior.get('input') != payload:
                raise ValueError('Proposal ID cannot be reused with a different payload')
            if prior.get('question_comment_id'):
                return prior
            proposal = prior
        if not proposal.get('changed_attributes') or not proposal.get('product_id'):
            raise ValueError('Describe an exact product attribute substitution')
        if not prior:
            proposal.update(created_at=store.now(), status='pending')
            proposal = validate_proposal(proposal, state, current_quotes(state), state.get('candidates', {}))
            proposal['input'] = deepcopy(payload)
            state['proposals'][pid] = proposal
            persist()
        scope = {key: proposal[key] for key in ('requirement_id', 'product_id', 'changed_attributes',
                 'quote_id', 'quote_revision', 'candidate_id', 'product_revision') if key in proposal}
        content = payload['question'] + '\n\nExact proposed change:\n```json\n' + json.dumps(scope, indent=2) + '\n```'
        content += f"\n\nReply to this comment with **Approve {pid}** or **Reject {pid}**. I’ll keep working on the other materials."
        proposal['question_comment_id'] = comment(api, state, persist, 'decision-' + pid, content)
        state['proposals'][pid] = proposal
        persist()
        return proposal
    if command == 'plan':
        from buyer.planning import evaluate_plan
        result = evaluate_plan(state, payload['quote_ids'], candidates=state.get('candidates', {}), approvals=state.get('approvals', []))
        state['plan'] = result
        store.event(state, 'plan', result)
        persist()
        return result
    if command == 'publish':
        if payload.get('plan'):
            from buyer.explanation import explain_plan
            from buyer.planning import evaluate_plan
            if not state.get('plan'):
                raise ValueError('Evaluate the plan before publishing')
            state['plan'] = evaluate_plan(state, [q['quote_id'] for q in state['plan']['selected_offers']],
                candidates=state.get('candidates', {}), approvals=state.get('approvals', []))
            content = explain_plan(state['plan'])
        else:
            content = payload['content']
        remote_id = comment(api, state, persist, store.identifier(payload['id']), content)
        if payload.get('final'):
            if not payload.get('plan') or not state['plan'].get('complete'):
                raise ValueError('Only a currently complete evaluated plan can finish the task')
            api.call(f"/api/tasks/{state['task_id']}", 'PATCH', {'status': 'done'})
            state['phase'] = 'complete'
            store.event(state, 'task_completed', {'comment_id': remote_id})
            persist()
        return {'comment_id': remote_id}
    raise ValueError('Unknown tool command')


def current_quotes(state):
    from buyer.quotes import normalize_quote
    return [normalize_quote(q, evidence=state.get('evidence', {}).get(state.get('quote_sources', {}).get(qid)))
            for qid, q in state.get('quotes', {}).items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('command', choices=['snapshot', 'requirements', 'clarify', 'catalog', 'assess', 'send', 'offer', 'decision', 'plan', 'publish'])
    parser.add_argument('--input', help='JSON file; omit for JSON stdin, except snapshot')
    args = parser.parse_args()
    if os.environ.get('TAKEOFF_SANDBOX') != '1' or not Path('/.dockerenv').exists():
        raise ValueError('Run procurement tools inside the isolated Hermes container')
    payload = {} if args.command == 'snapshot' else json.loads(Path(args.input).read_text() if args.input else sys.stdin.read())
    with store.transaction(args.task_id) as (state, persist):
        print(json.dumps(execute(args.command, payload, state, persist, API()), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, StopIteration, OSError, BridgeError) as error:
        print(json.dumps({'error': safe_reply(str(error))}), file=sys.stderr)
        sys.exit(1)
