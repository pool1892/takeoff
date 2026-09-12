#!/usr/bin/env python3
"""Concise state-derived contractor progress DMs, without a model call."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from bridge import API, BridgeError, CONTRACTOR, WORKSPACE, identifier
except ModuleNotFoundError:
    from integrations.ambiguous.bridge import API, BridgeError, CONTRACTOR, WORKSPACE, identifier
from buyer import store
from buyer.quotes import normalize_quote

MIN_INTERVAL = 60


def values(items):
    return list(items.values()) if isinstance(items, dict) else list(items or [])


def has_products(data):
    if isinstance(data, dict):
        if isinstance(data.get('products'), list) and any(isinstance(p, dict) and p.get('id') for p in data['products']):
            return True
        return any(has_products(value) for key, value in data.items() if key != 'products')
    if isinstance(data, list):
        return any(has_products(value) for value in data)
    return False


def overview(state, now=None):
    """Read only confirmed records; never include supplier prose, raw errors or proposed prices."""
    now = time.time() if now is None else now
    requirements = values(state.get('requirements'))
    known_ids = {r['id'] for r in requirements if r.get('id')}
    checked = {c.get('requirement_id') for c in values(state.get('candidates'))
               if c.get('requirement_id') in known_ids and c.get('assessment')}
    products = values(state.get('products'))
    evidence = state.get('evidence', {})
    catalogs = {e.get('url') for e in evidence.values()
                if e.get('channel') == 'website' and e.get('url') and has_products(e.get('data'))}
    supplier_ids = {s['id'] for s in state.get('suppliers', []) if s.get('id')}
    sent = {a.get('input', {}).get('vendor_id') for a in values(state.get('actions'))
            if a.get('status') in ('sent', 'delivered') and a.get('result', {}).get('id')}
    sent &= supplier_ids
    replied = {e.get('vendor_id') for e in evidence.values()
               if e.get('channel') == 'supplier_email' and not e.get('unavailable')}
    replied &= supplier_ids
    quotes = 0
    for qid, quote in state.get('quotes', {}).items():
        source_id = state.get('quote_sources', {}).get(qid)
        source = evidence.get(source_id)
        if not source or source.get('unavailable') or quote.get('run_id') != state.get('run_id'):
            continue
        try:
            normalized = normalize_quote(quote, evidence=source, now=datetime.fromtimestamp(now, timezone.utc))
            quotes += bool(normalized.get('valid'))
        except (ValueError, TypeError, KeyError):
            continue
    missing = {key for req in requirements for key in req.get('missing_essentials', [])}
    details = []
    if 'facing' in missing:
        details.append('insulation facing')
    if 'fitting_system' in missing:
        details.append('PEX fitting system')
    if missing - {'facing', 'fitting_system'}:
        details.append('other material details')
    approvals = sum(1 for p in values(state.get('proposals'))
                    if p.get('status') == 'pending' and p.get('question_comment_id')
                    and p.get('run_id') == state.get('run_id')
                    and p.get('request_revision') == state.get('request_revision'))
    plan = state.get('plan') or {}
    complete = state.get('phase') == 'complete' and plan.get('complete') is True and not plan.get('blockers')
    paused = state.get('paused') or state.get('phase') in ('failed', 'blocked', 'interrupted', 'source_changed')
    if complete:
        stage, next_step = 'complete', 'Your buying recommendation is ready in the task. No order has been placed.'
    elif paused:
        stage, next_step = 'paused', 'I need to resolve an issue before continuing; the work recorded so far is preserved.'
    elif approvals:
        stage, next_step = 'approval', 'A product change needs your decision in the task; I’m continuing with the other materials.'
    elif details:
        stage, next_step = 'details', 'The material details below need confirmation while I work on the rest of the package.'
    elif sent - replied:
        stage, next_step = 'replies', 'I’m waiting for supplier replies, then I’ll compare complete delivered prices.'
    elif quotes:
        stage, next_step = 'comparing', 'I’m comparing the delivered offers and checking the next useful negotiation step.'
    elif replied:
        stage, next_step = 'reviewing', 'I’m checking the supplier replies and following up on anything needed for complete quotes.'
    else:
        stage, next_step = 'discovery', 'I’m matching the material list to supplier catalogs before requesting comparable offers.'
    data = {'requirements': len(known_ids), 'checked': len(checked), 'products': len(products),
            'catalogs': len(catalogs), 'suppliers': len(supplier_ids), 'sent': len(sent),
            'replied': len(replied), 'quotes': quotes, 'details': details, 'approvals': approvals,
            'stage': stage, 'complete': complete}
    lines = ['Bill, here’s where your material request stands.']
    if known_ids:
        discovery = f'{len(products)} products found'
        if catalogs:
            discovery += f' across {len(catalogs)} catalogs'
        lines.append(f'Materials: {len(checked)} of {len(known_ids)} reviewed against product facts; ' + discovery + '.')
    else:
        lines.append('I’ve started reviewing your material list and organizing the requirements.')
    lines.append(f'Suppliers: contacted {len(sent)} of {len(supplier_ids)}; '
                 f'heard back from {len(replied)}; {quotes} current quotes checked.')
    if details:
        lines.append('Details to confirm: ' + ', '.join(details) + '.')
    if approvals:
        lines.append(f'Decisions waiting for you: {approvals} product change' + ('s.' if approvals != 1 else '.'))
    lines.append(next_step)
    lines.append('[View the task](https://app.ambiguous.ai/tasks?task=' + identifier(state['task_id']) + ')')
    return data, '\n\n'.join(lines)


def dm_channel(api, agent_id):
    page = api.call('/api/channels')
    if page.get('has_more'):
        raise BridgeError('Progress channel listing is incomplete')
    eligible = []
    for row in page.get('data', []):
        if row.get('type') != 'dm' or row.get('archived_at'):
            continue
        detail = api.call('/api/channels/' + identifier(row['id']))
        if detail.get('type') == 'dm' and {m.get('user_id') for m in detail.get('members', [])} == {CONTRACTOR, agent_id}:
            eligible.append(identifier(row['id']))
    if len(eligible) != 1:
        raise BridgeError('A unique contractor DM is required for progress')
    return eligible[0]


def reconcile(api, entry, agent_id):
    matches, cursor, seen = {}, None, set()
    for _ in range(10):
        query = {'limit': 100}
        if cursor:
            query['cursor'] = cursor
        page = api.call('/api/channels/' + entry['channel_id'] + '/messages', **query)
        for row in page.get('data', []):
            try:
                at = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')).timestamp()
            except (KeyError, TypeError, ValueError):
                continue
            if (at >= entry['attempted_at'] and (row.get('author') or {}).get('id') == agent_id
                    and row.get('content') == entry['body']['content'] and not row.get('deleted_at')
                    and not row.get('edited_at')):
                matches[row['id']] = row
        if not page.get('has_more'):
            break
        cursor = page.get('next_cursor')
        if not cursor or cursor in seen:
            raise BridgeError('Progress reconciliation pagination did not advance')
        seen.add(cursor)
    else:
        raise BridgeError('Progress reconciliation exceeded its bound')
    if len(matches) == 1:
        entry.update(status='sent', remote_id=next(iter(matches)), sent_at=entry['attempted_at'])
        return True
    entry['status'] = 'uncertain'
    return False


def notify_progress(api, state, persist, agent_id=None, now=None):
    """Best effort. Call under the run transaction; never retry an uncertain POST."""
    now = time.time() if now is None else now
    try:
        agent_id = identifier(agent_id or state['agent_id'])
        metrics, body = overview(state, now)
        key = store.digest(metrics)
        journal = state.setdefault('progress_notifications', {'records': {}})
        records = journal['records']
        # Resolve an unknown delivery before publishing another overview.
        for entry in records.values():
            if entry.get('status') in ('sending', 'uncertain'):
                if metrics['complete'] and not entry.get('metrics', {}).get('complete'):
                    continue
                if now - entry.get('checked_at', entry['attempted_at']) < MIN_INTERVAL:
                    return {'status': 'pending_reconciliation'}
                entry['checked_at'] = now
                persist()
                if reconcile(api, entry, agent_id):
                    journal['last_sent_at'] = entry['sent_at']
                persist()
                if entry['status'] != 'sent':
                    return {'status': 'pending_reconciliation'}
        existing = records.get(key)
        if existing and existing.get('status') == 'sent':
            return {'status': 'unchanged'}
        latest = journal.get('last_sent_at')
        if latest is not None and not metrics['complete'] and now - latest < MIN_INTERVAL:
            return {'status': 'throttled'}
        if existing and now - existing.get('last_attempt_at', 0) < MIN_INTERVAL:
            return {'status': 'throttled'}
        if existing and existing.get('attempts', 0) >= 3:
            return {'status': 'deferred'}
        entry = existing or {'body': {'content': body}, 'metrics': metrics, 'status': 'queued', 'attempts': 0}
        records[key] = entry
        entry.update(attempts=entry['attempts'] + 1, last_attempt_at=now)
        persist()
        channel = dm_channel(api, agent_id)
        entry.update(status='sending', channel_id=channel, attempted_at=now)
        persist()
        sent = api.call('/api/channels/' + channel + '/messages', 'POST', entry['body'])
        if not sent.get('id') or sent.get('content') != entry['body']['content']:
            raise BridgeError('Progress send response was not confirmed')
        entry.update(status='sent', remote_id=sent['id'], sent_at=now)
        journal['last_sent_at'] = now
        persist()
        return {'status': 'sent', 'milestone': metrics['stage']}
    except (BridgeError, ValueError, TypeError, KeyError, OSError):
        # Do not publish technical diagnostics or interrupt procurement over a progress notification.
        try:
            if 'entry' in locals() and entry.get('status') == 'sending':
                entry['status'] = 'uncertain'
                persist()
        except (OSError, ValueError):
            pass
        return {'status': 'deferred'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True, type=identifier)
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    if os.environ.get('TAKEOFF_SANDBOX') != '1' or not Path('/.dockerenv').exists():
        raise BridgeError('Use the isolated Takeoff runtime')
    with store.transaction(args.task_id) as (state, persist):
        if not state:
            raise BridgeError('No persisted procurement run exists for this task')
        if not args.send:
            print(overview(state)[1])
            return
        api = API()
        identity = api.call('/api/users/me')
        if identity.get('workspace_id') != WORKSPACE or identity.get('id') != state.get('agent_id') or identity.get('type') != 'agent':
            raise BridgeError('Progress sender identity mismatch')
        print(json.dumps(notify_progress(api, state, persist)))


if __name__ == '__main__':
    main()
