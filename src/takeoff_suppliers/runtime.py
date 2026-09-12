"""OpenAI Agents API adapter with durable required-action recovery.

Reference: https://developers.openai.com/api/docs/guides/agents-api/tools/functions
"""
import json
import sqlite3
import time
import threading
from pathlib import Path

import httpx


class RecoveryRequired(RuntimeError):
    """An uncertain side effect must be reconciled by the operator before retry."""


class TransportState:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS transport_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM transport_state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO transport_state VALUES (?,?)', (key, json.dumps(value)))


    def export_run(self, run_id):
        """Operator-only transport evidence; may contain private correspondence."""
        rows = {key: json.loads(value) for key, value in
                self.db.execute('SELECT key,value FROM transport_state').fetchall()}
        sessions = {key: value for key, value in rows.items() if key.startswith((f'session:{run_id}:', f'codex-session:{run_id}:'))}
        ids = set(sessions.values()) | {'codex-' + v for k, v in sessions.items() if k.startswith('codex-session:')}
        return {
            'sessions': sessions,
            'record_mirrors': rows.get(f'records:{run_id}'),
            'codex_turns': {k: v for k, v in rows.items() if k.startswith(f'codex-input:{run_id}:')},
            'messages': {k: v for k, v in rows.items() if k.startswith(f'message:{run_id}:')},
            'fulfillment_tasks': {k: v for k, v in rows.items() if k.startswith(f'fulfillment:{run_id}:')},
            'agent_traces': {k: v for k, v in rows.items() if k.startswith('trace:') and
                             k.split(':', 2)[1] in ids},
        }


PERSONALITIES = {
    'general': 'Sell fixed packages; explain fit and package conditions.',
    'overstock': 'Move aging inventory. Negotiate useful discounts and bundles.',
    'local': 'Optimize delivery timing and consolidation; propose useful coordination.',
    'trader': 'Use cited external research to inform future-delivery proposals. Never execute trades.',
}


def function(name, properties, required=()):
    return {'type': 'function', 'name': name, 'description': {
        'catalog': 'Read this supplier public catalog and negotiating opportunities.',
        'inquire': 'Get a canonical response to a product or commercial question.',
        'issue_offer': 'Validate and issue proposed commercial terms. Only successful records are offers.',
    }[name], 'parameters': {'type': 'object', 'properties': properties,
                           'required': list(required), 'additionalProperties': False}}


TOOLS = [function('catalog', {'query': {'type': 'string'}}),
         function('inquire', {'message': {'type': 'string'}}, ['message']),
         function('issue_offer', {'proposal': {'type': 'object', 'properties': {
             'request_id': {'type': 'string'}, 'lines': {'type': 'array', 'items': {'type': 'object',
             'properties': {'product_id': {'type': 'string'}, 'quantity': {'type': 'integer'},
                            'unit': {'type': 'string'}, 'substitution_for': {'type': 'string'},
                            'approval_ref': {'type': 'string'}},
             'required': ['product_id', 'quantity', 'unit'], 'additionalProperties': False}},
             'delivery_slot': {'type': 'string'}, 'discount_code': {'type': 'string'},
             'requested_total': {'type': 'string'}, 'previous_quote_id': {'type': 'string'}},
             'required': ['lines', 'delivery_slot'], 'additionalProperties': False}}, ['proposal'])]


