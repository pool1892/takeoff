"""Poll configured demo channels and relay authenticated buyer inputs."""
from datetime import datetime, timezone
import hashlib
import json
import time

import httpx

from .runtime import RecoveryRequired


class SupplierWorker:
    def __init__(self, market, runtime, state, run_id, vendor_id, channel,
                 *, buyers, chat_buyers=None, sync_records=True):
        self.market, self.runtime, self.state = market, runtime, state
        self.run_id, self.vendor_id, self.channel = run_id, vendor_id, channel
        # Explicit sender -> buyer mapping is configured outside model context.
        self.buyers = {email.lower(): buyer for email, buyer in buyers.items()}
        self.chat_buyers = chat_buyers or {}
        self.sync_records = sync_records

    def _respond(self, buyer_id, body, source_id, kind):
        """Structured A2A decisions are explicit; free text is negotiation only."""
        try:
            envelope = json.loads(body)
        except (ValueError, TypeError):
            if isinstance(body, str) and body.lstrip().startswith(('{', '[')):
                raise ValueError('Malformed structured supplier request') from None
            envelope = None
        if envelope is not None and not isinstance(envelope, dict):
            raise ValueError('A structured supplier request must be an object')
        if isinstance(envelope, dict) and envelope.get('schema_version') not in (None, 'takeoff.supplier.v1'):
            raise ValueError('Unsupported supplier message schema')
        if isinstance(envelope, dict) and envelope.get('schema_version') == 'takeoff.supplier.v1':
            if envelope.get('run_id') != self.run_id or envelope.get('vendor_id') != self.vendor_id:
                raise ValueError('A2A envelope addresses a different run or supplier')
            action = envelope.get('type')
            if action == 'approval':
                record = self.market.record_approval(self.run_id, buyer_id,
                    envelope['requirement_id'], envelope['product_id'], source_id)
                return {'message': 'Recorded buyer approval:\n' + json.dumps(record), 'offers': []}
            if action == 'acceptance':
                quote = self.market.get_offer(self.run_id, envelope['quote_id'], buyer_id)
                if quote['vendor_id'] != self.vendor_id:
                    raise ValueError('Acceptance addresses a different supplier offer')
                # Core rechecks buyer ownership, exact revision, stock and recorded approvals.
                record = self.market.accept_offer(self.run_id, envelope['quote_id'], buyer_id,
                                                  approval_refs=envelope.get('approval_refs', []))
                task_key = f'fulfillment:{self.run_id}:{self.vendor_id}:{envelope["quote_id"]}'
                try:
                    task = self.state.get(task_key)
                    if task and task.get('pending'):
                        raise RecoveryRequired('Fulfillment task creation uncertain; inspect Ambiguous before retry')
                    if task is None:
                        self.state.put(task_key, {'pending': True})
                        task = self.channel.create_fulfillment_task(record)
                        if not isinstance(task.get('id'), str) or not task['id']:
                            raise ValueError('Fulfillment creation returned no task ID')
                        self.state.put(task_key, task)
                except RecoveryRequired:
                    raise
                except Exception as exc:
                    raise RecoveryRequired('Commitment recorded; fulfillment task outcome requires inspection') from exc
                return {'message': 'Simulated commitment:\n' + json.dumps(record) +
                        '\nSupplier fulfillment task: ' + str(task['id']), 'offers': [],
                        'commercial_change': True}
            if action not in ('inquiry', 'counter'):
                raise ValueError('Unsupported A2A message type')
        return self.runtime.respond(self.run_id, self.vendor_id, buyer_id, body,
                                    channel=kind, request_id=source_id)

    def _process(self, source_id, buyer_id, body, send, *, retry_safe=False):
        key = f'message:{self.run_id}:{self.vendor_id}:{source_id}'
        item = self.state.get(key)
        if item and item.get('status') in ('sent', 'ignored', 'recovery_required'):
            return False
        if self.market.is_paused(self.run_id, self.vendor_id):
            self.state.put(key, {**(item or {}), 'status': item.get('status', 'queued') if item else 'queued',
                                 'buyer_id': buyer_id, 'body': body, 'paused': True})
            return False
        if item and item.get('status') == 'sending' and not retry_safe:
            raise RecoveryRequired('Chat send outcome uncertain; inspect thread before retry')
        if item and item.get('status') == 'processing':
            # Structured decisions may have succeeded before saving their result.
            try:
                envelope = json.loads(body)
            except ValueError:
                envelope = {}
            if isinstance(envelope, dict) and envelope.get('type') in ('approval', 'acceptance'):
                raise RecoveryRequired('Buyer decision outcome uncertain; reconcile ledger before retry')
        if not item or 'result' not in item:
            self.state.put(key, {**(item or {}), 'status': 'processing',
                                 'buyer_id': buyer_id, 'source_id': source_id, 'body': body})
            try:
                result = self._respond(buyer_id, body, source_id,
                                       'chat' if source_id.startswith('chat:') else 'email')
            except (ValueError, KeyError, TypeError):
                result = {'status': 'invalid_request', 'offers': [],
                          'message': 'The supplier could not validate this request. Check the message type, '
                                     'required fields, and referenced quote or approval, then send a corrected request.'}
            item = {**self.state.get(key), 'status': 'ready', 'result': result}
            self.state.put(key, item)
        if item['result'].get('status') == 'paused':
            self.state.put(key, {'status': 'queued'})
            return False
        if self.sync_records and 'record_sync' not in item and (
                item['result'].get('offers') or item['result'].get('commercial_change')):
            # Mirroring is independent of the reply. Its failure must not erase a
            # validated quote or cause an already completed turn to run again.
            try:
                from .sync import SupplierRecordsSync
                item['record_sync'] = SupplierRecordsSync(
                    self.market, self.state, {self.vendor_id: self.channel}).sync(self.run_id)
            except Exception as exc:
                item['record_sync'] = {'ok': False, 'error': type(exc).__name__,
                                       'recovery_required': isinstance(exc, RecoveryRequired)}
            self.state.put(key, item)
        item['status'] = 'sending'
        self.state.put(key, item)
        receipt = send(item['result']['message'], hashlib.sha256(key.encode()).hexdigest())
        item.update(status='sent', receipt=receipt)
        self.state.put(key, item)
        return True

    @staticmethod
    def _timestamp(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

    def _eligible(self, source_id, buyer_id, body, timestamp, run_start):
        key = f'message:{self.run_id}:{self.vendor_id}:{source_id}'
        existing = self.state.get(key) or {}
        if existing.get('status') in ('sent', 'ignored', 'recovery_required'):
            return False
        try:
            envelope = json.loads(body)
        except (ValueError, TypeError):
            envelope = None
        reason = None
        if isinstance(envelope, dict) and envelope.get('schema_version') == 'takeoff.supplier.v1':
            # Missing scope fields are malformed requests and receive an error;
            # explicit different scope means an old/other conversation to ignore.
            if envelope.get('run_id') is not None and envelope['run_id'] != self.run_id:
                reason = 'different_run'
            elif envelope.get('vendor_id') is not None and envelope['vendor_id'] != self.vendor_id:
                reason = 'different_vendor'
        observed = self._timestamp(timestamp)
        if reason is None and observed is not None and observed < run_start:
            reason = 'predates_run'
        if reason is None and observed is None:
            # Without a trustworthy timestamp, only an explicitly current scoped
            # envelope can establish which trial should handle this message.
            if not (isinstance(envelope, dict) and envelope.get('schema_version') == 'takeoff.supplier.v1'
                    and envelope.get('run_id') == self.run_id and envelope.get('vendor_id') == self.vendor_id):
                reason = 'missing_or_invalid_timestamp'
        if reason:
            self.state.put(key, {**existing, 'status': 'ignored', 'reason': reason,
                                'buyer_id': buyer_id, 'source_id': source_id, 'timestamp': timestamp,
                                'body': body})
            return False
        return True

    def _handle_message(self, source_id, buyer_id, body, send, timestamp, run_start, *, retry_safe=False):
        if not self._eligible(source_id, buyer_id, body, timestamp, run_start):
            return False
        key = f'message:{self.run_id}:{self.vendor_id}:{source_id}'
        if self.state.get(key) is None:
            self.state.put(key, {'status': 'received', 'source_id': source_id, 'buyer_id': buyer_id,
                                 'body': body, 'timestamp': timestamp})
        try:
            return self._process(source_id, buyer_id, body, send, retry_safe=retry_safe)
        except RecoveryRequired as exc:
            item = self.state.get(key) or {}
            self.state.put(key, {**item, 'status': 'recovery_required',
                                'previous_status': item.get('status'), 'error': type(exc).__name__,
                                'source_id': source_id})
            return False
        except (httpx.HTTPError, TimeoutError) as exc:
            item = self.state.get(key) or {}
            # Idempotent email sends may retry. Chat sends and pending explicit
            # decisions are checked by _process before any retry can occur.
            self.state.put(key, {**item, 'last_error': type(exc).__name__, 'source_id': source_id})
            return False

    def tick(self):
        if self.channel.identity is None:
            self.channel.verify_identity()
        identity = self.channel.identity
        run_start = self._timestamp(self.market.get_run(self.run_id)['created_at'])
        if run_start is None:
            raise ValueError('Run creation timestamp is missing or invalid')
        own_emails = {identity.get(k, '').lower() for k in ('workspace_email', 'primary_email')
                      if identity.get(k)}
        sent = 0
        for message in reversed(self.channel.inbox()):
            sender = message.get('from') or {}
            address = (sender.get('email', '') if isinstance(sender, dict) else sender).lower()
            if address in own_emails or address not in self.buyers:
                continue
            authentication = message.get('inbound_auth') or {}
            verdict = authentication.get('verdict') if isinstance(authentication, dict) else None
            if verdict != 'aligned':
                source_id = 'email:' + message['id']
                key = f'message:{self.run_id}:{self.vendor_id}:{source_id}'
                existing = self.state.get(key) or {}
                if existing.get('status') not in ('sent', 'ignored', 'recovery_required'):
                    reason = 'sender_auth_' + (verdict if verdict in ('unaligned', 'unverified') else 'missing')
                    self.state.put(key, {**existing, 'status': 'ignored', 'reason': reason,
                                        'source_id': source_id, 'sender': address,
                                        'buyer_id': self.buyers[address],
                                        'body': message.get('body_text') or '',
                                        'timestamp': message.get('received_at') or message.get('sent_at')})
                continue
            def send(body, key, m=message, address=address):
                return self.channel.send_email(address, body, key=key,
                    subject='Re: ' + m.get('subject', 'Takeoff inquiry'), thread_id=m.get('thread_id'),
                    in_reply_to=m.get('message_id'))
            timestamp = message.get('received_at') or message.get('created_at') or message.get('sent_at')
            sent += self._handle_message('email:' + message['id'], self.buyers[address],
                                         message.get('body_text') or '', send, timestamp, run_start, retry_safe=True)
        for channel_id, thread_id in self.channel.config.chat_threads:
            for message in self.channel.thread(channel_id, thread_id):
                sender = (message.get('author') or {}).get('id')
                if sender == identity['id'] or sender not in self.chat_buyers or message.get('deleted_at'):
                    continue
                def send(body, key, channel_id=channel_id, thread_id=thread_id):
                    return self.channel.send_chat(channel_id, thread_id, body)
                sent += self._handle_message('chat:' + message['id'], self.chat_buyers[sender],
                                             message.get('content', ''), send, message.get('created_at'), run_start)
        return sent

    def run(self, interval=2):
        """Poll independent messages; retain rejected and uncertain outcomes for inspection."""
        while True:
            self.tick()
            time.sleep(interval)
