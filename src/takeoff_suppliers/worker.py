"""Poll configured demo channels and relay authenticated buyer inputs."""
import hashlib
import json
import time

from .runtime import RecoveryRequired


class SupplierWorker:
    def __init__(self, market, runtime, state, run_id, vendor_id, channel,
                 *, buyers, chat_buyers=None):
        self.market, self.runtime, self.state = market, runtime, state
        self.run_id, self.vendor_id, self.channel = run_id, vendor_id, channel
        # Explicit sender -> buyer mapping is configured outside model context.
        self.buyers = {email.lower(): buyer for email, buyer in buyers.items()}
        self.chat_buyers = chat_buyers or {}

    def _respond(self, buyer_id, body, source_id, kind):
        """Structured A2A decisions are explicit; free text is negotiation only."""
        try:
            envelope = json.loads(body)
        except (ValueError, TypeError):
            envelope = None
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
                task = self.state.get(task_key)
                if task and task.get('pending'):
                    raise RecoveryRequired('Fulfillment task creation uncertain; inspect Ambiguous before retry')
                if task is None:
                    self.state.put(task_key, {'pending': True})
                    task = self.channel.create_fulfillment_task(record)
                    self.state.put(task_key, task)
                return {'message': 'Simulated commitment:\n' + json.dumps(record) +
                        '\nSupplier fulfillment task: ' + str(task['id']), 'offers': []}
            if action not in ('inquiry', 'counter'):
                raise ValueError('Unsupported A2A message type')
        return self.runtime.respond(self.run_id, self.vendor_id, buyer_id, body,
                                    channel=kind, request_id=source_id)

    def _process(self, source_id, buyer_id, body, send, *, retry_safe=False):
        key = f'message:{self.run_id}:{self.vendor_id}:{source_id}'
        item = self.state.get(key)
        if item and item.get('status') in ('sent', 'ignored'):
            return False
        if self.market.is_paused(self.run_id, self.vendor_id):
            self.state.put(key, {'status': 'queued', 'buyer_id': buyer_id, 'body': body})
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
            self.state.put(key, {'status': 'processing'})
            result = self._respond(buyer_id, body, source_id,
                                   'chat' if source_id.startswith('chat:') else 'email')
            item = {'status': 'ready', 'result': result}
            self.state.put(key, item)
        if item['result'].get('status') == 'paused':
            self.state.put(key, {'status': 'queued'})
            return False
        item['status'] = 'sending'
        self.state.put(key, item)
        receipt = send(item['result']['message'], hashlib.sha256(key.encode()).hexdigest())
        item.update(status='sent', receipt=receipt)
        self.state.put(key, item)
        return True

    def tick(self):
        if self.channel.identity is None:
            self.channel.verify_identity()
        identity = self.channel.identity
        own_emails = {identity.get(k, '').lower() for k in ('workspace_email', 'primary_email')
                      if identity.get(k)}
        sent = 0
        for message in reversed(self.channel.inbox()):
            sender = message.get('from') or {}
            address = (sender.get('email', '') if isinstance(sender, dict) else sender).lower()
            if address in own_emails or address not in self.buyers:
                continue
            def send(body, key, m=message, address=address):
                return self.channel.send_email(address, body, key=key,
                    subject='Re: ' + m.get('subject', 'Takeoff inquiry'), thread_id=m.get('thread_id'),
                    in_reply_to=m.get('message_id'))
            sent += self._process('email:' + message['id'], self.buyers[address],
                                  message.get('body_text') or '', send, retry_safe=True)
        for channel_id, thread_id in self.channel.config.chat_threads:
            for message in self.channel.thread(channel_id, thread_id):
                sender = (message.get('author') or {}).get('id')
                if sender == identity['id'] or sender not in self.chat_buyers or message.get('deleted_at'):
                    continue
                def send(body, key, channel_id=channel_id, thread_id=thread_id):
                    return self.channel.send_chat(channel_id, thread_id, body)
                sent += self._process('chat:' + message['id'], self.chat_buyers[sender],
                                      message.get('content', ''), send)
        return sent

    def run(self, interval=2):
        """Fail visibly on auth or uncertain effects; preserve state for resumption."""
        while True:
            self.tick()
            time.sleep(interval)
