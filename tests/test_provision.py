import json

import httpx
import pytest

from takeoff_suppliers.config import Settings, initialize, private_json
from takeoff_suppliers.provision import provision


def setup_settings(tmp_path):
    initialize(tmp_path)
    settings = Settings(tmp_path)
    settings.data['supplier_workspace_id'] = 'supplier-space'
    private_json(tmp_path / 'config.json', settings.data)
    private_json(tmp_path / 'secrets.json', {'AMBIGUOUS_SUPPLIER_API_KEY': 'setup-secret'})
    return settings


def test_provision_saves_keys_privately_and_restart_does_not_duplicate(tmp_path):
    settings = setup_settings(tmp_path)
    created = []

    def handle(request):
        assert request.headers['Authorization'] == 'Bearer setup-secret'
        if request.method == 'GET':
            return httpx.Response(200, json={'id': 'owner', 'role': 'owner',
                                            'workspace_id': 'supplier-space'})
        body = json.loads(request.content)
        created.append(body['username'])
        return httpx.Response(200, json={'api_key': 'secret-' + body['username'],
            'user': {'id': body['username'], 'workspace_email': body['username'] + '@example.test'}})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    result = provision(settings, client)
    assert len(created) == 4
    assert 'secret-' not in json.dumps(result)
    assert all(item['created'] for item in result['vendors'])
    result = provision(Settings(tmp_path), client)
    assert len(created) == 4
    assert not any(item['created'] for item in result['vendors'])
    assert (tmp_path / 'secrets.json').stat().st_mode & 0o777 == 0o600


def test_uncertain_creation_survives_restart_without_repeating_post(tmp_path):
    settings = setup_settings(tmp_path)
    calls = []

    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'id': 'owner', 'role': 'owner',
                                            'workspace_id': 'supplier-space'})
        calls.append(request.url.path)
        raise httpx.ReadTimeout('response lost', request=request)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.ReadTimeout):
        provision(settings, client)
    with pytest.raises(ValueError, match='uncertain'):
        provision(Settings(tmp_path), client)
    assert len(calls) == 1


def test_wrong_workspace_cannot_provision(tmp_path):
    settings = setup_settings(tmp_path)
    def handle(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'id': 'owner', 'role': 'owner', 'workspace_id': 'other'})
    with pytest.raises(ValueError, match='verified existing supplier workspace'):
        provision(settings, httpx.Client(transport=httpx.MockTransport(handle)))
