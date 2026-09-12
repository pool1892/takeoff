import json

import httpx
import pytest

from takeoff_suppliers.runtime import AgentRuntime, RecoveryRequired, TransportState


class Market:
    issued = 0
    def is_paused(self, *a): return False
    def get_run(self, *a): return {'policy': 'collaboration'}
    def catalog(self, *a): return {'products': []}
    def get_offer(self, *a):
        return {'quote_id': 'q', 'total': '12.50', 'vendor_id': 'general', 'status': 'issued'}
    def issue_offer(self, run, vendor, buyer, proposal):
        assert (run, vendor, buyer) == ('r', 'general', 'b')
        assert 'approval_ref' not in proposal['lines'][0]
        self.issued += 1
        return {'quote_id': 'q', 'total': '12.50', 'vendor_id': vendor}


def pending():
    return {'type': 'function_call', 'turn_id': 'turn', 'call_id': 'call', 'name': 'issue_offer',
            'arguments': {'proposal': {'lines': [{'product_id': 'p', 'quantity': 1, 'unit': 'each',
                                                'approval_ref': 'forged'}], 'delivery_slot': 'slot'}}}


def test_real_agents_contract_and_required_action_disconnect_recovery(tmp_path):
    state = TransportState(tmp_path / 's.db')
    market = Market()
    results, creates = [], []
    fail = [True]
    submitted = [False]
    def handle(r):
        assert r.headers['OpenAI-Beta'] == 'agents=v1'
        if r.method == 'POST' and r.url.path.endswith('/sessions'):
            body = json.loads(r.content)
            creates.append(body)
            assert body['environment'] == {'type': 'none'}
            assert body['agent']['model'] == 'gpt-6-astra'
            assert not any(t['name'] == 'accept_offer' for t in body['agent']['tools'])
            return httpx.Response(200, json={'id': 'sess'})
        if r.method == 'GET' and r.url.path.endswith('/sess'):
            return httpx.Response(200, json={'status': 'idle' if submitted[0] else 'requires_action',
                                           'required_actions': [] if submitted[0] else [pending()]})
        if r.method == 'POST':
            event = json.loads(r.content)['events'][0]
            results.append(event)
            if fail[0]:
                fail[0] = False
                raise httpx.ReadTimeout('response lost')
            submitted[0] = True
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'data': [{'id': 'turn', 'status': 'completed'}]})
    runtime = AgentRuntime(market, state, 'key', client=httpx.Client(transport=httpx.MockTransport(handle)), poll_interval=0)
    with pytest.raises(httpx.ReadTimeout):
        runtime.respond('r', 'general', 'b', 'Request', request_id='source')
    result = runtime.respond('r', 'general', 'b', 'Request', request_id='source')
    assert market.issued == 1
    assert results[0] == results[1]
    assert result['offers'][0]['total'] == '12.50'
    assert len(creates) == 1
    assert runtime.respond('r', 'general', 'b', 'Request', request_id='source') == result


def test_scope_override_is_rejected_and_cached(tmp_path):
    state = TransportState(tmp_path / 's.db')
    market = Market()
    runtime = AgentRuntime(market, state, 'key')
    action = pending()
    action['arguments']['buyer_id'] = 'another-buyer'
    outcome = runtime._action('s', action, 'r', 'general', 'b', 'email', 'source')
    assert outcome['success'] is False
    assert market.issued == 0


def test_uncertain_function_execution_never_blindly_repeats(tmp_path):
    state = TransportState(tmp_path / 's.db')
    state.put('call:s:turn:call', {'pending': True})
    market = Market()
    runtime = AgentRuntime(market, state, 'key')
    with pytest.raises(RecoveryRequired):
        runtime._action('s', pending(), 'r', 'general', 'b', 'email', 'source')
    assert market.issued == 0


def test_idle_without_successful_turn_is_not_success(tmp_path):
    state = TransportState(tmp_path / 's.db')
    def handle(r):
        if r.method == 'POST': return httpx.Response(200, json={'id': 's'})
        if r.url.path.endswith('/turns'): return httpx.Response(200, json={'data': [{'status': 'failed'}]})
        return httpx.Response(200, json={'status': 'idle'})
    runtime = AgentRuntime(Market(), state, 'key', client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(RecoveryRequired, match='verified completion'):
        runtime.respond('r', 'general', 'b', 'request', request_id='source')


def test_cancelled_caller_cannot_execute_pending_action(tmp_path):
    import threading
    cancel = threading.Event()
    state = TransportState(tmp_path / 's.db')
    state.put('session:r:general', 'sess')
    state.put('input:r:general:source', {'session_id': 'sess', 'records': []})
    market = Market()
    def handle(r):
        cancel.set()
        return httpx.Response(200, json={'status': 'requires_action', 'required_actions': [pending()]})
    runtime = AgentRuntime(market, state, 'key', client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(TimeoutError, match='disconnected'):
        runtime.respond('r', 'general', 'b', 'request', request_id='source', cancel_event=cancel)
    assert market.issued == 0


def test_counter_retains_original_request_and_refreshes_superseded_offer(tmp_path):
    from takeoff_suppliers.core import Market as RealMarket
    market = RealMarket(tmp_path / 'market.db')
    run_id = market.create_run('buyer')['id']
    catalog = market.catalog(run_id, 'overstock')
    product = catalog['products'][0]
    proposal = {'lines': [{'product_id': product['id'], 'quantity': max(product['pack_size'], product['minimum_quantity']),
                          'unit': product['unit']}], 'delivery_slot': catalog['delivery_slots'][0]['id']}
    state = TransportState(tmp_path / 'state.db')
    runtime = AgentRuntime(market, state, 'key')
    action = {'type': 'function_call', 'turn_id': 'turn', 'call_id': 'opening',
              'name': 'issue_offer', 'arguments': {'proposal': proposal}}
    first = runtime._action('session', action, run_id, 'overstock', 'buyer', 'email', 'email:first')['record']
    action['call_id'] = 'counter'
    action['arguments'] = {'proposal': {**proposal, 'previous_quote_id': first['quote_id']}}
    second = runtime._action('session', action, run_id, 'overstock', 'buyer', 'email', 'email:counter')['record']
    assert second['request_id'] == first['request_id'] == 'email:first'
    assert market.get_offer(run_id, first['quote_id'], 'buyer')['status'] == 'countered'
    state.put(f'session:{run_id}:overstock', 'session')
    state.put(f'input:{run_id}:overstock:email:counter', {'session_id': 'session', 'records': [
        {'name': 'issue_offer', 'success': True, 'record': first},
        {'name': 'issue_offer', 'success': True, 'record': second}]})
    def handle(request):
        if request.url.path.endswith('/turns'):
            return httpx.Response(200, json={'data': [{'id': 'turn', 'status': 'completed'}]})
        if request.url.path.endswith('/items'):
            return httpx.Response(200, json={'data': []})
        return httpx.Response(200, json={'status': 'idle'})
    runtime.client = httpx.Client(transport=httpx.MockTransport(handle))
    result = runtime.respond(run_id, 'overstock', 'buyer', 'counter', request_id='email:counter')
    assert [q['quote_id'] for q in result['offers']] == [second['quote_id']]
