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


class PollMarket(FakeMarket):
    def get_run(self, *args):
        return {'created_at': '2026-09-12T12:00:00+00:00'}


def poll_channel(messages):
    sent = []
    channel = SimpleNamespace(
        identity={'id': 'vendor', 'workspace_email': 'supplier@example.test'},
        config=SimpleNamespace(vendor_id='general', chat_threads=[]),
        inbox=lambda: messages,
        send_email=lambda address, body, **kwargs: sent.append((address, body, kwargs)) or {'id': str(len(sent))},
    )
    return channel, sent


def inbound(message_id, body, received_at='2026-09-12T12:05:00Z'):
    return {'id': message_id, 'from': {'email': 'buyer@example.test'}, 'body_text': body,
            'inbound_auth': {'verdict': 'aligned'}, 'received_at': received_at, 'sent_at': '2026-09-12T12:04:00Z', 'subject': 'Demo'}


def test_reset_ignores_old_and_other_scoped_mail_without_starving_new_message(tmp_path):
    messages = [
        inbound('new', 'Please quote a package'),
        inbound('wrong-vendor', json.dumps({'schema_version': 'takeoff.supplier.v1', 'run_id': 'run',
                                          'vendor_id': 'local', 'type': 'inquiry'})),
        inbound('wrong-run', json.dumps({'schema_version': 'takeoff.supplier.v1', 'run_id': 'old-run',
                                       'vendor_id': 'general', 'type': 'inquiry'})),
        inbound('old', 'Old free text must not replay', '2026-09-12T11:59:59Z'),
    ]
    channel, sent = poll_channel(messages)
    calls = []
    runtime = SimpleNamespace(respond=lambda *a, **kw: calls.append(kw['request_id']) or {'message': 'Current response'})
    state = TransportState(tmp_path / 'state.db')
    worker = SupplierWorker(PollMarket(), runtime, state, 'run', 'general', channel,
                            buyers={'buyer@example.test': 'buyer'})
    assert worker.tick() == 1
    assert calls == ['email:new']
    assert len(sent) == 1
    reasons = {'old': 'predates_run', 'wrong-run': 'different_run', 'wrong-vendor': 'different_vendor'}
    for message_id, reason in reasons.items():
        item = state.get('message:run:general:email:' + message_id)
        assert item['status'] == 'ignored' and item['reason'] == reason
    assert worker.tick() == 0
    assert len(sent) == 1


def test_malformed_authorized_message_replies_once_and_valid_next_message_runs(tmp_path):
    channel, sent = poll_channel([
        inbound('valid', 'Please show stock'),
        inbound('missing-fields', json.dumps({'schema_version': 'takeoff.supplier.v1', 'run_id': 'run',
                                            'vendor_id': 'general', 'type': 'acceptance'})),
        inbound('malformed', '{"schema_version":'),
    ])
    calls = []
    runtime = SimpleNamespace(respond=lambda *a, **kw: calls.append(kw['request_id']) or {'message': 'Current stock'})
    # The acceptance handler must never reach commercial state for missing quote_id.
    class SafeMarket(PollMarket):
        def get_offer(self, *args):
            raise AssertionError('No quote was supplied')
    worker = SupplierWorker(SafeMarket(), runtime, TransportState(tmp_path / 'state.db'),
                            'run', 'general', channel, buyers={'buyer@example.test': 'buyer'})
    assert worker.tick() == 3
    assert calls == ['email:valid']
    assert sum('could not validate' in body for _, body, _ in sent) == 2
    assert worker.tick() == 0
    assert len(sent) == 3


def test_uncertain_message_is_quarantined_and_does_not_block_next_message(tmp_path):
    channel, sent = poll_channel([inbound('valid', 'Current request'), inbound('uncertain', 'Earlier request')])
    calls = []
    def respond(*args, **kwargs):
        calls.append(kwargs['request_id'])
        if kwargs['request_id'] == 'email:uncertain':
            raise RecoveryRequired('Pending commercial side effect')
        return {'message': 'Current reply'}
    state = TransportState(tmp_path / 'state.db')
    worker = SupplierWorker(PollMarket(), SimpleNamespace(respond=respond), state,
                            'run', 'general', channel, buyers={'buyer@example.test': 'buyer'})
    assert worker.tick() == 1
    assert state.get('message:run:general:email:uncertain')['status'] == 'recovery_required'
    assert worker.tick() == 0
    assert calls == ['email:uncertain', 'email:valid']


def test_record_sync_failure_preserves_reply_and_does_not_repeat_turn(tmp_path, monkeypatch):
    channel, sent = poll_channel([inbound('quote', 'Quote request')])
    calls = []
    def respond(*a, **kw):
        calls.append(kw['request_id'])
        return {'message': 'Validated quote', 'offers': [{'quote_id': 'quote'}]}
    def broken_sync(*args, **kwargs):
        raise RecoveryRequired('Uncertain document creation')
    monkeypatch.setattr('takeoff_suppliers.sync.SupplierRecordsSync', broken_sync)
    state = TransportState(tmp_path / 'state.db')
    worker = SupplierWorker(PollMarket(), SimpleNamespace(respond=respond), state,
                            'run', 'general', channel, buyers={'buyer@example.test': 'buyer'})
    assert worker.tick() == 1
    item = state.get('message:run:general:email:quote')
    assert item['status'] == 'sent' and item['record_sync']['ok'] is False
    assert item['record_sync']['recovery_required'] is True
    assert worker.tick() == 0
    assert len(sent) == len(calls) == 1


@pytest.mark.parametrize('verdict,reason', [('unaligned', 'sender_auth_unaligned'),
                                         ('unverified', 'sender_auth_unverified'),
                                         (None, 'sender_auth_missing')])
def test_mail_sender_requires_aligned_authentication(tmp_path, verdict, reason):
    untrusted = inbound('untrusted', 'Please issue a quote')
    untrusted['inbound_auth'] = {'verdict': verdict} if verdict is not None else None
    channel, sent = poll_channel([inbound('trusted', 'Current request'), untrusted])
    calls = []
    runtime = SimpleNamespace(respond=lambda *a, **kw: calls.append(kw['request_id']) or {'message': 'Verified reply'})
    state = TransportState(tmp_path / 'state.db')
    worker = SupplierWorker(PollMarket(), runtime, state, 'run', 'general', channel,
                            buyers={'buyer@example.test': 'buyer'})
    assert worker.tick() == 1
    assert calls == ['email:trusted']
    assert len(sent) == 1
    rejected = state.get('message:run:general:email:untrusted')
    assert rejected['status'] == 'ignored' and rejected['reason'] == reason
    assert worker.tick() == 0
