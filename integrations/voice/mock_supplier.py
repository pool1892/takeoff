#!/usr/bin/env python3
"""Scripted local stand-in for the supplier voice endpoint (protocol from PR #30).

This is a test fixture, not the supplier: it cannot hear the buyer, follows a fixed
script, and its quote is synthetic. It exists so the buyer bridge can be exercised
without the supplier computer. With --tts it voices its lines through OpenAI TTS
using the buyer's key; otherwise it sends short silent WAVs.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import uuid
import wave

import httpx

GREETING = "Thanks for calling Ridge Building Supply, this is an AI voice assistant. What materials do you need today, and where is the job?"
READBACK_1 = ("I can do forty sheets of half-inch CDX plywood, four by eight, at $38.50 per sheet, subtotal $1540.00, plus a $45.00 delivery fee, "
              "total $1585.00, delivered Thursday, September 17. Tax is not included. Please confirm those exact quoted terms; this is not an order.")
READBACK_2 = ("Best I can do is $37.25 per sheet: forty sheets, subtotal $1490.00, plus $45.00 delivery, total $1535.00, still Thursday the 17th, "
              "tax not included. Please confirm those exact quoted terms; this is not an order.")
CLOSING = "Understood. Anything else I can quote for you today?"


def quote(run_id, vendor_id, call_id, revision, unit_price, subtotal, total):
    return {
        'quote_id': f'mock-{call_id[:8]}-{revision}', 'id': f'mock-{call_id[:8]}-{revision}', 'run_id': run_id,
        'request_id': f'{call_id}:{revision + 1}', 'vendor_id': vendor_id, 'revision': revision, 'currency': 'USD',
        'status': 'issued',
        'lines': [{'product_id': 'ply-cdx-12-4x8', 'description': '1/2 in CDX plywood 4x8', 'quantity': 40,
                   'unit': 'sheet', 'unit_price': unit_price, 'line_total': subtotal}],
        'subtotal': subtotal, 'fees': [{'name': 'delivery', 'amount': '45.00'}], 'discounts': [],
        'taxes': {'status': 'excluded', 'agreed': False}, 'delivery': {'date': '2026-09-17', 'days': 5},
        'expires_at': '2026-09-13T23:59:59+00:00', 'total': total,
        'conditions': ['delivery fee waived on orders over $2,000'], 'evidence_refs': [f'mock-call:{call_id}'],
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def silence_wav(seconds=1.0, rate=16000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b'\0\0' * int(rate * seconds))
    return output.getvalue()


class MockSupplier:
    def __init__(self, token, tts, api_key=''):
        self.token = token
        self.tts = tts
        self.api_key = api_key
        self.calls = []

    async def speak(self, text):
        if not self.tts:
            return silence_wav()
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post('https://api.openai.com/v1/audio/speech',
                                         headers={'Authorization': f'Bearer {self.api_key}'},
                                         json={'model': 'gpt-4o-mini-tts', 'voice': 'coral', 'input': text, 'response_format': 'wav'})
            response.raise_for_status()
            return response.content

    async def handle(self, ws):
        path = ws.request.path
        parts = path.strip('/').split('/')
        run_id, vendor_id = (parts[2], parts[4]) if len(parts) >= 6 else ('run', 'vendor')
        auth = json.loads(await ws.recv())
        if auth.get('token') != self.token:
            await ws.close(code=1008, reason='Unauthorized')
            return
        call_id = str(uuid.uuid4())
        record = {'call_id': call_id, 'events': [], 'outcome': 'unconfirmed'}
        self.calls.append(record)
        await ws.send(json.dumps({'type': 'ready', 'call_id': call_id, 'max_exchanges': 8, 'max_seconds': 120,
                                  'disclosure': 'You are speaking with an AI supplier using an AI-generated voice.'}))
        exchanges = 0
        candidates = {}
        async for frame in ws:
            if isinstance(frame, (bytes, bytearray)):
                audio = bytes(frame)
            else:
                message = json.loads(frame)
                kind = message.get('type')
                if kind == 'end':
                    record['outcome'] = 'ended_unconfirmed'
                    await ws.send(json.dumps({'type': 'ended', 'confirmed': False}))
                    return
                if kind == 'confirm_quote':
                    candidate = candidates.get(message.get('readback_digest'))
                    if not candidate or message.get('quote') != candidate:
                        await ws.send(json.dumps({'type': 'error', 'message': 'Repeat the exact candidate quote and readback digest.'}))
                        continue
                    record['outcome'] = 'confirmed_readback'
                    record['confirmed_quote'] = candidate
                    await ws.send(json.dumps({'type': 'confirmed_quote', 'call_id': call_id, 'quote': candidate, 'order_placed': False}))
                    return
                if kind != 'audio':
                    await ws.send(json.dumps({'type': 'error', 'message': 'Send audio, confirm_quote, or end.'}))
                    continue
                audio = base64.b64decode(message.get('wav_base64', ''))
            if exchanges >= 8:
                await ws.send(json.dumps({'type': 'error', 'message': 'Exchange limit reached; confirm the last quote or end.'}))
                continue
            exchanges += 1
            record['events'].append({'buyer_audio_bytes': len(audio)})
            candidates.clear()
            # The mock cannot transcribe the buyer; the "transcript" is an honest placeholder.
            await ws.send(json.dumps({'type': 'transcript', 'text': f'(mock supplier cannot transcribe; received {len(audio)} bytes of buyer audio)'}))
            if exchanges == 1:
                text, offers = GREETING, []
            elif exchanges == 2:
                text, offers = READBACK_1, [quote(run_id, vendor_id, call_id, 1, '38.50', '1540.00', '1585.00')]
            elif exchanges == 3:
                text, offers = READBACK_2, [quote(run_id, vendor_id, call_id, 2, '37.25', '1490.00', '1535.00')]
            else:
                text, offers = READBACK_2, [quote(run_id, vendor_id, call_id, 2, '37.25', '1490.00', '1535.00')]
            for offer in offers:
                candidates[digest(offer)] = offer
            voice = await self.speak(text)
            record['events'].append({'supplier_text': text, 'offers': [o['quote_id'] for o in offers]})
            await ws.send(json.dumps({'type': 'supplier_turn', 'text': text, 'wav_base64': base64.b64encode(voice).decode(),
                                      'candidates': [{'quote': q, 'readback_digest': d} for d, q in candidates.items()]}))


async def serve_mock(token, port, tts=False, api_key=''):
    from websockets.asyncio.server import serve
    supplier = MockSupplier(token, tts, api_key)
    server = await serve(supplier.handle, '127.0.0.1', port, max_size=12_000_000)
    return server, supplier


def main():
    parser = argparse.ArgumentParser(description='Run the scripted local mock supplier voice endpoint.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--token', default=os.environ.get('TAKEOFF_BUYER_TOKEN', 'mock-token'))
    parser.add_argument('--tts', action='store_true', help='voice lines with OpenAI TTS using OPENAI_API_KEY')
    args = parser.parse_args()

    async def run():
        server, _ = await serve_mock(args.token, args.port, args.tts, os.environ.get('OPENAI_API_KEY', ''))
        print(f'mock supplier listening on ws://127.0.0.1:{args.port}/v1/runs/RUN/vendors/VENDOR/call')
        await server.serve_forever()

    asyncio.run(run())


if __name__ == '__main__':
    main()
