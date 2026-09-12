"""Supplier operator commands. Live external actions are explicit commands."""
import argparse
import json
import sys
import uuid

import httpx

from .config import DEFAULT_HOME, Settings, initialize, private_json
from .runtime import RecoveryRequired, TransportState


def parser():
    root = argparse.ArgumentParser(prog='takeoff-suppliers')
    root.add_argument('--home', default=str(DEFAULT_HOME), help='Ignored local config/secrets directory')
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Create missing local settings and tokens; preserve existing files')
    run = commands.add_parser('run', help='Start a fresh simulated trial')
    run.add_argument('--buyer-type', choices=['agent', 'human'], default='agent')
    run.add_argument('--policy', choices=['baseline', 'collaboration'], default='baseline')
    reset = commands.add_parser('reset', help='Clone initial scenario into a new run ID, retaining history')
    reset.add_argument('run_id')
    serve = commands.add_parser('serve', help='Serve supplier website and HTTP API')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    serve.add_argument('--voice', action='store_true', help='Enable live OpenAI phone stretch')
    worker = commands.add_parser('worker', help='Poll a configured supplier mailbox and reply')
    worker.add_argument('run_id')
    worker.add_argument('vendor_id', choices=['general', 'overstock', 'local', 'trader'])
    worker.add_argument('--once', action='store_true')
    agent = commands.add_parser('agent', help='Run one manual supplier-agent turn (no outgoing mail)')
    agent.add_argument('run_id')
    agent.add_argument('vendor_id', choices=['general', 'overstock', 'local', 'trader'])
    agent.add_argument('message')
    agent.add_argument('--request-id', default=None, help='Reuse after a timeout to resume safely')
    export = commands.add_parser('export', help='Export public records or private operator evidence')
    export.add_argument('run_id')
    export.add_argument('--private', action='store_true')
    export.add_argument('--output', help='Write a mode-600 JSON file instead of stdout')
    sync = commands.add_parser('sync-records', help='Mirror canonical supplier records into Ambiguous')
    sync.add_argument('run_id')
    score = commands.add_parser('score', help='Assess validity before comparing package cost')
    score.add_argument('run_id')
    score.add_argument('quote_ids', nargs='+')
    score.add_argument('--max-delivery-days', type=int)
    doctor = commands.add_parser('doctor', help='Read-only supplier identity and configuration check')
    doctor.add_argument('--vendor', choices=['general', 'overstock', 'local', 'trader'])
    pause = commands.add_parser('pause', help='Pause a vendor for operator takeover')
    pause.add_argument('run_id')
    pause.add_argument('vendor_id')
    pause.add_argument('--resume', action='store_true')
    return root


def doctor(settings, vendor_id=None):
    if vendor_id:
        channel = settings.connection(vendor_id)
        identity = channel.verify_identity(require_buyer=False)
    else:
        # Setup-owner credential is diagnostic only, never a vendor runtime identity.
        key = settings.secret('AMBIGUOUS_SUPPLIER_API_KEY')
        url = settings.data.get('ambiguous_base_url', 'https://app.ambiguous.ai').rstrip('/')
        response = httpx.get(url + '/api/users/me', headers={'Authorization': f'Bearer {key}'}, timeout=20)
        response.raise_for_status()
        identity = response.json()
        expected = settings.data.get('supplier_workspace_id')
        if expected and identity.get('workspace_id') != expected:
            raise ValueError('Setup credential belongs to a different supplier workspace')
        if not identity.get('workspace_id') or identity.get('needs_workspace_setup'):
            raise ValueError('Supplier workspace setup is incomplete')
    buyer = settings.data.get('buyer_workspace_id')
    if buyer and buyer == identity['workspace_id']:
        raise ValueError('Buyer and supplier workspace IDs must differ')
    return {'supplier': {k: identity.get(k) for k in ('id', 'display_name', 'workspace_id', 'primary_email')},
            'buyer_workspace': buyer or 'pending — worker unavailable until configured',
            'runtime_backend': settings.data.get('runtime_backend', 'codex'),
            'openai_key_configured': bool(settings.secret('OPENAI_API_KEY', required=False)),
            'checks_performed': ['supplier_identity', 'local_configuration'],
            'live_agent_verified': False, 'cross_computer_verified': False}


