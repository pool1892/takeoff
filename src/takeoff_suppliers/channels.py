"""Ambiguous's REST transport; credentials never enter message bodies."""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import quote

import httpx


class _MailHTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.images = [], []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden_depth += 1
        if tag == 'img':
            self.images.extend(v for k, v in attrs if k == 'src' and v)
        if not self.hidden_depth and tag in ('p', 'div', 'br', 'li', 'tr', 'pre'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden_depth:
            self.hidden_depth -= 1
        if not self.hidden_depth and tag in ('p', 'div', 'li', 'tr', 'pre'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def email_body(message):
    """Read actual content, never an inbox preview or a tracking-pixel link."""
    parser = _MailHTMLText()
    markup = message.get('body_html')
    if isinstance(markup, str):
        parser.feed(markup)
    for field in ('body_text', 'body_markdown'):
        body = message.get(field)
        if not isinstance(body, str):
            continue
        for src in parser.images:
            body = body.replace('[' + src + ']', '').replace('![](' + src + ')', '')
        # Ambiguous's Markdown conversion can turn an SES tracking image into
        # a bare URL even when the originating message has no authored content.
        body = re.sub(r'\[?https://[^/\s\]]*awstrack\.me/[^\s\]]+\]?', '', body).strip()
        if body:
            return body
    return ''.join(parser.parts).strip()


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

    def read_email(self, message_id):
        data = self.request('GET', f'/api/mail/{quote(message_id, safe="")}', params={'detail': 'full'})
        if data.get('id') != message_id:
            raise ValueError('Full email response does not match the requested message')
        return data

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
            'title': f'Fulfill Takeoff quote {quote_id}'[:255],
            'description': 'Fulfillment details\n\n```json\n' +
                           json.dumps(commitment, indent=2) + '\n```',
            'status': 'todo', 'assignee_id': self.config.user_id})
