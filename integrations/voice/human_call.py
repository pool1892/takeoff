#!/usr/bin/env python3
"""Buyer agent (gpt-live-1) talking live to a human seller in a browser (issue #11 demo path).

The human opens one page and speaks as the supplier over WebRTC; audio flows
browser <-> OpenAI directly. This server owns everything on the buyer side:
it creates the Live session with the buyer's objective and authorization
(POST /v1/live/sessions with the browser's SDP offer), attaches a sideband
WebSocket to record both transcripts, executes the backend tools
(check_proposal, record_quote, confirm_readback, end_call), and writes the
call evidence. Terms come from a human's speech: a recorded quote is
"heard, unconfirmed" until the buyer reads it back and the seller confirms
aloud; that confirmation is evidence of quoted terms, never an order.

Run on the buyer side with OPENAI_API_KEY in the environment; expose the port
over HTTPS (tailscale serve / funnel) so a seller at another location can open
it. The share URL carries a token so nobody else can mint sessions on the key.
"""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import uuid

import httpx

from integrations.voice.call import CallError, DEFAULT_MODEL, DEFAULT_REASONING, normalize_request, utc_now, voice_home
from integrations.voice.live import LIVE_MODEL, check_proposal

SESSIONS_URL = 'https://api.openai.com/v1/live/sessions'
ATTACH_URL = 'wss://api.openai.com/v1/live/sessions/{id}/attach'
BUYER_VOICE = 'meridian'
HUMAN_MAX_SECONDS = 900
AFFIRMATIVE = re.compile(r"\b(yes|yeah|yep|correct|confirmed?|that's right|that is right|exactly|agreed|deal|sounds right)\b", re.I)

LIVE_INSTRUCTIONS = """You are Takeoff, a procurement assistant on a live phone call with a building-material supplier, calling on behalf of a general contractor. The person on the line is a human at the supplier. Be warm, brief, and professional: one point at a time, then listen. Say quantities with units and prices with currency clearly.

Your only job is the call objective below. Never approve or accept a substitute product, later delivery than the deadline, or any relaxed contractor constraint; say you will take such proposals back to the contractor. Never place, promise, or imply an order. Before proposing any price, bundle, or delivery change, ask the backend to check authorization and only propose what it allows. Once the supplier states a quote, ask the backend to record it, then read the full terms back to the supplier (quantity, unit price, fees, delivery date, tax treatment, total) and ask them to confirm. When they confirm aloud, ask the backend to confirm the readback. If a number, unit, date, or condition was unclear, ask the supplier to repeat it. When the objective is met or the supplier cannot help, thank them and ask the backend to end the call.

"""

BACKEND_INSTRUCTIONS = """You are the backend for Takeoff's live buyer voice call with a human supplier. Transcripts can contain mistakes; use the latest context. Tools are the only way to act: check_proposal before any commercial proposal; record_quote when the supplier states terms (fill only what was actually said, null for unknown); confirm_readback after the buyer read the terms back and the supplier confirmed aloud (this confirms quoted terms, not an order); end_call to hang up. Never approve substitutes, later delivery, or orders. Return short factual results the voice can paraphrase; never invent a confirmation or a successful action."""

QUOTE_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'supplier_name': {'type': ['string', 'null']},
        'lines': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                             'properties': {'description': {'type': 'string'}, 'quantity': {'type': ['number', 'null']},
                                                            'unit': {'type': ['string', 'null']}, 'unit_price': {'type': ['string', 'null']}},
                                             'required': ['description', 'quantity', 'unit', 'unit_price']}},
        'fees': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                            'properties': {'name': {'type': 'string'}, 'amount': {'type': 'string'}}, 'required': ['name', 'amount']}},
        'total': {'type': ['string', 'null']}, 'currency': {'type': ['string', 'null']},
        'delivery_date': {'type': ['string', 'null']}, 'delivery_days': {'type': ['integer', 'null']},
        'tax_status': {'type': ['string', 'null'], 'enum': ['included', 'excluded', 'unknown', None]},
        'expires': {'type': ['string', 'null']}, 'conditions': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['supplier_name', 'lines', 'fees', 'total', 'currency', 'delivery_date', 'delivery_days', 'tax_status', 'expires', 'conditions'],
}

