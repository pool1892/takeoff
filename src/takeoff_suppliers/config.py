"""Ignored local settings and credentials; no secret values in diagnostics."""
import json
import os
from pathlib import Path
import secrets

from .channels import AmbiguousClient, VendorConnection

DEFAULT_HOME = Path('.local/suppliers')


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def defaults(home=DEFAULT_HOME):
    home = Path(home)
    vendors = {}
    for vendor in ('general', 'overstock', 'local', 'trader'):
        vendors[vendor] = {
            'user_id': None,
            'token_env': f'AMBIGUOUS_{vendor.upper()}_API_KEY',
            'email': None, 'chat_threads': [], 'buyers': {}, 'chat_buyers': {},
        }
    return {'database_path': str(home / 'market.sqlite'), 'transport_path': str(home / 'transport.sqlite'),
            'scenario_path': str(Path(__file__).parent / 'fixtures' / 'house.json'),
            'buyer_id': 'demo-buyer', 'buyer_workspace_id': None,
            'supplier_workspace_id': None, 'supplier_workspace_slug': None,
            'model': 'gpt-6-astra', 'runtime_backend': 'codex', 'exa_mcp_url': None, 'vendors': vendors}


def initialize(home=DEFAULT_HOME):
    """Create only missing settings; retain every preexisting credential."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / 'config.json'
    created = not path.exists()
    if created:
        private_json(path, defaults(home))
    else:
        os.chmod(path, 0o600)
    secret_path = home / 'secrets.json'
    values = json.loads(secret_path.read_text()) if secret_path.exists() else {}
    for name in ('TAKEOFF_OPERATOR_TOKEN', 'TAKEOFF_BUYER_TOKEN'):
        values.setdefault(name, secrets.token_urlsafe(32))
    if values['TAKEOFF_OPERATOR_TOKEN'] == values['TAKEOFF_BUYER_TOKEN']:
        raise ValueError('Existing buyer and operator tokens must be distinct; settings were not overwritten')
    private_json(secret_path, values)
    return {'config_created': created, 'config_path': str(path), 'secrets_path': str(secret_path),
            'buyer_workspace': 'pending', 'credentials': 'preserved; values omitted'}


class Settings:
    def __init__(self, home=DEFAULT_HOME):
        self.home = Path(home)
        path = self.home / 'config.json'
        if not path.exists():
            raise ValueError('Local configuration is missing; run takeoff-suppliers init')
        self.data = json.loads(path.read_text())

    def secret(self, name, required=True):
        value = os.environ.get(name)
        if not value:
            path = self.home / 'secrets.json'
            values = json.loads(path.read_text()) if path.exists() else {}
            value = values.get(name)
        if not value and required:
            raise ValueError(f'{name} is missing; configure it in the environment or ignored secrets.json')
        return value

    def market(self):
        from .core import Market
        return Market(self.data['database_path'], self.data.get('scenario_path'))

    def connection(self, vendor_id):
        try:
            vendor = self.data['vendors'][vendor_id]
        except KeyError as exc:
            raise ValueError('Unknown supplier configuration') from exc
        if not vendor.get('user_id'):
            raise ValueError(f'{vendor_id} supplier identity is not configured')
        return AmbiguousClient(VendorConnection(
            vendor_id=vendor_id, token=self.secret(vendor['token_env']),
            workspace_id=self.data['supplier_workspace_id'],
            buyer_workspace_id=self.data.get('buyer_workspace_id') or '',
            user_id=vendor['user_id'], base_url=self.data.get('ambiguous_base_url', 'https://app.ambiguous.ai'),
            chat_threads=tuple(tuple(pair) for pair in vendor.get('chat_threads', []))))

    def runtime(self, market, state, connections=None):
        backend = self.data.get('runtime_backend', 'codex')
        if backend == 'codex':
            from .codex_runtime import CodexRuntime
            return CodexRuntime(market, state, model=self.data.get('model', 'gpt-6-astra'),
                                connections=connections, binary=self.data.get('codex_binary', 'codex'))
        if backend != 'agents_api':
            raise ValueError('runtime_backend must be codex or agents_api')
        from .runtime import AgentRuntime
        return AgentRuntime(market, state, self.secret('OPENAI_API_KEY'),
                            model=self.data.get('model', 'gpt-6-astra'), connections=connections,
                            exa_mcp_url=self.data.get('exa_mcp_url'))
