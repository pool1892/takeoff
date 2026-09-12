import json
from types import SimpleNamespace

import httpx
import pytest

from takeoff_suppliers.channels import AmbiguousClient, VendorConnection
from takeoff_suppliers.runtime import RecoveryRequired, TransportState
from takeoff_suppliers.worker import SupplierWorker


def connection(handler, **kwargs):
    return AmbiguousClient(VendorConnection('general', 'secret', 'supplier', 'buyer', 'vendor', **kwargs),
                           httpx.Client(transport=httpx.MockTransport(handler)))


def test_verify_workspace_and_vendor():
    channel = connection(lambda r: httpx.Response(200, json={'id': 'vendor', 'workspace_id': 'supplier'}))
    assert channel.verify_identity()['id'] == 'vendor'
    channel = connection(lambda r: httpx.Response(200, json={'id': 'vendor', 'workspace_id': 'buyer'}))
    with pytest.raises(ValueError, match='workspace'):
        channel.verify_identity()


def test_inbox_flattens_and_paginates_and_send_uses_retry_key():
    requests = []
    def handle(request):
        requests.append(request)
        if request.method == 'POST':
            assert request.headers['Idempotency-Key'] == 'same-send'
            body = json.loads(request.content)
            assert body['thread_id'] == 'thread' and body['in_reply_to'] == 'rfc-id'
            assert body['to'] == ['buyer@example.test']
            return httpx.Response(201, json={'id': 'out', 'delivery_status': 'sent'})
        assert request.url.params['threaded'] == 'false'
        if 'cursor' not in request.url.params:
            return httpx.Response(200, json={'data': [{'id': 'one'}], 'has_more': True, 'next_cursor': 'two'})
        return httpx.Response(200, json={'data': [{'id': 'two'}], 'has_more': False})
    channel = connection(handle)
    assert [m['id'] for m in channel.inbox()] == ['one', 'two']
    channel.send_email('buyer@example.test', 'Terms', key='same-send', thread_id='thread', in_reply_to='rfc-id')
    assert all(r.headers['authorization'] == 'Bearer secret' for r in requests)


class FakeMarket:
    paused = False
    def is_paused(self, *args):
        return self.paused


def test_worker_pauses_deduplicates_and_does_not_replay_confirmed_send(tmp_path):
    state = TransportState(tmp_path / 'state.db')
    market = FakeMarket()
    calls = []
    runtime = SimpleNamespace(respond=lambda *a, **kw: calls.append(kw['request_id']) or {'message': 'Canonical quote'})
    worker = SupplierWorker(market, runtime, state, 'run', 'general', None, buyers={})
    sent = []
    send = lambda body, key: sent.append(key) or {'id': 'sent'}
    market.paused = True
    assert not worker._process('email:one', 'buyer', 'request', send, retry_safe=True)
    market.paused = False
    assert worker._process('email:one', 'buyer', 'request', send, retry_safe=True)
    assert not worker._process('email:one', 'buyer', 'request', send, retry_safe=True)
    assert len(calls) == len(sent) == 1


def test_uncertain_email_retries_same_key_but_chat_requires_reconciliation(tmp_path):
    state = TransportState(tmp_path / 'state.db')
    runtime = SimpleNamespace(respond=lambda *a, **kw: {'message': 'Terms'})
    worker = SupplierWorker(FakeMarket(), runtime, state, 'run', 'general', None, buyers={})
    keys = []
    def uncertain(body, key):
        keys.append(key)
        raise httpx.ReadTimeout('lost reply')
    with pytest.raises(httpx.ReadTimeout):
        worker._process('email:one', 'buyer', 'request', uncertain, retry_safe=True)
    worker._process('email:one', 'buyer', 'request', lambda b, k: keys.append(k) or {'id':'sent'}, retry_safe=True)
    assert keys[0] == keys[1]
    with pytest.raises(httpx.ReadTimeout):
        worker._process('chat:one', 'buyer', 'request', uncertain)
    with pytest.raises(RecoveryRequired):
        worker._process('chat:one', 'buyer', 'request', uncertain)


def test_explicit_acceptance_creates_one_simulated_fulfillment_task(tmp_path):
    class AcceptanceMarket(FakeMarket):
        def get_offer(self, *args):
            return {'vendor_id': 'general'}
        def accept_offer(self, run, quote, buyer, approval_refs):
            assert (run, quote, buyer) == ('run', 'quote', 'buyer')
            return {'id': 'order', 'quote_id': quote, 'simulated': True}
    calls = []
    channel = SimpleNamespace(create_fulfillment_task=lambda record: calls.append(record) or {'id':'task'})
    worker = SupplierWorker(AcceptanceMarket(), None, TransportState(tmp_path / 'state.db'),
                            'run', 'general', channel, buyers={})
    envelope = json.dumps({'schema_version': 'takeoff.supplier.v1', 'run_id': 'run',
                           'vendor_id': 'general', 'type': 'acceptance', 'quote_id': 'quote'})
    result = worker._respond('buyer', envelope, 'email:accept', 'email')
    assert 'task' in result['message']
    worker._respond('buyer', envelope, 'email:accept', 'email')
    assert len(calls) == 1


def test_real_market_acceptance_checks_vendor_and_mirrors_task(tmp_path):
    from takeoff_suppliers.core import Market
    market = Market(tmp_path / 'market.db')
    run = market.create_run('buyer')['id']
    catalog = market.catalog(run, 'general')
    product = catalog['products'][0]
    offer = market.issue_offer(run, 'general', 'buyer', {
        'lines': [{'product_id': product['id'], 'quantity': max(product['minimum_quantity'], product['pack_size']),
                   'unit': product['unit']}], 'delivery_slot': catalog['delivery_slots'][0]['id']})
    tasks = []
    channel = SimpleNamespace(create_fulfillment_task=lambda record: tasks.append(record) or {'id': 'ambi-task'})
    state = TransportState(tmp_path / 'transport.db')
    worker = SupplierWorker(market, None, state, run, 'overstock', channel, buyers={})
    envelope = {'schema_version': 'takeoff.supplier.v1', 'run_id': run, 'vendor_id': 'overstock',
                'type': 'acceptance', 'quote_id': offer['quote_id']}
    with pytest.raises(ValueError, match='different supplier'):
        worker._respond('buyer', json.dumps(envelope), 'email:source', 'email')
    envelope['vendor_id'] = 'general'
    worker = SupplierWorker(market, None, state, run, 'general', channel, buyers={})
    worker._respond('buyer', json.dumps(envelope), 'email:source', 'email')
    assert market.get_offer(run, offer['quote_id'], 'buyer')['status'] == 'accepted'
    assert len(tasks) == 1
    assert list(state.export_run(run)['fulfillment_tasks'].values()) == [{'id': 'ambi-task'}]
