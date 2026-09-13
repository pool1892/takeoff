"""Persistent cloud host for the existing Codex supplier harness.

Starts a fresh isolated ledger. Mail workers are an explicit, separate cutover;
this service never imports a laptop ledger or sends mail from manual turns.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, initialize, private_json
from .runtime import TransportState, RecoveryRequired
from .web import create_app


class AgentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=50000)


def app_from_env():
    home = Path(os.environ.get('TAKEOFF_CLOUD_HOME', '/data/suppliers'))
    initialize(home)
    settings = Settings(home)
    market = settings.market()
    state = TransportState(settings.data['transport_path'])
    active_path = home / 'active_run.json'
    if active_path.exists():
        active = json.loads(active_path.read_text())
        market.get_run(active['id'])
    else:
        active = market.create_run(settings.data['buyer_id'], policy='collaboration')
        private_json(active_path, active)
    operator = settings.secret('TAKEOFF_OPERATOR_TOKEN')
    app = create_app(market, operator, settings.secret('TAKEOFF_BUYER_TOKEN'),
                     settings.data['buyer_id'], public_run_id=active['id'])
    runtime = settings.runtime(market, state, {})
    lock = threading.Lock()

    def authorize(request):
        supplied = request.headers.get('authorization', '').encode()
        if not secrets.compare_digest(supplied, ('Bearer ' + operator).encode()):
            raise HTTPException(401, 'Valid operator bearer token required')

    @app.get('/operator/status')
    def status(request: Request):
        authorize(request)
        from .codex_runtime import account_status
        return {'run_id': active['id'], 'runtime': 'codex', 'outbound_enabled': False,
                'account': account_status(settings.data.get('codex_binary', 'codex'))}

    @app.post('/operator/vendors/{vendor_id}/agent')
    def agent(vendor_id: str, body: AgentInput, request: Request):
        authorize(request)
        market.catalog(active['id'], vendor_id)
        digest = hashlib.sha256(body.message.encode()).hexdigest()
        key = f'cloud-request:{active["id"]}:{vendor_id}:{body.request_id}'
        with lock:
            previous = state.get(key)
            if previous and previous['digest'] != digest:
                raise HTTPException(409, 'Request ID already belongs to a different message')
            state.put(key, {'digest': digest})
            try:
                return runtime.respond(active['id'], vendor_id, settings.data['buyer_id'],
                                       body.message, channel='operator', request_id=body.request_id,
                                       timeout_seconds=240)
            except (RecoveryRequired, ValueError, TimeoutError) as exc:
                # Never return provider error payloads or authentication details.
                raise HTTPException(503, f'Supplier turn unavailable ({type(exc).__name__}); saved state retained') from exc

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app_from_env(), host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
