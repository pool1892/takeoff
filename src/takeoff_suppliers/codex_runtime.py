"""Supplier runtime using the supported local Codex app-server and saved login.

No authentication files or tokens are read by this application. Codex owns login
and model transport. Dynamic tools execute only in the supplier service.
"""
from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time

from .runtime import AgentRuntime, PERSONALITIES, RecoveryRequired, TOOLS


DISABLED_FEATURES = ('apps', 'plugins', 'remote_plugin', 'hooks', 'memories', 'shell_tool',
                     'unified_exec', 'browser_use', 'computer_use', 'image_generation',
                     'view_image', 'multi_agent', 'skill_search')


def app_server_command(binary='codex'):
    # Ask the installed CLI for server names, never read its credential/config files.
    listing = subprocess.run([binary, 'mcp', 'list', '--json'], capture_output=True,
                             text=True, timeout=20, check=True)
    servers = json.loads(listing.stdout)
    command = [binary]
    for feature in DISABLED_FEATURES:
        command.extend(['-c', f'features.{feature}=false'])
    command.extend(['-c', 'features.code_mode_host=true',
                    '-c', 'features.skip_host_skill_discovery=true',
                    '-c', 'project_doc_max_bytes=0', '-c', 'web_search="disabled"'])
    for server in servers:
        name = server['name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Cannot safely isolate an MCP server with this configured name')
        command.extend(['-c', f'mcp_servers.{name}.enabled=false'])
    command.extend(['app-server', '--stdio'])
    return command