TOOLS = [
    {'type': 'function', 'name': 'check_proposal', 'description': 'Check whether a commercial move is authorized before saying it.',
     'parameters': {'type': 'object', 'additionalProperties': False,
                    'properties': {'kind': {'type': 'string', 'enum': ['counter_total', 'counter_unit', 'bundle', 'delivery', 'substitute']},
                                   'amount': {'type': ['string', 'null']}, 'delivery_date': {'type': ['string', 'null']}},
                    'required': ['kind', 'amount', 'delivery_date']}},
    {'type': 'function', 'name': 'record_quote', 'description': 'Record the terms the supplier just stated, exactly as heard; null when not said.',
     'parameters': QUOTE_SCHEMA},
    {'type': 'function', 'name': 'confirm_readback', 'description': 'After the buyer read the recorded terms back and the supplier confirmed aloud, mark that quote confirmed. Not an order.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'properties': {'quote_id': {'type': 'string'}}, 'required': ['quote_id']}},
    {'type': 'function', 'name': 'end_call', 'description': 'End the call.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'properties': {'reason': {'type': 'string'}}, 'required': ['reason']}},
]


def money(value):
    try:
        return Decimal(str(value).replace(',', '').replace('$', ''))
    except (InvalidOperation, AttributeError):
        return None


def to_supplier_quote(heard, quote_id, request, session_id, confirmed):
    """Public-quote shape the buyer's normalize_quote understands; unknowns stay explicit."""
    lines, subtotal = [], Decimal(0)
    complete = True
    for line in heard.get('lines') or []:
        price, quantity = money(line.get('unit_price')), line.get('quantity')
        entry = {'description': line.get('description'), 'quantity': quantity, 'unit': line.get('unit'),
                 'unit_price': str(price) if price is not None else None}
        if price is not None and quantity is not None:
            entry['line_total'] = str(price * Decimal(str(quantity)))
            subtotal += price * Decimal(str(quantity))
        else:
            complete = False
        lines.append(entry)
    fees = [{'name': f.get('name'), 'amount': str(money(f.get('amount')))} for f in heard.get('fees') or [] if money(f.get('amount')) is not None]
    computed = subtotal + sum(Decimal(f['amount']) for f in fees)
    total = money(heard.get('total'))
    tax = heard.get('tax_status') or 'unknown'
    taxes = {'status': 'included'} if tax == 'included' else ({'status': 'excluded', 'agreed': False} if tax == 'excluded' else {'status': 'unknown', 'amount': None})
    delivery = {}
    if heard.get('delivery_date'):
        delivery['date'] = heard['delivery_date']
    if heard.get('delivery_days') is not None:
        delivery['days'] = heard['delivery_days']
    return {
        'quote_id': quote_id, 'id': quote_id, 'run_id': request['run_id'], 'request_id': f'live:{session_id}',
        'vendor_id': request['vendor_id'], 'revision': 1, 'currency': heard.get('currency') or 'USD',
        'status': 'issued' if confirmed else 'heard_unconfirmed', 'source': 'human_vendor_spoken',
        'supplier_name': heard.get('supplier_name'), 'lines': lines,
        'subtotal': str(subtotal) if complete and lines else None, 'fees': fees, 'discounts': [], 'taxes': taxes,
        'delivery': delivery or None, 'expires_at': heard.get('expires'), 'conditions': heard.get('conditions') or [],
        'total': str(total) if total is not None else None,
        'arithmetic': 'consistent' if (complete and lines and total is not None and computed == total)
        else ('mismatch' if (complete and lines and total is not None) else 'incomplete'),
        'computed_total_from_lines': str(computed) if complete and lines else None,
        'evidence_refs': [f'live:{session_id}'],
    }


class HumanCall:
    """One live session: sideband observer, tool executor, evidence writer."""

    def __init__(self, request, env, home, session_id):
        self.request = request
        self.env = env
        self.session_id = session_id
        self.attempt_id = uuid.uuid4().hex[:12]
        self.directory = Path(home) / 'calls' / self.attempt_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.seller_text, self.buyer_text = [], []
        self.candidates, self.tool_log, self.flags = {}, [], []
        self.quote_count = 0
        self.ws = None
        self.lock = asyncio.Lock()
        self.result = {
            'attempt_id': self.attempt_id, 'call_id': session_id, 'live_session_id': session_id,
            'run_id': request['run_id'], 'vendor_id': request['vendor_id'], 'status': 'connecting', 'outcome_reason': None,
            'started_at': utc_now(), 'finished_at': None, 'elapsed_seconds': None,
            'transcript': {'seller': self.seller_text, 'buyer': self.buyer_text}, 'candidates': [],
            'confirmed_quote': None, 'proposed_offer': None, 'authorization': request['allowed_actions'],
            'objective': request['objective'], 'tool_calls': self.tool_log, 'authorization_flags': self.flags, 'live_usage': None,
            'evidence': {'path': str(self.directory / 'call.json')},
            'labels': {'transport': 'webrtc_browser_to_openai; buyer sideband', 'buyer_voice': f'{LIVE_MODEL} full-duplex',
                       'seller': 'human teammate playing the supplier (simulated business)', 'live_cross_computer': True,
                       'hard_gates': 'code: recorded terms, readback + spoken confirmation, authorization checks, end; speech: model-chosen'},
        }
        self.save()

    def save(self):
        self.result['candidates'] = list(self.candidates.values())
        self.result['elapsed_seconds'] = round(time.monotonic() - self.started, 1)
        (self.directory / 'call.json').write_text(json.dumps(self.result, indent=2, ensure_ascii=False))

    def finish(self, status, reason):
        if self.result['finished_at'] is None:
            self.result['status'] = status
            self.result['outcome_reason'] = reason
            self.result['finished_at'] = utc_now()
            if self.result['confirmed_quote'] is None and self.candidates:
                self.result['proposed_offer'] = list(self.candidates.values())[-1]['quote']
        self.save()

    def spoken(self, rows, since_ms=0):
        return ''.join(r['text'] for r in rows if r['end_ms'] >= since_ms)

    async def send(self, event):
        async with self.lock:
            await self.ws.send(json.dumps(event))

    async def run_tool(self, name, arguments):
        allowed = self.request['allowed_actions']
        if name == 'check_proposal':
            verdict = check_proposal(allowed, arguments.get('kind'), arguments.get('amount'), arguments.get('delivery_date'))
            if not verdict.startswith('authorized'):
                self.flags.append({'at': utc_now(), 'blocked_proposal': arguments, 'verdict': verdict})
            return {'result': verdict}
        if name == 'record_quote':
            self.quote_count += 1
            quote_id = f'human-{self.session_id[-6:]}-{self.quote_count}'
            quote = to_supplier_quote(arguments, quote_id, self.request, self.session_id, confirmed=False)
            recorded_at = max([r['end_ms'] for r in self.seller_text] or [0])
            self.candidates[quote_id] = {'quote_id': quote_id, 'quote': quote, 'heard': arguments, 'recorded_at_ms': recorded_at,
                                         'confirmed': False, 'verified_by': None}
            note = {'consistent': 'arithmetic checks out', 'mismatch': f"lines plus fees compute to {quote['computed_total_from_lines']}, not the stated total; clarify",
                    'incomplete': 'some quantities or prices missing; ask for them'}[quote['arithmetic']]
            return {'status': 'recorded', 'quote_id': quote_id, 'total': quote['total'], 'note': note,
                    'next': 'read every term back to the supplier and ask them to confirm, then call confirm_readback'}
        if name == 'confirm_readback':
            candidate = self.candidates.get(arguments.get('quote_id'))
            if not candidate:
                return {'status': 'rejected', 'message': 'unknown quote_id; record the quote first'}
            readback = self.spoken(self.buyer_text, candidate['recorded_at_ms'])
            total = money(candidate['quote'].get('total'))
            read_total = total is not None and (f'{total:.2f}' in readback.replace(',', '') or f'{total:.0f}' in readback.replace(',', ''))
            seller_after = self.spoken(self.seller_text, candidate['recorded_at_ms'])
            affirmed = bool(AFFIRMATIVE.search(seller_after[-400:]))
            if not read_total:
                return {'status': 'not_verified', 'message': 'the buyer transcript does not show the total being read back; read the full terms back first'}
            if not affirmed:
                return {'status': 'not_verified', 'message': 'no spoken confirmation from the supplier yet; ask them to confirm the terms are correct'}
            candidate['confirmed'] = True
            candidate['verified_by'] = 'seller_spoken_confirmation'
            candidate['confirmation_excerpt'] = seller_after[-400:]
            candidate['quote'] = to_supplier_quote(candidate['heard'], candidate['quote_id'], self.request, self.session_id, confirmed=True)
            self.result['confirmed_quote'] = candidate['quote']
            self.result['proposed_offer'] = candidate['quote']
            self.result['status'] = 'confirmed'
            self.result['outcome_reason'] = 'seller confirmed the readback aloud; not an order'
            self.save()
            return {'status': 'confirmed', 'total': candidate['quote']['total'], 'note': 'quoted terms confirmed; no order placed'}
        if name == 'end_call':
            if self.result['status'] != 'confirmed':
                self.finish('unconfirmed', f"buyer ended the call: {arguments.get('reason', '')}")
            else:
                self.finish('confirmed', self.result['outcome_reason'])
            await self.send({'type': 'session.close', 'event_id': 'close'})
            return {'status': 'ended'}
        return {'status': 'unknown_tool'}

    async def observe(self):
        from websockets.asyncio.client import connect
        api_key = self.env.get('OPENAI_API_KEY', '')
        try:
            async with connect(ATTACH_URL.format(id=self.session_id), additional_headers={'Authorization': f'Bearer {api_key}'},
                               max_size=12_000_000, open_timeout=20) as ws:
                self.ws = ws
                self.result['status'] = 'in_call'
                self.save()
                deadline = self.started + self.request['constraints']['max_seconds']
                async for frame in ws:
                    event = json.loads(frame)
                    kind = event.get('type')
                    if kind == 'session.input_transcript.delta':
                        self.seller_text.append({'text': event.get('delta', ''), 'start_ms': event.get('start_ms'), 'end_ms': event.get('end_ms') or 0})
                    elif kind == 'session.output_transcript.delta':
                        self.buyer_text.append({'text': event.get('delta', ''), 'start_ms': event.get('start_ms'), 'end_ms': event.get('end_ms') or 0})
                    elif kind == 'response.event':
                        nested = event.get('event') or {}
                        item = nested.get('item') or {}
                        if nested.get('type') == 'response.output_item.done' and item.get('type') == 'function_call':
                            try:
                                arguments = json.loads(item.get('arguments') or '{}')
                            except json.JSONDecodeError:
                                arguments = {}
                            output = await self.run_tool(item.get('name'), arguments)
                            self.tool_log.append({'at': utc_now(), 'tool': item.get('name'), 'arguments': arguments, 'output': output})
                            self.save()
                            await self.send({'type': 'response.item.create', 'event_id': f'tool_{uuid.uuid4().hex[:8]}',
                                             'item': {'type': 'function_call_output', 'call_id': item.get('call_id'), 'output': json.dumps(output)}})
                            await self.send({'type': 'response.create', 'event_id': f'cont_{uuid.uuid4().hex[:8]}'})
                    elif kind == 'session.closed':
                        self.result['live_usage'] = event.get('usage')
                        break
                    elif kind == 'error':
                        self.tool_log.append({'at': utc_now(), 'live_error': event.get('error') or event.get('message')})
                    if time.monotonic() > deadline and self.result['finished_at'] is None:
                        self.finish('unconfirmed' if self.result['status'] != 'confirmed' else 'confirmed', 'time budget exhausted')
                        await self.send({'type': 'session.close', 'event_id': 'close_budget'})
                    if len(self.seller_text) + len(self.buyer_text) < 400 or (len(self.seller_text) + len(self.buyer_text)) % 20 == 0:
                        self.save()
        except Exception as error:
            self.finish('failed' if self.result['status'] != 'confirmed' else 'confirmed', f'{type(error).__name__}: {str(error)[:160]}')
        finally:
            if self.result['finished_at'] is None:
                self.finish('confirmed' if self.result['status'] == 'confirmed' else 'unconfirmed', 'session closed by the seller')
            self.save()


class Server:
    def __init__(self, request_path, env, home, token):
        self.request_path = Path(request_path)
        self.env = env
        self.home = home
        self.token = token
        self.calls = {}
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.page = (Path(__file__).with_name('human.html')).read_text()

    def request(self):
        return normalize_request(json.loads(self.request_path.read_text()), max_exchanges=999, max_seconds=HUMAN_MAX_SECONDS)

    def session_config(self, request):
        backend = {'model': self.env.get('TAKEOFF_VOICE_MODEL', DEFAULT_MODEL), 'tools': TOOLS, 'tool_choice': 'auto',
                   'instructions': BACKEND_INSTRUCTIONS + '\nCall context: ' + json.dumps(
                       {'objective': request['objective'], 'requirements': request['requirements'], 'authorization': request['allowed_actions']}, ensure_ascii=False)}
        if self.env.get('TAKEOFF_VOICE_SERVICE_TIER', 'priority'):
            backend['service_tier'] = self.env.get('TAKEOFF_VOICE_SERVICE_TIER', 'priority')
        if self.env.get('TAKEOFF_VOICE_REASONING', DEFAULT_REASONING):
            backend['reasoning'] = {'effort': self.env.get('TAKEOFF_VOICE_REASONING', DEFAULT_REASONING)}
        session = {'model': LIVE_MODEL, 'audio': {'output': {'voice': BUYER_VOICE}},
                   'instructions': LIVE_INSTRUCTIONS + json.dumps({k: request[k] for k in ('objective', 'requirements', 'known_alternatives', 'allowed_actions', 'disclosures')}, ensure_ascii=False),
                   'delegation': {'type': 'responses', 'responses': backend}}
        if self.env.get('TAKEOFF_VOICE_STORE') == '1':
            session['store'] = True
        return session

    def create_session(self, sdp):
        request = self.request()
        with httpx.Client(timeout=60) as client:
            response = client.post(SESSIONS_URL, headers={'Authorization': f"Bearer {self.env.get('OPENAI_API_KEY', '')}"},
                                   json={'session': self.session_config(request), 'transport': {'type': 'webrtc', 'sdp': sdp}})
        if response.status_code >= 400:
            raise CallError(f'Live session creation failed: HTTP {response.status_code}')
        body = response.json()
        session_id = body.get('id') or (body.get('session') or {}).get('id')
        answer = body.get('sdp') or (body.get('transport') or {}).get('sdp')
        if not session_id or not answer:
            raise CallError('Live session response lacked id or sdp')
        call = HumanCall(request, self.env, self.home, session_id)
        self.calls[call.attempt_id] = call
        asyncio.run_coroutine_threadsafe(call.observe(), self.loop)
        return {'id': session_id, 'sdp': answer, 'attempt_id': call.attempt_id}


def make_handler(server):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            return self.path.startswith(f'/s/{server.token}/') or self.path == f'/s/{server.token}'

        def do_GET(self):
            if not self.authorized():
                return self.reply(404, {'error': 'not found'})
            tail = self.path[len(f'/s/{server.token}'):].strip('/')
            if tail == '':
                return self.reply(200, server.page.encode(), 'text/html; charset=utf-8')
            if tail == 'api/calls':
                return self.reply(200, {k: {'status': c.result['status'], 'confirmed_quote': c.result['confirmed_quote'],
                                            'outcome_reason': c.result['outcome_reason'], 'path': c.result['evidence']['path']}
                                        for k, c in server.calls.items()})
            if tail.startswith('api/calls/') and tail[10:] in server.calls:
                return self.reply(200, server.calls[tail[10:]].result)
            return self.reply(404, {'error': 'not found'})

        def do_POST(self):
            if not self.authorized() or not self.path.endswith('/api/session'):
                return self.reply(404, {'error': 'not found'})
            origin, host = self.headers.get('Origin', ''), self.headers.get('Host', '')
            if not origin or origin.split('://', 1)[-1] != host:
                return self.reply(403, {'error': 'unexpected request origin'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                return self.reply(400, {'error': 'an SDP offer is required'})
            try:
                sdp = json.loads(self.rfile.read(length)).get('sdp', '')
                if not isinstance(sdp, str) or not sdp.strip():
                    raise ValueError
            except (ValueError, AttributeError):
                return self.reply(400, {'error': 'an SDP offer is required'})
            try:
                return self.reply(201, server.create_session(sdp))
            except CallError as error:
                return self.reply(502, {'error': str(error)})

        def log_message(self, fmt, *args):
            sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Serve the human-seller live call page and buyer sideband.')
    parser.add_argument('--request', type=Path, default=Path(__file__).with_name('example-request.json'))
    parser.add_argument('--bind', default='0.0.0.0' if os.environ.get('TAKEOFF_SANDBOX') == '1' else '127.0.0.1',
                        help='inside the Hermes container the launcher publishes 127.0.0.1:3000, so bind all interfaces there')
    parser.add_argument('--port', type=int, default=int(os.environ.get('TAKEOFF_VOICE_WEB_PORT', '3000')))
    parser.add_argument('--public-url', default='', help='HTTPS origin the seller will use (printed in the share link)')
    args = parser.parse_args()
    if not os.environ.get('OPENAI_API_KEY'):
        raise SystemExit('OPENAI_API_KEY must be set in the environment (never pass it as an argument).')
    token = os.environ.get('TAKEOFF_VOICE_WEB_TOKEN') or secrets.token_urlsafe(12)
    server = Server(args.request, os.environ, voice_home(os.environ), token)
    server.request()  # fail early on a bad request file
    httpd = ThreadingHTTPServer((args.bind, args.port), make_handler(server))
    base = args.public_url.rstrip('/') or f'http://127.0.0.1:{args.port}'
    print(f'Seller page: {base}/s/{token}/   (evidence under {server.home}/calls)', flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
