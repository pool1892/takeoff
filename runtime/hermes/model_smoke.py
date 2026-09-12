"""Check installed Hermes config-to-wire behavior without making an API call.

Run with scripts/hermes exec /opt/hermes/.venv/bin/python
/workspace/runtime/hermes/model_smoke.py. Credentials are never printed or sent.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

assert Path('/.dockerenv').exists() and os.environ.get('TAKEOFF_SANDBOX') == '1'
sys.path.insert(0, '/opt/hermes')

import httpx
from openai import OpenAI
from hermes_cli.config import load_config, get_compatible_custom_providers
from hermes_cli.oneshot import _resolve_model_and_provider
from hermes_cli.runtime_provider import resolve_runtime_provider
from hermes_constants import resolve_reasoning_config
from agent.agent_init import _merge_custom_provider_extra_body
from agent.transports.codex import ResponsesApiTransport

cfg = load_config()
choice = _resolve_model_and_provider(cfg, None, None)
runtime = resolve_runtime_provider(
    requested=choice.provider, target_model=choice.model,
    explicit_base_url=choice.base_url, explicit_api_key=choice.api_key,
)
agent = SimpleNamespace(
    provider=runtime['provider'], model=choice.model,
    base_url=runtime['base_url'], request_overrides={},
)
_merge_custom_provider_extra_body(agent, get_compatible_custom_providers(cfg))
transport = ResponsesApiTransport()
kwargs = transport.preflight_kwargs(transport.build_kwargs(
    choice.model, [{'role': 'user', 'content': 'Reply TAKEOFF_MODEL_OK.'}],
    reasoning_config=resolve_reasoning_config(cfg, choice.model),
    request_overrides=agent.request_overrides,
    provider=agent.provider, base_url=agent.base_url,
))
captured = {}

def intercept(request):
    body = json.loads(request.content)
    captured.update(model=body.get('model'),
                    reasoning=body.get('reasoning', {}).get('effort'),
                    service_tier=body.get('service_tier'))
    return httpx.Response(200, json={
        'id': 'mock', 'object': 'response', 'created_at': 0,
        'status': 'completed', 'model': choice.model, 'output': [],
    })

# A synthetic key and MockTransport guarantee this check cannot send credentials.
with OpenAI(api_key='synthetic-offline-check', base_url=agent.base_url,
            http_client=httpx.Client(transport=httpx.MockTransport(intercept))) as client:
    client.responses.create(**kwargs)

assert captured == {'model': 'gpt-5.6-luna', 'reasoning': 'max', 'service_tier': 'priority'}, captured
print(json.dumps({'model_config_to_wire': 'passed', **captured, 'network': 'mocked'}))
