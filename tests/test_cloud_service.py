import importlib

from fastapi.testclient import TestClient

from takeoff_suppliers.config import Settings


def test_cloud_restart_auth_and_bound_request(tmp_path, monkeypatch):
    monkeypatch.setenv('TAKEOFF_CLOUD_HOME', str(tmp_path))
    calls = []

    class Runtime:
        def respond(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {'status': 'completed', 'offers': []}

    monkeypatch.setattr(Settings, 'runtime', lambda *args: Runtime())
    module = importlib.import_module('takeoff_suppliers.cloud_service')
    client = TestClient(module.app_from_env())
    settings = Settings(tmp_path)
    headers = {'Authorization': 'Bearer ' + settings.secret('TAKEOFF_OPERATOR_TOKEN')}
    path = '/operator/vendors/general/agent'
    body = {'request_id': 'one', 'message': 'Please quote studs'}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert calls[0][1]['channel'] == 'operator'
    assert calls[0][1]['request_id'] == 'one'
    run_id = calls[0][0][0]
    restarted = TestClient(module.app_from_env())
    assert restarted.post(path, headers=headers, json={**body, 'message': 'changed'}).status_code == 409
    assert restarted.post(path, headers=headers, json=body).status_code == 200
    assert calls[-1][0][0] == run_id
    assert restarted.post(path, headers=headers, json={**body, 'deliver': True}).status_code == 422