class AgentRuntime:
    def __init__(self, market, state: TransportState, api_key: str, *, model='gpt-6-astra',
                 client=None, connections=None, exa_mcp_url=None, poll_interval=1, max_polls=120):
        self.market, self.state = market, state
        self.api_key, self.model = api_key, model
        self.client = client or httpx.Client(timeout=45)
        self.connections = connections or {}
        self.exa_mcp_url = exa_mcp_url
        self.poll_interval, self.max_polls = poll_interval, max_polls
        self._locks = {}
        self._locks_guard = threading.Lock()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, 'https://api.openai.com/v1/agents/sessions' + path,
            headers={'Authorization': f'Bearer {self.api_key}', 'OpenAI-Beta': 'agents=v1'}, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def _tools(self, vendor_id):
        tools = list(TOOLS)
        if vendor_id in self.connections:
            connection = self.connections[vendor_id]
            if connection.identity is None:
                connection.verify_identity()
            tools.append(connection.readonly_mcp())
        if self.exa_mcp_url:
            tools.append({'type': 'mcp', 'server_label': 'exa', 'required': False,
                          'transport': {'type': 'http', 'server_url': self.exa_mcp_url}})
        return tools

    def _action(self, sid, action, run_id, vendor_id, buyer_id, channel, request_id):
        key = f'call:{sid}:{action["turn_id"]}:{action["call_id"]}'
        saved = self.state.get(key)
        if saved and saved.get('pending'):
            raise RecoveryRequired(f'Function result uncertain: {key}')
        if saved is not None:
            return saved
        self.state.put(key, {'pending': True})
        try:
            args = action['arguments']
            if isinstance(args, str):
                args = json.loads(args)
            name = action['name']
            allowed = {'catalog': {'query'}, 'inquire': {'message'}, 'issue_offer': {'proposal'}}
            if name not in allowed or set(args) - allowed[name]:
                raise ValueError('Unsupported function or scope-changing arguments')
            if name == 'catalog':
                result = self.market.catalog(run_id, vendor_id, args.get('query', ''))
            elif name == 'inquire':
                result = self.market.inquire(run_id, vendor_id, buyer_id, args['message'],
                                             channel=channel, request_id=request_id)
            else:
                proposal = dict(args['proposal'])
                if proposal.get('previous_quote_id'):
                    previous = self.market.get_offer(run_id, proposal['previous_quote_id'], buyer_id)
                    if previous['vendor_id'] != vendor_id:
                        raise ValueError('Counter addresses a different supplier offer')
                    proposal['request_id'] = previous['request_id']
                else:
                    proposal['request_id'] = request_id or proposal.get('request_id', '')
                # Models cannot manufacture buyer approval references.
                for line in proposal.get('lines', []):
                    line.pop('approval_ref', None)
                result = self.market.issue_offer(run_id, vendor_id, buyer_id, proposal)
            saved = {'success': True, 'output': json.dumps(result), 'record': result, 'name': name}
        except (ValueError, KeyError, TypeError) as exc:
            saved = {'success': False, 'error': getattr(exc, 'message', 'Invalid function arguments'),
                     'name': action.get('name')}
        self.state.put(key, saved)
        return saved

    def respond(self, run_id, vendor_id, buyer_id, message, channel='email', request_id=None,
                timeout_seconds=None, cancel_event=None):
        with self._locks_guard:
            lock = self._locks.setdefault((run_id, vendor_id), threading.Lock())
        started = time.monotonic()
        acquired = lock.acquire(timeout=timeout_seconds) if timeout_seconds is not None else lock.acquire()
        if not acquired:
            raise TimeoutError('Supplier is still processing another turn')
        try:
            remaining = None if timeout_seconds is None else max(0, timeout_seconds - (time.monotonic() - started))
            return self._respond(run_id, vendor_id, buyer_id, message, channel, request_id,
                                 remaining, cancel_event)
        finally:
            lock.release()

    def _respond(self, run_id, vendor_id, buyer_id, message, channel='email', request_id=None,
                 timeout_seconds=None, cancel_event=None):
        """Return canonical public records, never model-authored commercial claims.

        request_id must be stable across retries. Timeout leaves work resumable.
        """
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def request(method, path, **kwargs):
            if cancel_event is not None and cancel_event.is_set():
                raise TimeoutError('Agent caller disconnected')
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Agent turn deadline exceeded')
                kwargs['timeout'] = min(45, remaining)
            return self.request(method, path, **kwargs)

        run = self.market.get_run(run_id)
        if run.get('buyer_id') and run['buyer_id'] != buyer_id:
            raise ValueError('Buyer does not own this run')
        if self.market.is_paused(run_id, vendor_id):
            return {'status': 'paused', 'message': 'Supplier operator has paused responses.', 'offers': []}
        if not request_id:
            raise ValueError('A stable request_id is required for agent turns')
        turn_key = f'input:{run_id}:{vendor_id}:{request_id}'
        work = self.state.get(turn_key)
        if work and work.get('result'):
            return work['result']
        session_key = f'session:{run_id}:{vendor_id}'
        sid = self.state.get(session_key)
        if work and work.get('uncertain'):
            raise RecoveryRequired(f'Agent input delivery uncertain: {turn_key}')
        if not work:
            previous_turn_id = None
            if sid:
                previous = request('GET', f'/{sid}/turns', params={'order': 'desc', 'limit': 1})
                previous_turns = previous.get('data', [])
                previous_turn_id = previous_turns[0]['id'] if previous_turns else None
            self.state.put(turn_key, {'uncertain': True})
            payload = json.dumps({'request_id': request_id, 'sender': buyer_id, 'channel': channel,
                                  'message': message})
            if not sid:
                policy = self.market.get_run(run_id).get('policy', 'baseline')
                instructions = ('You represent one simulated supplier. Use catalog before negotiating. '
                    'Use inquire for questions or issue_offer for a quote. Never invent terms, stock, '
                    'fees, approvals or competitors. All external communication is rendered by the host '
                    'from these function results. Do not reveal owner-private context. No real purchases '
                    'or trades. ' + PERSONALITIES.get(vendor_id, 'Negotiate according to your public catalog.'))
                if policy != 'baseline':
                    instructions += (' Exchange useful information, distinguish proposals from commitments, '
                                     'ask for explicit substitution approval, and stop after agreement.')
                data = request('POST', '', json={'agent': {'model': self.model,
                    'instructions': instructions, 'tools': self._tools(vendor_id)},
                    'environment': {'type': 'none'}, 'input': payload, 'stream': False})
                sid = data['id']
                self.state.put(session_key, sid)
            else:
                request('POST', f'/{sid}/events', json={'events': [{
                    'type': 'agent.session.input.message', 'input': [{'role': 'user',
                    'content': [{'type': 'input_text', 'text': payload}]}]}]})
            work = {'session_id': sid, 'records': [], 'previous_turn_id': previous_turn_id}
            self.state.put(turn_key, work)
        for _ in range(self.max_polls):
            session = request('GET', f'/{sid}')
            for action in session.get('required_actions', []):
                if action['type'] != 'function_call':
                    raise RecoveryRequired('Unexpected required action for environment:none')
                if cancel_event is not None and cancel_event.is_set():
                    raise TimeoutError('Agent caller disconnected before executing tool')
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('Agent turn deadline exceeded before executing tool')
                outcome = self._action(sid, action, run_id, vendor_id, buyer_id, channel, request_id)
                marker = action['turn_id'] + ':' + action['call_id']
                if marker not in [r['marker'] for r in work['records']]:
                    work['records'].append({'marker': marker, **outcome})
                    self.state.put(turn_key, work)
                event = {'type': 'agent.session.input.tool_result', 'turn_id': action['turn_id'],
                         'call_id': action['call_id'], **{k: outcome[k] for k in ('success','output','error') if k in outcome}}
                request('POST', f'/{sid}/events', json={'events': [event]})
            if session.get('status') == 'idle':
                turns = request('GET', f'/{sid}/turns', params={'order': 'desc', 'limit': 1})
                latest = turns.get('data', [])
                if latest and work.get('previous_turn_id') and work['previous_turn_id'] == latest[0].get('id'):
                    time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic()))
                               if deadline is not None else self.poll_interval)
                    continue
                status = latest[0].get('status') if latest else 'unknown'
                if status != 'completed':
                    raise RecoveryRequired(f'Agent turn ended without verified completion: {status}')
                # Saved items include remote MCP research calls and their sources.
                # Store locally for inspection; never copy raw agent traces to buyers.
                params = {'order': 'asc', 'limit': 100, 'turn_id': latest[0]['id']}
                items = []
                while True:
                    page = request('GET', f'/{sid}/items', params=params)
                    items.extend(page.get('data', []))
                    if not page.get('has_more'):
                        break
                    after = page.get('last_id')
                    if not after or after == params.get('after'):
                        raise RecoveryRequired('Session item pagination did not advance')
                    params['after'] = after
                self.state.put(f'trace:{sid}:{latest[0]["id"]}', {'turn': latest[0], 'items': items})
                records = [r for r in work['records'] if r.get('success')]
                offers = []
                for record in records:
                    if record['name'] != 'issue_offer':
                        continue
                    saved_offer = record['record']
                    quote_id = saved_offer.get('quote_id') or saved_offer['id']
                    current = self.market.get_offer(run_id, quote_id, buyer_id)
                    if current['vendor_id'] == vendor_id and current.get('status') == 'issued':
                        offers.append(current)
                inquiries = [r['record'] for r in records if r['name'] == 'inquire']
                public = offers or inquiries
                result = {'status': 'completed', 'session_id': sid, 'offers': offers,
                          'message': ('Validated supplier records:\n\n```json\n' +
                                      json.dumps(public, indent=2) + '\n```') if public else
                          'No offer was issued. Please clarify products, quantities and delivery needs.'}
                work['result'] = result
                self.state.put(turn_key, work)
                return result
            if session.get('status') in ('failed', 'cancelled'):
                raise RecoveryRequired('Agent session failed or was cancelled')
            time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic()))
                               if deadline is not None else self.poll_interval)
        raise TimeoutError('Agent still working; retry with the same request_id to resume')
