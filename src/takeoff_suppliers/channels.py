"""Ambiguous's REST transport; credentials never enter message bodies."""
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class VendorConnection:
    vendor_id: str
    token: str = field(repr=False)
    workspace_id: str = ''
    buyer_workspace_id: str = ''
    user_id: str = ''
    base_url: str = 'https://app.ambiguous.ai'
    chat_threads: tuple[tuple[str, str], ...] = ()


class AmbiguousClient:
    def __init__(self, config: VendorConnection, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=30)
        self.identity = None

    def request(self, method, path, **kwargs):
        headers = {'Authorization': f'Bearer {self.config.token}', 'API-Version': '1'}
        headers.update(kwargs.pop('headers', {}))
        response = self.client.request(method, self.config.base_url.rstrip('/') + path,
                                       headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    def verify_identity(self, require_buyer=True):
        c = self.config
        if not c.workspace_id:
            raise ValueError('Configure the current supplier workspace ID')
        if require_buyer and not c.buyer_workspace_id:
            raise ValueError('Buyer workspace is pending; configure it before starting the worker')
        if c.buyer_workspace_id and c.workspace_id == c.buyer_workspace_id:
            raise ValueError('Configure distinct current buyer and supplier workspace IDs')
        identity = self.request('GET', '/api/users/me')
        if identity.get('workspace_id') != c.workspace_id or identity.get('needs_workspace_setup'):
            raise ValueError('Supplier credential does not belong to the configured workspace')
        if not c.user_id or identity.get('id') != c.user_id:
            raise ValueError('Supplier credential does not match the configured vendor user')
        self.identity = identity
        return identity

    def inbox(self):
        """Flatten every page so replies in existing threads cannot disappear."""
        result, params = [], {'threaded': 'false', 'detail': 'full', 'limit': 100}
        while True:
            page = self.request('GET', '/api/mail/inbox', params=params)
            result.extend(page['data'])
            if not page.get('has_more'):
                return result
            cursor = page.get('next_cursor')
            if not cursor or cursor == params.get('cursor'):
                raise ValueError('Inbox pagination did not advance')
            params['cursor'] = cursor

    def thread(self, channel_id, message_id):
        path = f'/api/channels/{quote(channel_id, safe="")}/messages/{quote(message_id, safe="")}/thread'
        data = self.request('GET', path)
        return [data['parent'], *data['replies']]

    def send_email(self, recipient, body, *, key, subject='Takeoff supplier response', thread_id=None,
                   in_reply_to=None):
        payload = {'to': [recipient], 'subject': subject, 'body_markdown': body,
                   'include_signature': False, 'undo_send_seconds': 0}
        if thread_id:
            payload['thread_id'] = thread_id
        if in_reply_to:
            payload['in_reply_to'] = in_reply_to
        result = self.request('POST', '/api/mail/send', json=payload,
                              headers={'Idempotency-Key': key})
        if result.get('delivery_status') in ('failed', 'suppressed'):
            raise ValueError('Ambiguous did not deliver the supplier message')
        return result

    def send_chat(self, channel_id, thread_id, body):
        # Chat thread_key is a stitching key, NOT a documented send deduplication key.
        return self.request('POST', f'/api/channels/{quote(channel_id, safe="")}/messages',
                            json={'content': body, 'thread_id': thread_id})

    def readonly_mcp(self):
        return {'type': 'mcp', 'server_label': 'ambiguous', 'required': True,
                'transport': {'type': 'http', 'server_url': self.config.base_url.rstrip('/') + '/mcp',
                              'authorization': f'Bearer {self.config.token}'},
                'allowed_tools': ['auth_whoami', 'list_inbox', 'chat_thread_get']}

    def create_fulfillment_task(self, commitment):
        import json
        quote_id = commitment.get('quote_id') or commitment.get('id')
        return self.request('POST', '/api/tasks', json={
            'title': f'[Simulated] Fulfill Takeoff quote {quote_id}'[:255],
            'description': 'Demo commitment only; no real purchase or dispatch.\n\n```json\n' +
                           json.dumps(commitment, indent=2) + '\n```',
            'status': 'todo', 'assignee_id': self.config.user_id})