class AppServer:
    def __init__(self, cwd, *, binary='codex', timeout=120, cancel_event=None):
        self.deadline = time.monotonic() + timeout
        self.cancel_event = cancel_event
        self.queue = queue.Queue()
        self.pending = deque()
        self.next_id = 0
        environment = dict(os.environ)
        # Use saved Codex account auth, not an accidentally inherited API credential.
        environment.pop('OPENAI_API_KEY', None)
        self.process = subprocess.Popen(app_server_command(binary), cwd=cwd, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request('initialize', {'clientInfo': {'name': 'takeoff_suppliers', 'version': '0.1.0'},
                                       'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized', 'params': {}})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.queue.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.queue.put(None)

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def receive(self):
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise TimeoutError('Codex caller disconnected')
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex supplier turn deadline exceeded')
            try:
                item = self.queue.get(timeout=min(remaining, .25))
            except queue.Empty:
                continue
            if item is None:
                raise RecoveryRequired('Codex app-server exited; saved supplier state was retained')
            return item

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            event = self.receive()
            if event.get('id') == request_id and 'method' not in event:
                if 'error' in event:
                    raise RecoveryRequired(f'Codex {method} failed: {event["error"].get("message", "RPC error")}')
                return event['result']
            self.pending.append(event)

    def next_event(self):
        return self.pending.popleft() if self.pending else self.receive()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def account_status(binary='codex'):
    with tempfile.TemporaryDirectory(prefix='takeoff-account-') as cwd:
        rpc = AppServer(cwd, binary=binary, timeout=30)
        try:
            result = rpc.request('account/read', {'refreshToken': False})
            account = result.get('account') or {}
            return {'type': account.get('type'), 'plan_type': account.get('planType'),
                    'authenticated': account.get('type') == 'chatgpt'}
        finally:
            rpc.close()


class CodexRuntime(AgentRuntime):
    def __init__(self, market, state, *, model='gpt-6-astra', connections=None,
                 binary='codex', rpc_factory=AppServer, work_root=None):
        super().__init__(market, state, 'unused-codex-account', model=model, connections=connections)
        self.binary, self.rpc_factory = binary, rpc_factory
        self.work_root = Path(work_root) if work_root else None

    def _configuration(self, cwd, vendor_id, policy):
        instructions = ('You are the supplier negotiation agent for a simulated construction-material market. '
            'Use only the supplied dynamic tools. No filesystem, shell, personal context, outside messaging, '
            'or unrelated work. Call catalog to inspect this supplier and inquire for commercial questions. '
            'Call issue_offer to validate and issue negotiated terms. Never accept for the buyer, invent '
            'approval or quote a price without the commercial tool. The host publishes canonical records; '
            'your final prose is internal only. ' + PERSONALITIES.get(vendor_id, 'Negotiate useful packages.'))
        if policy == 'collaboration':
            instructions += (' Protect private context, distinguish proposals from commitments, exchange useful '
                             'information, clarify substitutions and stop after an agreement.')
        dynamic = [{'type': 'function', 'name': t['name'], 'description': t['description'],
                    'inputSchema': t['parameters']} for t in TOOLS]
        return {'model': self.model, 'cwd': str(cwd), 'approvalPolicy': 'never', 'sandbox': 'read-only',
                'baseInstructions': instructions, 'developerInstructions': instructions,
                'environments': [], 'selectedCapabilityRoots': [], 'dynamicTools': dynamic,
                'serviceName': 'takeoff_suppliers', 'allowProviderModelFallback': False}

    def _render(self, run_id, vendor_id, buyer_id, sid, work):
        offers, inquiries = [], []
        for outcome in work['records']:
            if not outcome.get('success'):
                continue
            if outcome['name'] == 'issue_offer':
                record = outcome['record']
                current = self.market.get_offer(run_id, record.get('quote_id') or record['id'], buyer_id)
                if current['vendor_id'] == vendor_id and current['status'] == 'issued':
                    offers.append(current)
            elif outcome['name'] == 'inquire':
                inquiries.append(outcome['record'])
        public = offers or inquiries
        return {'status': 'completed', 'runtime': 'codex', 'session_id': sid, 'offers': offers,
                'message': ('Validated supplier records:\n\n```json\n' + json.dumps(public, indent=2) + '\n```')
                if public else 'No offer was issued. Please clarify products, quantities and delivery needs.'}

    def _respond(self, run_id, vendor_id, buyer_id, message, channel='email', request_id=None,
                 timeout_seconds=None, cancel_event=None):
        run = self.market.get_run(run_id)
        if run.get('buyer_id') != buyer_id:
            raise ValueError('Buyer does not own this run')
        if self.market.is_paused(run_id, vendor_id):
            return {'status': 'paused', 'message': 'Supplier operator has paused responses.', 'offers': []}
        if not request_id:
            raise ValueError('A stable request_id is required for Codex turns')
        key = f'codex-input:{run_id}:{vendor_id}:{request_id}'
        work = self.state.get(key)
        if work and work.get('result'):
            return work['result']
        session_key = f'codex-session:{run_id}:{vendor_id}'
        sid = self.state.get(session_key)
        timeout = timeout_seconds if timeout_seconds is not None else 180
        if self.work_root:
            self.work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='takeoff-vendor-', dir=self.work_root) as cwd:
            rpc = self.rpc_factory(cwd, binary=self.binary, timeout=timeout, cancel_event=cancel_event)
            try:
                account = rpc.request('account/read', {'refreshToken': False}).get('account') or {}
                if account.get('type') != 'chatgpt':
                    raise ValueError('Codex ChatGPT login required; run codex login using the desired account')
                if work:
                    # A new app-server cannot safely assume a interrupted turn did not act.
                    # Recover completed work, otherwise require reconciliation before a new turn.
                    if not sid:
                        raise RecoveryRequired('Codex thread creation outcome uncertain')
                    saved = rpc.request('thread/read', {'threadId': sid, 'includeTurns': True})['thread']
                    turns = saved.get('turns', [])
                    latest = next((t for t in turns if t['id'] == work.get('turn_id')), None)
                    if not latest or latest.get('status') != 'completed':
                        raise RecoveryRequired('Previous Codex turn is incomplete; inspect its saved records before retry')
                    result = self._render(run_id, vendor_id, buyer_id, sid, work)
                    work['result'] = result
                    self.state.put(key, work)
                    return result
                configuration = self._configuration(cwd, vendor_id, run.get('policy'))
                if sid:
                    resumed = {k: v for k, v in configuration.items() if k not in
                               ('dynamicTools', 'environments', 'selectedCapabilityRoots', 'serviceName',
                                'allowProviderModelFallback')}
                    rpc.request('thread/resume', {'threadId': sid, **resumed})
                else:
                    self.state.put(key, {'records': [], 'uncertain': True})
                    started = rpc.request('thread/start', configuration)
                    sid = started['thread']['id']
                    self.state.put(session_key, sid)
                # Fail closed if personal MCP tools remain active despite launch overrides.
                servers = rpc.request('mcpServerStatus/list', {'detail': 'toolsAndAuthOnly'})
                if any(server.get('tools') for server in servers.get('data', [])):
                    raise RecoveryRequired('Unexpected personal MCP tools in isolated supplier runtime')
                work = {'records': [], 'events': [], 'uncertain': True}
                self.state.put(key, work)
                started = rpc.request('turn/start', {'threadId': sid, 'environments': [],
                    'input': [{'type': 'text', 'text': json.dumps({'sender': buyer_id, 'channel': channel,
                        'request_id': request_id, 'message': message})}], 'effort': 'medium'})
                work.update(turn_id=started['turn']['id'], uncertain=False)
                self.state.put(key, work)
                while True:
                    event = rpc.next_event()
                    params = event.get('params', {})
                    if params.get('threadId') not in (None, sid):
                        raise RecoveryRequired('Unexpected supplier thread event')
                    if 'method' in event and 'id' in event:
                        if event['method'] != 'item/tool/call':
                            rpc.send({'id': event['id'], 'error': {'code': -32601,
                                      'message': 'Only supplier dynamic tools are permitted'}})
                            continue
                        if cancel_event is not None and cancel_event.is_set():
                            raise TimeoutError('Codex caller disconnected before tool execution')
                        if time.monotonic() >= getattr(rpc, 'deadline', float('inf')):
                            raise TimeoutError('Codex deadline exceeded before tool execution')
                        if params.get('turnId') != work['turn_id']:
                            raise RecoveryRequired('Unexpected supplier turn tool request')
                        action = {'turn_id': params['turnId'], 'call_id': params['callId'],
                                  'name': params['tool'], 'arguments': params['arguments']}
                        outcome = self._action('codex-' + sid, action, run_id, vendor_id,
                                               buyer_id, channel, request_id)
                        marker = params['callId']
                        if not any(r.get('marker') == marker for r in work['records']):
                            work['records'].append({'marker': marker, **outcome})
                        self.state.put(key, work)
                        rpc.send({'id': event['id'], 'result': {'success': outcome['success'],
                            'contentItems': [{'type': 'inputText', 'text': outcome.get('output') or outcome['error']}]}})
                    elif event.get('method') in ('item/completed', 'turn/completed', 'error'):
                        work['events'].append(event)
                        self.state.put(key, work)
                        if event['method'] == 'turn/completed':
                            turn = params['turn']
                            if turn.get('id') != work['turn_id']:
                                continue
                            if turn.get('status') != 'completed':
                                raise RecoveryRequired('Codex turn did not complete successfully')
                            result = self._render(run_id, vendor_id, buyer_id, sid, work)
                            work['result'] = result
                            self.state.put(key, work)
                            self.state.put(f'trace:codex-{sid}:{work["turn_id"]}', work)
                            return result
            finally:
                rpc.close()
