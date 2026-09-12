#!/usr/bin/env python3
"""Local smoke: GPT-Live buyer bridge against the in-process scripted mock supplier.

Labels: the supplier business is a scripted mock; the buyer voice, the live
session, and (with --tts) the supplier audio are real OpenAI calls through the
container proxy. This is not a cross-computer call.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from integrations.voice.live import place_live_call
from integrations.voice.mock_supplier import serve_mock


async def run(args):
    request = json.loads(Path(args.request).read_text())
    token = 'mock-' + os.urandom(4).hex()
    server, supplier = await serve_mock(token, args.port, args.tts, os.environ.get('OPENAI_API_KEY', ''))
    request['supplier_url'] = f"ws://127.0.0.1:{args.port}/v1/runs/{request['run_id']}/vendors/{request['vendor_id']}/call"
    env = dict(os.environ, TAKEOFF_BUYER_TOKEN=token)
    try:
        result = await place_live_call(request, env=env)
    finally:
        server.close()
        await server.wait_closed()
    result['mock_supplier_record'] = supplier.calls[0] if supplier.calls else None
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request', nargs='?', default=str(Path(__file__).with_name('example-request.json')))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--tts', action='store_true')
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'confirmed' else 1


if __name__ == '__main__':
    sys.exit(main())
