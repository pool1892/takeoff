import json

import pytest

from takeoff_suppliers.codex_runtime import CodexRuntime
from takeoff_suppliers.config import Settings, initialize
from takeoff_suppliers.core import Market
from takeoff_suppliers.runtime import RecoveryRequired, TransportState


class FakeRPC:
    account_type = 'chatgpt'
    instances = []
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.events = []
        self.responses = []
        self.__class__.instances.append(self)
    def request(self, method, params):
        self.calls.append((method, params))
        if method == 'account/read': return {'account': {'type': self.account_type}}
        if method == 'thread/start':
            assert params['environments'] == []
            assert params['selectedCapabilityRoots'] == []
            assert params['approvalPolicy'] == 'never'
            assert params['sandbox'] == 'read-only'
            assert {t['name'] for t in params['dynamicTools']} == {'catalog', 'inquire', 'issue_offer'}
            return {'thread': {'id': 'thread'}}
        if method == 'mcpServerStatus/list': return {'data': []}
        if method == 'turn/start':
            self.events = [
                {'id': 99, 'method': 'item/tool/call', 'params': {'threadId': 'thread', 'turnId': 'turn',
                    'callId': 'call', 'tool': 'inquire', 'arguments': {'message': 'What can you supply?'}}},
                {'method': 'turn/completed', 'params': {'threadId': 'thread',
                                                       'turn': {'id': 'turn', 'status': 'completed'}}}]
            return {'turn': {'id': 'turn'}}
        raise AssertionError(method)
    def next_event(self): return self.events.pop(0)
    def send(self, response): self.responses.append(response)
    def close(self): pass


def test_saved_chatgpt_account_dynamic_tool_and_canonical_result(tmp_path):
    market = Market(tmp_path / 'market.db')
    run_id = market.create_run('buyer')['id']
    state = TransportState(tmp_path / 'transport.db')
    runtime = CodexRuntime(market, state, rpc_factory=FakeRPC)
    result = runtime.respond(run_id, 'general', 'buyer', 'What can you supply?', request_id='email:source')
    assert result['runtime'] == 'codex'
    assert 'Validated supplier records' in result['message']
    rpc = FakeRPC.instances[-1]
    assert rpc.responses[0]['result']['success']
    content = rpc.responses[0]['result']['contentItems'][0]
    assert content['type'] == 'inputText'
    assert 'products' in json.loads(content['text'])
    assert runtime.respond(run_id, 'general', 'buyer', 'repeat', request_id='email:source') == result


def test_codex_is_default_and_does_not_require_api_key(tmp_path, monkeypatch):
    initialize(tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    settings = Settings(tmp_path)
    runtime = settings.runtime(settings.market(), TransportState(tmp_path / 'transport.db'))
    assert isinstance(runtime, CodexRuntime)


def test_rejects_api_key_account_in_account_backend(tmp_path):
    class KeyRPC(FakeRPC): account_type = 'apiKey'
    market = Market(tmp_path / 'market.db')
    run_id = market.create_run('buyer')['id']
    runtime = CodexRuntime(market, TransportState(tmp_path / 'transport.db'), rpc_factory=KeyRPC)
    with pytest.raises(ValueError, match='ChatGPT login'):
        runtime.respond(run_id, 'general', 'buyer', 'request', request_id='source')


def test_incomplete_saved_turn_is_not_blindly_restarted(tmp_path):
    class IncompleteRPC(FakeRPC):
        def request(self, method, params):
            if method == 'thread/read':
                return {'thread': {'turns': [{'id': 'prior', 'status': 'interrupted'}]}}
            return super().request(method, params)
    market = Market(tmp_path / 'market.db')
    run_id = market.create_run('buyer')['id']
    state = TransportState(tmp_path / 'transport.db')
    state.put(f'codex-session:{run_id}:general', 'thread')
    state.put(f'codex-input:{run_id}:general:source', {'turn_id': 'prior', 'records': []})
    runtime = CodexRuntime(market, state, rpc_factory=IncompleteRPC)
    with pytest.raises(RecoveryRequired, match='incomplete'):
        runtime.respond(run_id, 'general', 'buyer', 'request', request_id='source')
    assert not any(method == 'turn/start' for method, _ in FakeRPC.instances[-1].calls)


def test_launch_uses_tool_host_but_disables_personal_tools(monkeypatch):
    from types import SimpleNamespace
    from takeoff_suppliers.codex_runtime import app_server_command
    monkeypatch.setattr('takeoff_suppliers.codex_runtime.subprocess.run',
                        lambda *a, **kw: SimpleNamespace(stdout='[{"name":"personal_mcp"}]'))
    command = app_server_command()
    assert 'features.code_mode_host=true' in command
    assert 'features.shell_tool=false' in command
    assert 'features.plugins=false' in command
    assert 'mcp_servers.personal_mcp.enabled=false' in command
