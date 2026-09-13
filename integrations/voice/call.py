#!/usr/bin/env python3
"""Buyer-side caller for the optional supplier voice channel (issue #11).

Runs inside the isolated Hermes container. The buyer model chooses every spoken
turn within the contractor's authorization; code enforces the authorization,
turn/time limits, and exact-readback confirmation. Audio travels both ways:
buyer text is synthesized to WAV, supplier WAV is transcribed back. A confirmed
readback is evidence of quoted terms, never an order or a substitution approval.

Wire protocol: supplier branch docs/suppliers/voice.md (turn-based WAV over one
WebSocket, JSON control frames, confirm_quote with the exact readback digest).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
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

import httpx

SUPPLIER_MAX_EXCHANGES = 8
SUPPLIER_MAX_SECONDS = 120
DEFAULT_MAX_EXCHANGES = 6
DEFAULT_MAX_SECONDS = 105
TURN_MAX_SECONDS = 30
TURN_MAX_BYTES = 2_000_000
SAY_MAX_CHARS = 700
SPEAK_RESERVE_SECONDS = 35  # do not start a new spoken exchange with less time left
DEFAULT_HOST = 'supplier.example.invalid'
DEFAULT_MODEL = 'gpt-5.6-luna'      # delegated decisions: the configuration that carried the verified live call
DEFAULT_REASONING = 'xhigh'         # Live delegation accepts none…xhigh; "max" is rejected by /v1/live/sessions
DEFAULT_HOME = '.local/voice'
BUYER_VOICE = 'ash'
OPENAI = 'https://api.openai.com/v1'


def voice_home(env):
    """Evidence directory: writable /opt/data inside the Hermes container, .local/voice elsewhere."""
    return env.get('TAKEOFF_VOICE_HOME') or ('/opt/data/voice' if env.get('TAKEOFF_SANDBOX') == '1' else DEFAULT_HOME)

DECISION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'action': {'type': 'string', 'enum': ['speak', 'confirm', 'end']},
        'say': {'type': 'string'},
        'confirm_digest': {'type': ['string', 'null']},
        'proposal': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'kind': {'type': 'string', 'enum': ['none', 'question', 'counter_total', 'counter_unit',
                                                    'bundle', 'delivery', 'substitute']},
                'amount': {'type': ['string', 'null']},
                'delivery_date': {'type': ['string', 'null']},
                'note': {'type': ['string', 'null']},
            },
            'required': ['kind', 'amount', 'delivery_date', 'note'],
        },
        'heard_clearly': {'type': 'boolean'},
        'reason': {'type': 'string'},
    },
    'required': ['action', 'say', 'confirm_digest', 'proposal', 'heard_clearly', 'reason'],
}

INSTRUCTIONS = """You are Takeoff, a procurement assistant calling a building-material supplier by voice on behalf of a general contractor. The supplier is an AI voice agent. You speak; your words are converted to audio, so write natural spoken English: short sentences, no lists, no JSON, no markdown, at most 60 words per turn. Say quantities with units and prices with currency clearly (for example "forty sheets", "three hundred fifty-eight dollars and thirty-eight cents").

Your job on this call is the objective below, nothing else. Rules enforced on you:
- Never approve or accept a substitute product, a later delivery than the deadline, or any relaxed contractor constraint; if the supplier proposes one, say you will take it back to the contractor.
- Never place, promise, or imply an order. Confirming a readback only confirms what was quoted.
- Propose prices, bundles, or delivery changes only when the authorization allows it and within its limits. Use counter_total for a whole-package counteroffer.
- Confirm a quote (action "confirm") only immediately after a supplier readback that produced candidates, copying its readback_digest exactly, and only when the total and key terms were heard clearly. If a number, unit, quantity, date, or condition was unclear or not heard, ask the supplier to repeat it instead.
- Be efficient: the call has a small exchange and time budget. Get to a complete quoted package quickly: quantity, unit, unit price, fees, delivery date, and total. Then decide whether one bounded negotiating move is worthwhile, then confirm the best readback or end.
- Do not disclose anything outside the allowed disclosures. Do not invent facts about the contractor.

Respond with one JSON object matching the schema. "say" is what you will say next (empty for confirm/end). "proposal" describes any commercial move in "say". "heard_clearly" is whether the last supplier turn's numbers were unambiguous. "reason" is a one-sentence private rationale."""


