#!/usr/bin/env python3
"""GPT-Live buyer voice bridged to the supplier's turn-based call protocol (issue #11).

The buyer speaks through a full-duplex `gpt-live-1` session (wss://api.openai.com
/v1/live/sessions). The supplier only accepts whole WAV turns, so this bridge
collects each buyer utterance into one WAV turn, sends it, streams the supplier's
WAV reply back into the live session at real-time pace, and repeats. Code owns the
hard gates: exact readback confirmation, end of call, exchange/time budgets, and
authorization flags on spoken proposals. A confirmed readback is evidence of
quoted terms, never an order or a substitution approval.

Runs inside the isolated Hermes container. Requires OPENAI_API_KEY and
TAKEOFF_BUYER_TOKEN in the runtime environment; never prints them.
"""
from __future__ import annotations

import argparse
import array
import asyncio
import base64
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
import wave

from integrations.voice.call import (CallError, DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_REASONING, SUPPLIER_MAX_EXCHANGES,
                                     extract_offer, heard_total, normalize_request, quote_total, supplier_url, utc_now, voice_home)

LIVE_URL = 'wss://api.openai.com/v1/live/sessions'
LIVE_MODEL = 'gpt-live-1'
BUYER_VOICE = 'meridian'
RATE = 24000
CHUNK_MS = 100
CHUNK_BYTES = RATE * 2 * CHUNK_MS // 1000
SILENCE = b'\0' * CHUNK_BYTES
GAP_SECONDS = 1.3          # quiet output this long ends a buyer utterance
TURN_CAP_SECONDS = 28.0    # supplier accepts at most 30 s per turn
RESERVE_SECONDS = 30       # below this, no new questions: confirm or end
FORCE_END_SECONDS = 10

LIVE_INSTRUCTIONS = """You are Takeoff, a procurement assistant on a phone call with a building-material supplier, calling on behalf of a general contractor. The supplier is an AI voice agent. Speak naturally and briefly: one point per turn, under twenty seconds, then stop and listen. Say quantities with units and prices with currency clearly.

This line is turn-based: after you stop speaking, the supplier takes up to thirty seconds to answer, so stay completely silent during pauses and never fill silence or repeat yourself.

Your only job is the call objective below. Never approve or accept a substitute product, later delivery than the deadline, or any relaxed contractor constraint; say you will take such proposals back to the contractor. Never place, promise, or imply an order. Before proposing any price, bundle, or delivery change, ask the backend to check authorization; only propose what it allows. When the supplier reads back a complete quote and the numbers were clear, ask the backend to confirm that exact readback. If a number, unit, date, or condition was unclear, ask the supplier to repeat it instead. When told the budget is exhausted, either confirm the current readback through the backend or end the call through the backend.

"""

BACKEND_INSTRUCTIONS = """You are the backend for Takeoff's live buyer voice call. Transcripts can contain mistakes; use the verified facts supplied in context. Tools are the only way to act: check_proposal before any commercial proposal, confirm_quote to confirm an exact supplier readback by its readback_digest (this confirms quoted terms, not an order), end_call to hang up. Never approve substitutes, later delivery, or orders. Return short factual results the voice can paraphrase; do not invent a confirmed quote or a successful action."""

TOOLS = [
    {'type': 'function', 'name': 'check_proposal', 'description': 'Check whether a commercial move is authorized before saying it.',
     'parameters': {'type': 'object', 'additionalProperties': False,
                    'properties': {'kind': {'type': 'string', 'enum': ['counter_total', 'counter_unit', 'bundle', 'delivery', 'substitute']},
                                   'amount': {'type': ['string', 'null']}, 'delivery_date': {'type': ['string', 'null']}},
                    'required': ['kind', 'amount', 'delivery_date']}},
    {'type': 'function', 'name': 'confirm_quote', 'description': 'Confirm the supplier readback identified by its readback_digest. Not an order.',
     'parameters': {'type': 'object', 'additionalProperties': False,
                    'properties': {'readback_digest': {'type': 'string'}}, 'required': ['readback_digest']}},
    {'type': 'function', 'name': 'end_call', 'description': 'End the call without confirming a quote.',
     'parameters': {'type': 'object', 'additionalProperties': False,
                    'properties': {'reason': {'type': 'string'}}, 'required': ['reason']}},
]