def execute(args):
    if args.command == 'init':
        return initialize(args.home)
    settings = Settings(args.home)
    if args.command == 'doctor':
        return doctor(settings, args.vendor)
    market = settings.market()
    buyer_id = settings.data['buyer_id']
    if args.command == 'run':
        return market.create_run(buyer_id, args.buyer_type, args.policy)
    if args.command == 'reset':
        return market.reset_run(args.run_id)
    if args.command == 'pause':
        return market.set_paused(args.run_id, args.vendor_id, not args.resume)
    if args.command == 'score':
        return market.score_plan(args.run_id, buyer_id, args.quote_ids, args.max_delivery_days)
    if args.command == 'export':
        result = market.export_run(args.run_id, private=args.private)
        if args.private:
            result['transport'] = TransportState(settings.data['transport_path']).export_run(args.run_id)
        if args.output:
            private_json(args.output, result)
            return {'written': args.output, 'private': args.private}
        return result
    state = TransportState(settings.data['transport_path'])
    if args.command == 'sync-records':
        from .sync import SupplierRecordsSync
        connections = {v: settings.connection(v) for v in settings.data['vendors']}
        return SupplierRecordsSync(market, state, connections).sync(args.run_id)
    if args.command == 'serve':
        import uvicorn
        from .web import create_app
        app = create_app(market, settings.secret('TAKEOFF_OPERATOR_TOKEN'),
                         settings.secret('TAKEOFF_BUYER_TOKEN'), buyer_id)
        if args.voice:
            from .voice import attach_voice
            openai_key = settings.secret('OPENAI_API_KEY')
            connections = {}
            for vendor_id, vendor in settings.data['vendors'].items():
                if vendor.get('user_id'):
                    channel = settings.connection(vendor_id)
                    channel.verify_identity(require_buyer=False)
                    connections[vendor_id] = channel
            runtime = settings.runtime(market, state, connections)
            attach_voice(app, market, runtime, settings.secret('TAKEOFF_BUYER_TOKEN'), buyer_id,
                         openai_key, evidence_path=settings.home / 'voice.sqlite')
        uvicorn.run(app, host=args.host, port=args.port)
        return None
    if args.command == 'agent':
        channel = settings.connection(args.vendor_id)
        # Buyer setup is deferred; a manual operator turn sends no external messages.
        runtime = settings.runtime(market, state, {args.vendor_id: channel})
        channel.verify_identity(require_buyer=False)
        request_id = args.request_id or 'manual-' + uuid.uuid4().hex
        print(json.dumps({'request_id': request_id, 'resume': 'Reuse --request-id after a timeout'}), file=sys.stderr)
        return runtime.respond(args.run_id, args.vendor_id, buyer_id, args.message,
                               channel='operator', request_id=request_id)
    if args.command == 'worker':
        from .worker import SupplierWorker
        vendor = settings.data['vendors'][args.vendor_id]
        if not settings.data.get('buyer_workspace_id'):
            raise ValueError('Buyer workspace is pending; configure it before starting the worker')
        if not vendor.get('buyers') and not vendor.get('chat_buyers'):
            raise ValueError('Configure authorized buyer email or chat sender mappings before starting the worker')
        channel = settings.connection(args.vendor_id)
        runtime = settings.runtime(market, state, {args.vendor_id: channel})
        channel.verify_identity()
        worker = SupplierWorker(market, runtime, state, args.run_id, args.vendor_id, channel,
                                buyers=vendor.get('buyers', {}), chat_buyers=vendor.get('chat_buyers', {}))
        if args.once:
            return {'sent': worker.tick()}
        worker.run()
        return None
    raise ValueError('Unsupported command')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        if result is not None:
            print(json.dumps(result, indent=2))
        if args.command == 'sync-records' and result and not result.get('ok'):
            return 1
        return 0
    except (ValueError, OSError, RecoveryRequired, httpx.HTTPError) as exc:
        # HTTP payloads/headers may include credentials: report only status/type.
        if isinstance(exc, httpx.HTTPStatusError):
            error = f'Remote API returned HTTP {exc.response.status_code}; inspect configuration and access'
        elif isinstance(exc, httpx.HTTPError):
            error = f'Remote API transport failed ({type(exc).__name__}); saved state is retained'
        else:
            error = str(exc)
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