class CallError(Exception):
    """Fixed, non-secret diagnostic text only."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def wav_seconds(audio):
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        return wav.getnframes() / wav.getframerate()


def validate_turn_audio(audio):
    if not audio or len(audio) > TURN_MAX_BYTES:
        raise CallError('Buyer audio turn exceeds the supplier size limit.')
    try:
        seconds = wav_seconds(audio)
    except (wave.Error, EOFError):
        raise CallError('Synthesized buyer audio is not a complete PCM WAV.') from None
    if seconds > TURN_MAX_SECONDS:
        raise CallError('Buyer audio turn exceeds thirty seconds.')
    return seconds


def quote_total(quote):
    for key in ('total_payable', 'total', 'grand_total', 'total_due'):
        value = quote.get(key)
        if value is not None:
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return None
    return None


_UNITS = {w: i for i, w in enumerate(['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
                                      'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'])}
_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_NUMBER_WORD = re.compile(r'\b((?:' + '|'.join(list(_UNITS) + list(_TENS) + ['hundred', 'thousand', 'and']) + r')(?:[\s-]+(?:'
                          + '|'.join(list(_UNITS) + list(_TENS) + ['hundred', 'thousand', 'and']) + r'))*)\b')


def words_to_number(phrase):
    """'one thousand five hundred eighty five' -> 1585; 'fifteen thirty five' -> 1535 (spoken price style)."""
    words = [w for w in re.split(r'[\s-]+', phrase.strip()) if w and w != 'and']
    if not words:
        return None
    if 'hundred' not in words and 'thousand' not in words:
        groups, index = [], 0
        while index < len(words):
            if words[index] in _TENS and index + 1 < len(words) and words[index + 1] in _UNITS and _UNITS[words[index + 1]] < 10:
                groups.append(_TENS[words[index]] + _UNITS[words[index + 1]])
                index += 2
            else:
                groups.append(_TENS.get(words[index], _UNITS.get(words[index])))
                index += 1
        if any(g is None for g in groups):
            return None
        # "fifteen thirty five" is how a $1,535 price is often read; two groups of two digits.
        return groups[0] * 100 + groups[1] if len(groups) == 2 and groups[1] >= 10 else groups[0] if len(groups) == 1 else None
    total = current = 0
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == 'hundred':
            current = (current or 1) * 100
        elif word == 'thousand':
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    return total + current


def spoken_to_digits(text):
    """Replace spoken number phrases with digits; STT often renders prices as words."""
    def swap(match):
        value = words_to_number(match.group(1))
        return str(value) if value is not None else match.group(1)
    return _NUMBER_WORD.sub(swap, text)


def heard_total(text, total):
    """True when the quote total appears in what the buyer actually heard."""
    if total is None or not text:
        return False
    normalized = spoken_to_digits(re.sub(r'[,$]', '', text.lower()))
    cents = f'{total:.2f}'
    whole, fraction = cents.split('.')
    patterns = [rf'\b{re.escape(cents)}\b', rf'\b{whole}\s+dollars?\s+(and\s+)?{fraction}(\s+cents?)?\b', rf'\b{whole}\s+{fraction}\b']
    if fraction == '00':
        patterns.append(rf'\b{whole}(\.0+)?\s+dollars?')
        patterns.append(rf'\b{whole}\b(?!\.\d)')
    return any(re.search(pattern, normalized) for pattern in patterns)


def extract_offer(quote, confirmed):
    """Public quote facts in one shape; unknown facts stay explicitly unknown."""
    def pick(*keys):
        for key in keys:
            if quote.get(key) is not None:
                return quote[key]
        return 'unknown'
    return {
        'status': 'confirmed_readback' if confirmed else 'candidate_readback_unconfirmed',
        'quote_id': pick('quote_id', 'id'), 'revision': pick('revision'),
        'vendor_id': pick('vendor_id'), 'run_id': pick('run_id'), 'request_id': pick('request_id'),
        'total': str(quote_total(quote)) if quote_total(quote) is not None else 'unknown',
        'currency': pick('currency'), 'lines': pick('lines'), 'fees': pick('fees'),
        'discounts': pick('discounts'), 'taxes': pick('taxes'), 'delivery': pick('delivery'),
        'conditions': pick('conditions'), 'expires_at': pick('expires_at'),
        'quote_status': pick('status'),
    }


class Brain:
    """OpenAI speech and decision calls over one injectable HTTP client."""

    def __init__(self, client, api_key, model):
        self.client = client
        self.headers = {'Authorization': f'Bearer {api_key}'}
        self.model = model

    async def speak(self, text):
        response = await self.client.post(f'{OPENAI}/audio/speech', headers=self.headers, json={
            'model': 'gpt-4o-mini-tts', 'voice': BUYER_VOICE, 'input': text, 'response_format': 'wav',
            'instructions': 'Calm, clear, professional buyer on a phone call. Moderate pace.'})
        response.raise_for_status()
        return response.content

    async def transcribe(self, audio):
        response = await self.client.post(
            f'{OPENAI}/audio/transcriptions', headers=self.headers,
            data={'model': 'gpt-4o-mini-transcribe', 'response_format': 'json'},
            files={'file': ('supplier.wav', audio, 'audio/wav')})
        response.raise_for_status()
        return response.json().get('text', '').strip()

    async def decide(self, context):
        body = {'model': self.model, 'instructions': INSTRUCTIONS,
                'input': json.dumps(context, ensure_ascii=False),
                'text': {'format': {'type': 'json_schema', 'name': 'call_turn', 'strict': True,
                                    'schema': DECISION_SCHEMA}}}
        extras = {'reasoning': {'effort': os.environ.get('TAKEOFF_VOICE_REASONING', DEFAULT_REASONING)}}
        tier = os.environ.get('TAKEOFF_VOICE_SERVICE_TIER', 'priority')
        if tier:
            extras['service_tier'] = tier
        response = await self.client.post(f'{OPENAI}/responses', headers=self.headers, json={**body, **extras})
        if response.status_code == 400 and extras:
            # Optional speed parameters may not apply to every model; the call must still proceed.
            response = await self.client.post(f'{OPENAI}/responses', headers=self.headers, json=body)
        response.raise_for_status()
        text = ''.join(part.get('text', '') for item in response.json().get('output', [])
                       if item.get('type') == 'message' for part in item.get('content', [])
                       if part.get('type') == 'output_text')
        decision = json.loads(text)
        decision.setdefault('proposal', {'kind': 'none', 'amount': None, 'delivery_date': None, 'note': None})
        return decision


def normalize_request(request, *, max_exchanges=SUPPLIER_MAX_EXCHANGES, max_seconds=SUPPLIER_MAX_SECONDS - 5):
    if not isinstance(request, dict):
        raise CallError('Call request must be a JSON object.')
    for key in ('run_id', 'vendor_id', 'objective'):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise CallError(f'Call request needs a non-empty {key}.')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', request['run_id']) or not re.fullmatch(r'[A-Za-z0-9._-]+', request['vendor_id']):
        raise CallError('run_id and vendor_id must be URL-safe identifiers.')
    if not isinstance(request.get('requirements'), list) or not request['requirements']:
        raise CallError('Call request needs a non-empty requirements list.')
    allowed = {'counteroffer': False, 'max_total': None, 'delivery_deadline': None, 'bundle_ask': False}
    allowed.update(request.get('allowed_actions') or {})
    if allowed['max_total'] is not None:
        try:
            allowed['max_total'] = str(Decimal(str(allowed['max_total'])))
        except InvalidOperation:
            raise CallError('allowed_actions.max_total must be a decimal amount.') from None
    constraints = request.get('constraints') or {}
    exchanges = int(constraints.get('max_exchanges') or DEFAULT_MAX_EXCHANGES)
    seconds = float(constraints.get('max_seconds') or DEFAULT_MAX_SECONDS)
    if not 1 <= exchanges <= max_exchanges or not 20 <= seconds <= max_seconds:
        raise CallError('constraints exceed the call limits.')
    return {
        'run_id': request['run_id'], 'vendor_id': request['vendor_id'], 'objective': request['objective'],
        'requirements': request['requirements'], 'known_alternatives': request.get('known_alternatives') or [],
        'allowed_actions': allowed, 'disclosures': request.get('disclosures') or [],
        'constraints': {'max_exchanges': exchanges, 'max_seconds': seconds},
        'supplier_url': request.get('supplier_url'),
    }


def check_decision(decision, state):
    """Return a violation message or None. Code, not the model, holds the authorization."""
    allowed = state['allowed_actions']
    action = decision.get('action')
    proposal = decision.get('proposal') or {}
    kind = proposal.get('kind', 'none')
    if action not in ('speak', 'confirm', 'end'):
        return 'action must be speak, confirm, or end'
    if action == 'confirm':
        digest = decision.get('confirm_digest')
        if not digest or digest not in state['candidates']:
            return 'confirm_digest must exactly match a current candidate readback_digest'
        if not state['candidates'][digest]['total_verified'] and state['can_speak']:
            return 'the quote total was not heard clearly in the supplier audio; ask the supplier to repeat the total before confirming'
        return None
    if action == 'end':
        return None
    if not state['can_speak']:
        return 'no exchange or time budget remains: confirm a current candidate or end'
    say = decision.get('say') or ''
    if not say.strip() or len(say) > SAY_MAX_CHARS:
        return f'say must be 1 to {SAY_MAX_CHARS} characters of spoken text'
    if kind == 'substitute':
        return 'substitutions require contractor approval outside the call; do not propose or accept one'
    if kind in ('counter_total', 'counter_unit') and not allowed['counteroffer']:
        return 'counteroffers are not authorized on this call'
    if kind == 'counter_total' and allowed['max_total'] is not None:
        try:
            if Decimal(str(proposal.get('amount'))) > Decimal(allowed['max_total']):
                return f"counter total exceeds the authorized maximum {allowed['max_total']}"
        except InvalidOperation:
            return 'counter_total needs a decimal amount'
    if kind == 'bundle' and not allowed['bundle_ask']:
        return 'bundle proposals are not authorized on this call'
    if kind == 'delivery' and allowed['delivery_deadline'] and proposal.get('delivery_date'):
        if str(proposal['delivery_date']) > str(allowed['delivery_deadline']):
            return f"delivery later than the contractor deadline {allowed['delivery_deadline']} is not authorized"
    return None


class Call:
    def __init__(self, request, brain, home, connect, live):
        self.request = request
        self.brain = brain
        self.connect = connect
        self.attempt_id = uuid.uuid4().hex[:12]
        self.directory = Path(home) / 'calls' / self.attempt_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.deadline = self.started + request['constraints']['max_seconds']
        self.transcript = []
        self.candidates = {}
        self.decisions = []
        self.exchanges = 0
        self.result = {
            'attempt_id': self.attempt_id, 'call_id': None, 'run_id': request['run_id'],
            'vendor_id': request['vendor_id'], 'status': 'no_connect', 'outcome_reason': None,
            'started_at': utc_now(), 'finished_at': None, 'elapsed_seconds': None, 'exchanges': 0,
            'supplier_limits': None, 'transcript': self.transcript, 'candidates': [],
            'confirmed_quote': None, 'proposed_offer': None, 'authorization': request['allowed_actions'],
            'objective': request['objective'], 'decisions': self.decisions,
            'evidence': {'path': str(self.directory / 'call.json'), 'audio_dir': str(self.directory)},
            'labels': {'transport': 'websocket_audio', 'supplier_business': 'simulated',
                       'live_cross_computer': live, 'buyer_turns': 'model-chosen, code-authorized',
                       'audio': 'buyer TTS out, supplier WAV transcribed in'},
        }

    def remaining(self):
        return self.deadline - time.monotonic()

    def save(self):
        self.result['exchanges'] = self.exchanges
        self.result['candidates'] = [{'readback_digest': d, 'quote': c['quote'], 'total_verified': c['total_verified'],
                                      'verified_by': c['verified_by']} for d, c in self.candidates.items()]
        self.result['elapsed_seconds'] = round(time.monotonic() - self.started, 1)
        (self.directory / 'call.json').write_text(json.dumps(self.result, indent=2, ensure_ascii=False))

    def finish(self, status, reason):
        self.result['status'] = status
        self.result['outcome_reason'] = reason
        self.result['finished_at'] = utc_now()
        if self.result['confirmed_quote'] is None and self.candidates:
            latest = list(self.candidates.values())[-1]['quote']
            self.result['proposed_offer'] = extract_offer(latest, confirmed=False)
        self.save()
        return self.result

    async def recv_json(self, ws):
        budget = self.remaining()
        if budget <= 0:
            raise TimeoutError
        frame = await asyncio.wait_for(ws.recv(), timeout=budget)
        if isinstance(frame, (bytes, bytearray)):
            raise CallError('Unexpected binary frame from supplier.')
        return json.loads(frame)

    def context(self, violation):
        can_speak = self.exchanges < self.request['constraints']['max_exchanges'] and self.remaining() > SPEAK_RESERVE_SECONDS
        return {
            'objective': self.request['objective'], 'requirements': self.request['requirements'],
            'known_alternatives': self.request['known_alternatives'],
            'authorization': self.request['allowed_actions'], 'allowed_disclosures': self.request['disclosures'],
            'budget': {'exchanges_used': self.exchanges, 'exchanges_max': self.request['constraints']['max_exchanges'],
                       'seconds_remaining': round(self.remaining()), 'may_speak_again': can_speak},
            'transcript': self.transcript,
            'current_candidates': [{'readback_digest': d, 'quote': c['quote'], 'total_verified': c['total_verified'],
                                    'verified_by': c['verified_by']} for d, c in self.candidates.items()],
            'previous_decision_rejected': violation,
        }, can_speak

    async def decide(self):
        violation = None
        for _ in range(2):
            context, can_speak = self.context(violation)
            decision = await self.brain.decide(context)
            state = {'allowed_actions': self.request['allowed_actions'], 'candidates': self.candidates, 'can_speak': can_speak}
            violation = check_decision(decision, state)
            self.decisions.append({'at': utc_now(), 'decision': decision, 'violation': violation})
            if violation is None:
                return decision
        return {'action': 'end', 'say': '', 'confirm_digest': None, 'reason': f'ended by code: {violation}'}

    async def run(self, url):
        self.result['supplier_url'] = re.sub(r'\?.*', '', url)
        try:
            async with self.connect(url) as ws:
                await ws.send(json.dumps({'token': self.token}))
                ready = await self.recv_json(ws)
                if ready.get('type') != 'ready':
                    return self.finish('no_connect', f"supplier did not answer ready: {ready.get('type')}")
                self.result['call_id'] = ready.get('call_id')
                self.result['supplier_limits'] = {k: ready.get(k) for k in ('max_exchanges', 'max_seconds', 'disclosure')}
                self.result['status'] = 'unconfirmed'
                self.save()
                while True:
                    decision = await self.decide()
                    action = decision['action']
                    if action == 'end':
                        await ws.send(json.dumps({'type': 'end'}))
                        event = await self.recv_json(ws)
                        return self.finish('unconfirmed', f"buyer ended the call: {decision.get('reason', '')}")
                    if action == 'confirm':
                        candidate = self.candidates[decision['confirm_digest']]
                        await ws.send(json.dumps({'type': 'confirm_quote', 'quote': candidate['quote'],
                                                  'readback_digest': decision['confirm_digest']}))
                        event = await self.recv_json(ws)
                        if event.get('type') == 'confirmed_quote' and event.get('order_placed') is False:
                            self.result['confirmed_quote'] = event['quote']
                            self.result['proposed_offer'] = extract_offer(event['quote'], confirmed=True)
                            self.transcript.append({'turn': self.exchanges, 'speaker': 'supplier', 'event': 'confirmed_quote',
                                                    'at': utc_now(), 'verified_by': candidate['verified_by']})
                            return self.finish('confirmed', 'supplier confirmed the exact readback; not an order')
                        self.transcript.append({'turn': self.exchanges, 'speaker': 'supplier', 'event': event.get('type'),
                                                'text': event.get('message'), 'at': utc_now()})
                        self.candidates.clear()
                        self.save()
                        continue
                    await self.exchange(ws, decision)
        except TimeoutError:
            return self.finish('failed', 'call exceeded the buyer time budget without confirmation')
        except CallError as error:
            return self.finish('failed', str(error))
        except httpx.HTTPError as error:
            return self.finish('failed', f'buyer speech/decision provider error: {type(error).__name__}')
        except OSError as error:
            status = 'no_connect' if self.result['call_id'] is None else 'failed'
            return self.finish(status, f'connection error: {type(error).__name__}')
        except Exception as error:  # websockets closes, invalid handshakes, malformed frames
            status = 'no_connect' if self.result['call_id'] is None else 'failed'
            return self.finish(status, f'{type(error).__name__}: {str(error)[:160]}')

    async def exchange(self, ws, decision):
        turn = self.exchanges + 1
        audio = await self.brain.speak(decision['say'])
        seconds = validate_turn_audio(audio)
        path = self.directory / f'buyer-{turn}.wav'
        path.write_bytes(audio)
        self.transcript.append({'turn': turn, 'speaker': 'buyer', 'text': decision['say'], 'proposal': decision.get('proposal'),
                                'audio_path': str(path), 'audio_seconds': round(seconds, 1), 'at': utc_now()})
        self.save()
        await ws.send(audio)
        self.exchanges = turn
        self.candidates.clear()
        while True:
            event = await self.recv_json(ws)
            kind = event.get('type')
            if kind == 'transcript':
                self.transcript[-1]['supplier_heard'] = event.get('text')
                continue
            if kind == 'supplier_turn':
                break
            if kind == 'error':
                self.transcript.append({'turn': turn, 'speaker': 'supplier', 'event': 'error', 'text': event.get('message'), 'at': utc_now()})
                self.save()
                return
            if kind == 'ended':
                raise CallError('supplier ended the call')
            raise CallError(f'unexpected supplier event {kind}')
        supplier_audio = base64.b64decode(event.get('wav_base64', ''))
        path = self.directory / f'supplier-{turn}.wav'
        path.write_bytes(supplier_audio)
        heard = ''
        try:
            heard = await self.brain.transcribe(supplier_audio) if supplier_audio else ''
        except httpx.HTTPError:
            heard = ''
        entry = {'turn': turn, 'speaker': 'supplier', 'text': event.get('text'), 'heard_text': heard,
                 'audio_path': str(path), 'at': utc_now()}
        try:
            entry['audio_seconds'] = round(wav_seconds(supplier_audio), 1)
        except (wave.Error, EOFError):
            entry['audio_seconds'] = None
        self.transcript.append(entry)
        for candidate in event.get('candidates') or []:
            quote, digest = candidate.get('quote'), candidate.get('readback_digest')
            if not isinstance(quote, dict) or not isinstance(digest, str):
                continue
            total = quote_total(quote)
            by_hearing = heard_total(heard, total)
            by_text = heard_total(event.get('text') or '', total)
            self.candidates[digest] = {'quote': quote, 'total_verified': by_hearing or (by_text and not self.can_ask_repeat()),
                                       'verified_by': 'buyer_transcription' if by_hearing else ('supplier_text' if by_text else None)}
        self.save()

    def can_ask_repeat(self):
        return self.exchanges < self.request['constraints']['max_exchanges'] and self.remaining() > SPEAK_RESERVE_SECONDS


def supplier_url(request, host):
    if request.get('supplier_url'):
        url = request['supplier_url']
        if not url.startswith(('wss://', 'ws://127.0.0.1', 'ws://localhost')):
            raise CallError('supplier_url must be wss:// or a local ws:// address.')
        return url
    if not host or '/' in host:
        raise CallError('TAKEOFF_SUPPLIER_HOST must be a bare hostname.')
    return f"wss://{host}/v1/runs/{request['run_id']}/vendors/{request['vendor_id']}/call"


async def place_call(request, *, http=None, connect=None, env=None):
    """Run one bounded call and return the public result dictionary."""
    env = env if env is not None else os.environ
    request = normalize_request(request)
    api_key = env.get('OPENAI_API_KEY', '')
    token = env.get('TAKEOFF_BUYER_TOKEN', '')
    if not api_key or not token:
        raise CallError('OPENAI_API_KEY and TAKEOFF_BUYER_TOKEN must be set in the runtime environment.')
    url = supplier_url(request, env.get('TAKEOFF_SUPPLIER_HOST', DEFAULT_HOST))
    if connect is None:
        from websockets.asyncio.client import connect as ws_connect
        connect = lambda target: ws_connect(target, max_size=12_000_000, open_timeout=15)  # noqa: E731
    owned = http is None
    client = http or httpx.AsyncClient(timeout=60)
    try:
        brain = Brain(client, api_key, env.get('TAKEOFF_VOICE_MODEL', DEFAULT_MODEL))
        call = Call(request, brain, voice_home(env), connect, live=url.startswith('wss://'))
        call.token = token
        return await call.run(url)
    finally:
        if owned:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description='Place one bounded buyer voice call to a supplier and print the result JSON.')
    parser.add_argument('request', type=Path, help='JSON call request (see integrations/voice/README.md)')
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    try:
        result = asyncio.run(place_call(request))
    except CallError as error:
        print(json.dumps({'status': 'failed', 'outcome_reason': str(error)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'confirmed' else 1


if __name__ == '__main__':
    sys.exit(main())