def pcm16_from_wav(data):
    """Return mono PCM16 at RATE from any PCM WAV the supplier may send."""
    with wave.open(io.BytesIO(data), 'rb') as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise CallError('Supplier audio is not 16-bit PCM.')
    samples = array.array('h')
    samples.frombytes(frames)
    if sys.byteorder == 'big':
        samples.byteswap()
    if channels > 1:
        samples = array.array('h', [sum(samples[i:i + channels]) // channels for i in range(0, len(samples), channels)])
    if rate != RATE:
        total = int(len(samples) * RATE / rate)
        out = array.array('h', bytes(total * 2))
        for index in range(total):
            position = index * rate / RATE
            left = int(position)
            right = min(left + 1, len(samples) - 1)
            weight = position - left
            out[index] = int(samples[left] * (1 - weight) + samples[right] * weight)
        samples = out
    if sys.byteorder == 'big':
        samples.byteswap()
    return samples.tobytes()


def wav_from_pcm16(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return output.getvalue()


def check_proposal(allowed, kind, amount, delivery_date):
    if kind == 'substitute':
        return 'not authorized: substitutions need contractor approval outside the call'
    if kind in ('counter_total', 'counter_unit') and not allowed['counteroffer']:
        return 'not authorized: no counteroffers on this call'
    if kind == 'counter_total' and allowed['max_total'] is not None:
        try:
            if Decimal(str(amount)) > Decimal(allowed['max_total']):
                return f"not authorized: counter total above the contractor maximum {allowed['max_total']}"
        except InvalidOperation:
            return 'not authorized: counter_total needs a decimal amount'
    if kind == 'bundle' and not allowed['bundle_ask']:
        return 'not authorized: bundle proposals are off on this call'
    if kind == 'delivery' and allowed['delivery_deadline'] and delivery_date and str(delivery_date) > str(allowed['delivery_deadline']):
        return f"not authorized: delivery after the contractor deadline {allowed['delivery_deadline']}"
    return 'authorized'


def spoken_amounts(text):
    return [Decimal(value.replace(',', '')) for value in re.findall(r'\$\s?([\d,]+(?:\.\d{1,2})?)', text)]


class Bridge:
    def __init__(self, request, env, home, supplier_connect, live_connect):
        self.request = request
        self.env = env
        self.supplier_connect = supplier_connect
        self.live_connect = live_connect
        self.attempt_id = uuid.uuid4().hex[:12]
        self.directory = Path(home) / 'calls' / self.attempt_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.deadline = self.started + request['constraints']['max_seconds']
        self.transcript = []
        self.candidates = {}
        self.tool_log = []
        self.flags = []
        self.exchanges = 0
        self.out_pcm = bytearray()
        self.out_text = []
        self.in_text = []
        self.last_out = None
        self.inbound = asyncio.Queue()
        self.supplier_events = asyncio.Queue()
        self.send_lock = asyncio.Lock()
        self.live_lock = asyncio.Lock()
        self.live_started = asyncio.Event()
        self.closed = asyncio.Event()
        self.done = asyncio.Event()
        self.budget_warned = False
        self.live = None
        self.supplier = None
        self.result = {
            'attempt_id': self.attempt_id, 'call_id': None, 'live_session_id': None, 'run_id': request['run_id'],
            'vendor_id': request['vendor_id'], 'status': 'no_connect', 'outcome_reason': None,
            'started_at': utc_now(), 'finished_at': None, 'elapsed_seconds': None, 'exchanges': 0,
            'supplier_limits': None, 'transcript': self.transcript, 'candidates': [], 'confirmed_quote': None,
            'proposed_offer': None, 'authorization': request['allowed_actions'], 'objective': request['objective'],
            'tool_calls': self.tool_log, 'authorization_flags': self.flags, 'live_usage': None,
            'evidence': {'path': str(self.directory / 'call.json'), 'audio_dir': str(self.directory)},
            'labels': {'transport': 'websocket_audio', 'buyer_voice': f'{LIVE_MODEL} full-duplex, bridged to whole-turn WAV',
                       'supplier_business': 'simulated', 'live_cross_computer': None,
                       'hard_gates': 'code: exact readback confirmation, end, budgets; speech: model-chosen with authorization flags'},
        }

    # ---- evidence -------------------------------------------------------
    def remaining(self):
        return self.deadline - time.monotonic()

    def save(self):
        self.result['exchanges'] = self.exchanges
        self.result['candidates'] = [{'readback_digest': d, 'quote': c['quote'], 'total_verified': c['total_verified'],
                                      'verified_by': c['verified_by']} for d, c in self.candidates.items()]
        self.result['elapsed_seconds'] = round(time.monotonic() - self.started, 1)
        (self.directory / 'call.json').write_text(json.dumps(self.result, indent=2, ensure_ascii=False))

    def finish(self, status, reason):
        if self.result['finished_at'] is None:
            self.result['status'] = status
            self.result['outcome_reason'] = reason
            self.result['finished_at'] = utc_now()
            if self.result['confirmed_quote'] is None and self.candidates:
                self.result['proposed_offer'] = extract_offer(list(self.candidates.values())[-1]['quote'], confirmed=False)
        self.done.set()
        self.save()
        return self.result

    # ---- live session ---------------------------------------------------
    async def live_send(self, event):
        async with self.live_lock:
            await self.live.send(json.dumps(event))

    async def instruct(self, content, event_id=None):
        await self.live_send({'type': 'session.instructions.append', 'event_id': event_id or f'instr_{uuid.uuid4().hex[:8]}',
                              'delegation_id': None, 'content': content})

    async def think(self, content):
        await self.live_send({'type': 'session.thinking.append', 'event_id': f'think_{uuid.uuid4().hex[:8]}',
                              'delegation_id': None, 'content': content})

    def session_config(self):
        request = self.request
        instructions = LIVE_INSTRUCTIONS + json.dumps({
            'objective': request['objective'], 'requirements': request['requirements'],
            'known_alternatives': request['known_alternatives'], 'authorization': request['allowed_actions'],
            'allowed_disclosures': request['disclosures'],
            'budget': request['constraints']}, ensure_ascii=False)
        backend = {'model': self.env.get('TAKEOFF_VOICE_MODEL', DEFAULT_MODEL),
                   'instructions': BACKEND_INSTRUCTIONS + '\nCall context: ' + json.dumps(
                       {'objective': request['objective'], 'authorization': request['allowed_actions']}, ensure_ascii=False),
                   'tools': TOOLS, 'tool_choice': 'auto'}
        tier = self.env.get('TAKEOFF_VOICE_SERVICE_TIER', 'priority')
        if tier:
            backend['service_tier'] = tier
        effort = self.env.get('TAKEOFF_VOICE_REASONING', DEFAULT_REASONING)
        if effort:
            backend['reasoning'] = {'effort': effort}
        return {'model': LIVE_MODEL, 'instructions': instructions,
                'audio': {'format': {'type': 'audio/pcm', 'rate': RATE}, 'output': {'voice': BUYER_VOICE}},
                'delegation': {'type': 'responses', 'responses': backend}}

    async def pump_input(self):
        """Feed the live model a continuous real-time stream: supplier audio when present, else silence."""
        next_tick = time.monotonic()
        while not self.done.is_set():
            chunk = SILENCE
            if not self.inbound.empty():
                chunk = self.inbound.get_nowait()
                self.inbound.task_done()
            await self.live_send({'type': 'session.input_audio.append', 'audio': base64.b64encode(chunk).decode('ascii')})
            next_tick += CHUNK_MS / 1000
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))

    async def read_live(self):
        async for frame in self.live:
            event = json.loads(frame)
            kind = event.get('type')
            if kind == 'session.started':
                self.result['live_session_id'] = (event.get('session') or {}).get('id')
                self.live_started.set()
            elif kind == 'session.output_audio.delta':
                self.out_pcm += base64.b64decode(event['delta'])
                self.last_out = time.monotonic()
            elif kind == 'session.output_transcript.delta':
                self.out_text.append(event.get('delta', ''))
                self.last_out = time.monotonic()
            elif kind == 'session.input_transcript.delta':
                self.in_text.append(event.get('delta', ''))
            elif kind == 'response.event':
                await self.handle_backend(event.get('event') or {})
            elif kind == 'session.closed':
                self.result['live_usage'] = event.get('usage')
                self.closed.set()
                return
            elif kind == 'error':
                self.tool_log.append({'at': utc_now(), 'live_error': event.get('error') or event.get('message')})
                if not self.live_started.is_set():
                    self.live_started.set()

    async def handle_backend(self, nested):
        if nested.get('type') != 'response.output_item.done':
            return
        item = nested.get('item') or {}
        if item.get('type') != 'function_call':
            return
        try:
            arguments = json.loads(item.get('arguments') or '{}')
        except json.JSONDecodeError:
            arguments = {}
        name = item.get('name')
        output = await self.run_tool(name, arguments)
        self.tool_log.append({'at': utc_now(), 'tool': name, 'arguments': arguments, 'output': output})
        self.save()
        await self.live_send({'type': 'response.item.create', 'event_id': f'tool_{uuid.uuid4().hex[:8]}',
                              'item': {'type': 'function_call_output', 'call_id': item.get('call_id'), 'output': json.dumps(output)}})
        await self.live_send({'type': 'response.create', 'event_id': f'cont_{uuid.uuid4().hex[:8]}'})

    async def run_tool(self, name, arguments):
        if name == 'check_proposal':
            return {'result': check_proposal(self.request['allowed_actions'], arguments.get('kind'),
                                             arguments.get('amount'), arguments.get('delivery_date'))}
        if name == 'confirm_quote':
            digest = arguments.get('readback_digest')
            candidate = self.candidates.get(digest)
            if not candidate:
                return {'status': 'rejected', 'message': 'no current candidate with that readback_digest; ask for a fresh readback'}
            if not candidate['total_verified']:
                return {'status': 'not_verified', 'message': 'the total was not heard clearly; ask the supplier to repeat the total, then confirm'}
            async with self.send_lock:
                await self.supplier.send(json.dumps({'type': 'confirm_quote', 'quote': candidate['quote'], 'readback_digest': digest}))
            event = await asyncio.wait_for(self.supplier_events.get(), timeout=max(1.0, self.remaining()))
            if event.get('type') == 'confirmed_quote' and event.get('order_placed') is False:
                self.result['confirmed_quote'] = event['quote']
                self.result['proposed_offer'] = extract_offer(event['quote'], confirmed=True)
                self.transcript.append({'turn': self.exchanges, 'speaker': 'supplier', 'event': 'confirmed_quote', 'at': utc_now(),
                                        'verified_by': candidate['verified_by']})
                self.finish('confirmed', 'supplier confirmed the exact readback; not an order')
                return {'status': 'confirmed', 'total': str(quote_total(event['quote'])), 'note': 'quoted terms confirmed; no order placed'}
            self.candidates.clear()
            return {'status': 'rejected', 'message': event.get('message', 'quote changed; request a fresh readback')}
        if name == 'end_call':
            await self.end_supplier(f"buyer ended the call: {arguments.get('reason', '')}")
            return {'status': 'ended'}
        return {'status': 'unknown_tool'}

    async def end_supplier(self, reason):
        if self.done.is_set():
            return
        try:
            async with self.send_lock:
                await self.supplier.send(json.dumps({'type': 'end'}))
        except Exception:
            pass
        self.finish('unconfirmed', reason)

    # ---- supplier side --------------------------------------------------
    async def read_supplier(self):
        try:
            async for frame in self.supplier:
                if isinstance(frame, (bytes, bytearray)):
                    continue
                await self.supplier_events.put(json.loads(frame))
        except Exception as error:
            await self.supplier_events.put({'type': '_closed', 'reason': type(error).__name__})
        else:
            await self.supplier_events.put({'type': '_closed', 'reason': 'closed'})

    def utterance_ready(self):
        if not self.out_pcm or self.last_out is None or not self.inbound.empty():
            return False
        seconds = len(self.out_pcm) / (RATE * 2)
        return time.monotonic() - self.last_out >= GAP_SECONDS or seconds >= TURN_CAP_SECONDS

    async def send_turn(self):
        turn = self.exchanges + 1
        pcm = bytes(self.out_pcm)
        text = ''.join(self.out_text).strip()
        self.out_pcm.clear()
        self.out_text.clear()
        cap = int(TURN_CAP_SECONDS * RATE * 2)
        truncated = len(pcm) > cap
        pcm = pcm[:cap]
        audio = wav_from_pcm16(pcm)
        path = self.directory / f'buyer-{turn}.wav'
        path.write_bytes(audio)
        entry = {'turn': turn, 'speaker': 'buyer', 'text': text, 'audio_path': str(path),
                 'audio_seconds': round(len(pcm) / (RATE * 2), 1), 'truncated': truncated, 'at': utc_now()}
        allowed = self.request['allowed_actions']
        if allowed['max_total'] is not None and any(a > Decimal(allowed['max_total']) for a in spoken_amounts(text)):
            self.flags.append({'turn': turn, 'flag': 'spoken amount above authorized maximum', 'text': text})
            await self.instruct(f"Correction: you may not offer or accept more than {allowed['max_total']} in total. Withdraw any higher figure on your next turn.")
        self.transcript.append(entry)
        self.exchanges = turn
        self.candidates.clear()
        self.in_text.clear()
        self.save()
        async with self.send_lock:
            await self.supplier.send(audio)

    async def receive_supplier_turn(self):
        turn = self.exchanges
        while True:
            event = await asyncio.wait_for(self.supplier_events.get(), timeout=max(1.0, self.remaining()))
            kind = event.get('type')
            if kind == 'transcript':
                self.transcript[-1]['supplier_heard'] = event.get('text')
            elif kind == 'supplier_turn':
                break
            elif kind == 'error':
                self.transcript.append({'turn': turn, 'speaker': 'supplier', 'event': 'error', 'text': event.get('message'), 'at': utc_now()})
                await self.think(f"Line notice: {event.get('message')}")
                return
            elif kind in ('ended', '_closed'):
                raise CallError(f'supplier ended the call ({event.get("reason", kind)})')
        supplier_audio = base64.b64decode(event.get('wav_base64', ''))
        path = self.directory / f'supplier-{turn}.wav'
        path.write_bytes(supplier_audio)
        pcm = pcm16_from_wav(supplier_audio) if supplier_audio else b''
        for start in range(0, len(pcm), CHUNK_BYTES):
            chunk = pcm[start:start + CHUNK_BYTES]
            await self.inbound.put(chunk + b'\0' * (CHUNK_BYTES - len(chunk)))
        entry = {'turn': turn, 'speaker': 'supplier', 'text': event.get('text'), 'audio_path': str(path),
                 'audio_seconds': round(len(pcm) / (RATE * 2), 1), 'at': utc_now(), 'heard_text': ''}
        self.transcript.append(entry)
        candidates = [c for c in event.get('candidates') or [] if isinstance(c.get('quote'), dict) and isinstance(c.get('readback_digest'), str)]
        if candidates:
            summary = '; '.join(f"digest {c['readback_digest']} = quote {c['quote'].get('quote_id', '?')} rev {c['quote'].get('revision', '?')} total {quote_total(c['quote'])}"
                                for c in candidates)
            await self.think(f'Supplier readback candidates available for confirm_quote: {summary}. Confirm only if the total was heard clearly.')
        await self.inbound.join()
        await asyncio.sleep(GAP_SECONDS)   # let the input transcript settle
        heard = ''.join(self.in_text).strip()
        entry['heard_text'] = heard
        for candidate in candidates:
            quote, digest, total = candidate['quote'], candidate['readback_digest'], quote_total(candidate['quote'])
            by_hearing = heard_total(heard, total)
            by_text = heard_total(event.get('text') or '', total)
            self.candidates[digest] = {'quote': quote, 'total_verified': by_hearing or (by_text and not self.can_speak()),
                                       'verified_by': 'buyer_live_transcript' if by_hearing else ('supplier_text' if by_text else None)}
        self.save()

    def can_speak(self):
        return self.exchanges < self.request['constraints']['max_exchanges'] and self.remaining() > RESERVE_SECONDS

    async def budget_guard(self):
        while not self.done.is_set():
            await asyncio.sleep(0.5)
            if self.remaining() <= FORCE_END_SECONDS:
                await self.end_supplier('buyer time budget exhausted without confirmation')
                return
            if not self.budget_warned and not self.can_speak():
                self.budget_warned = True
                await self.instruct('Budget exhausted: ask no new questions. Immediately either confirm the current readback through the backend if its total was clear, or end the call through the backend.')

    async def conversation(self):
        await self.instruct('Begin the call now: greet the supplier, say you are Takeoff calling for a contractor, state the material request in one short breath, then stop and listen.', 'greeting')
        while not self.done.is_set():
            if self.utterance_ready():
                await self.send_turn()
                await self.receive_supplier_turn()
                if self.exchanges >= SUPPLIER_MAX_EXCHANGES:
                    await self.instruct('The supplier accepts no further questions. Confirm the current readback through the backend or end the call now.')
                continue
            await asyncio.sleep(0.1)

    async def run(self, url):
        self.result['supplier_url'] = re.sub(r'\?.*', '', url)
        self.result['labels']['live_cross_computer'] = url.startswith('wss://')
        tasks = []
        try:
            async with self.live_connect() as live:
                self.live = live
                await self.live_send({'type': 'session.start', 'event_id': 'start', 'session': self.session_config()})
                reader = asyncio.create_task(self.read_live())
                tasks.append(reader)
                await asyncio.wait_for(self.live_started.wait(), timeout=20)
                if self.result['live_session_id'] is None:
                    return self.finish('no_connect', f"live session did not start: {self.tool_log[-1] if self.tool_log else 'no event'}")
                tasks.append(asyncio.create_task(self.pump_input()))
                async with self.supplier_connect(url) as supplier:
                    self.supplier = supplier
                    await supplier.send(json.dumps({'token': self.env.get('TAKEOFF_BUYER_TOKEN', '')}))
                    tasks.append(asyncio.create_task(self.read_supplier()))
                    ready = await asyncio.wait_for(self.supplier_events.get(), timeout=15)
                    if ready.get('type') != 'ready':
                        return self.finish('no_connect', f"supplier did not answer ready: {ready.get('type')}")
                    self.result['call_id'] = ready.get('call_id')
                    self.result['supplier_limits'] = {k: ready.get(k) for k in ('max_exchanges', 'max_seconds', 'disclosure')}
                    self.result['status'] = 'unconfirmed'
                    self.save()
                    tasks.append(asyncio.create_task(self.budget_guard()))
                    await asyncio.wait_for(self.conversation(), timeout=max(1.0, self.remaining() + 5))
                    return self.finish(self.result['status'], self.result['outcome_reason'] or 'call ended')
        except TimeoutError:
            return self.finish('failed' if self.result['call_id'] else 'no_connect', 'time budget exceeded without confirmation')
        except CallError as error:
            return self.finish('failed' if self.result['call_id'] else 'no_connect', str(error))
        except Exception as error:
            return self.finish('failed' if self.result['call_id'] else 'no_connect', f'{type(error).__name__}: {str(error)[:160]}')
        finally:
            self.done.set()
            if self.live is not None:
                try:
                    await self.live_send({'type': 'session.close'})
                    await asyncio.wait_for(self.closed.wait(), timeout=10)
                except Exception:
                    pass
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.save()


async def place_live_call(request, *, env=None, supplier_connect=None, live_connect=None):
    env = env if env is not None else os.environ
    request = normalize_request(request)
    api_key, token = env.get('OPENAI_API_KEY', ''), env.get('TAKEOFF_BUYER_TOKEN', '')
    if not api_key or not token:
        raise CallError('OPENAI_API_KEY and TAKEOFF_BUYER_TOKEN must be set in the runtime environment.')
    url = supplier_url(request, env.get('TAKEOFF_SUPPLIER_HOST', DEFAULT_HOST))
    from websockets.asyncio.client import connect
    # Local ws:// mocks bypass the egress proxy; wss:// supplier hosts go through it (HTTPS_PROXY).
    supplier_connect = supplier_connect or (lambda target: connect(
        target, max_size=12_000_000, open_timeout=15, proxy=None if target.startswith('ws://') else True))
    live_connect = live_connect or (lambda: connect(LIVE_URL, additional_headers={'Authorization': f'Bearer {api_key}'},
                                                    max_size=12_000_000, open_timeout=20))
    bridge = Bridge(request, env, voice_home(env), supplier_connect, live_connect)
    return await bridge.run(url)


def main():
    parser = argparse.ArgumentParser(description='Place one bounded GPT-Live buyer call to a supplier and print the result JSON.')
    parser.add_argument('request', type=Path, help='JSON call request (see integrations/voice/README.md)')
    args = parser.parse_args()
    try:
        result = asyncio.run(place_live_call(json.loads(args.request.read_text())))
    except CallError as error:
        print(json.dumps({'status': 'failed', 'outcome_reason': str(error)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'confirmed' else 1


if __name__ == '__main__':
    sys.exit(main())
