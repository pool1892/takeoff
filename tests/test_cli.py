import json
import os
from pathlib import Path
from types import SimpleNamespace

from takeoff_suppliers.cli import main
from takeoff_suppliers.config import Settings, initialize, private_json


def test_init_preserves_secrets_and_existing_configuration(tmp_path, capsys):
    home = tmp_path / 'local'
    home.mkdir()
    private_json(home / 'secrets.json', {'AMBIGUOUS_SUPPLIER_API_KEY': 'do-not-print'})
    assert main(['--home', str(home), 'init']) == 0
    settings = Settings(home)
    assert settings.secret('AMBIGUOUS_SUPPLIER_API_KEY') == 'do-not-print'
    assert settings.secret('TAKEOFF_OPERATOR_TOKEN') != settings.secret('TAKEOFF_BUYER_TOKEN')
    assert settings.data['supplier_workspace_id'] is None
    settings.data['model'] = 'operator-choice'
    private_json(home / 'config.json', settings.data)
    assert main(['--home', str(home), 'init']) == 0
    assert Settings(home).data['model'] == 'operator-choice'
    assert 'do-not-print' not in capsys.readouterr().out
    for filename in ('config.json', 'secrets.json'):
        assert (home / filename).stat().st_mode & 0o777 == 0o600


def test_run_reset_and_export_keep_private_transport_separate(tmp_path, capsys):
    home = tmp_path / 'local'
    initialize(home)
    args = ['--home', str(home)]
    assert main(args + ['run']) == 0
    run = json.loads(capsys.readouterr().out)
    assert main(args + ['reset', run['id']]) == 0
    reset = json.loads(capsys.readouterr().out)
    assert reset['id'] != run['id']
    assert main(args + ['export', run['id']]) == 0
    assert 'transport' not in json.loads(capsys.readouterr().out)
    assert main(args + ['export', run['id'], '--private']) == 0
    assert 'transport' in json.loads(capsys.readouterr().out)


def test_worker_reports_buyer_pending_before_any_network(tmp_path, capsys):
    initialize(tmp_path)
    assert main(['--home', str(tmp_path), 'worker', 'run', 'general', '--once']) == 1
    assert 'Buyer workspace is pending' in capsys.readouterr().err


def test_website_serves_without_openai_key(tmp_path, monkeypatch):
    initialize(tmp_path)
    observed = []
    monkeypatch.setattr('uvicorn.run', lambda app, **kw: observed.append(app))
    assert main(['--home', str(tmp_path), 'serve']) == 0
    assert observed[0].title == 'Takeoff supplier market'


def test_doctor_can_verify_supplier_while_buyer_is_deferred(tmp_path, monkeypatch, capsys):
    initialize(tmp_path)
    private_json(tmp_path / 'secrets.json', {'AMBIGUOUS_SUPPLIER_API_KEY': 'private-key'})
    def get(url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer private-key'
        return SimpleNamespace(raise_for_status=lambda: None,
            json=lambda: {'id': 'supplier', 'workspace_id': 'supplier-workspace', 'display_name': 'Supplier'})
    monkeypatch.setattr('takeoff_suppliers.cli.httpx.get', get)
    assert main(['--home', str(tmp_path), 'doctor']) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data['buyer_workspace'].startswith('pending')
    assert not data['live_agent_verified']
    assert 'private-key' not in output


def test_environment_secret_precedes_ignored_file(tmp_path, monkeypatch):
    initialize(tmp_path)
    monkeypatch.setenv('TAKEOFF_OPERATOR_TOKEN', 'environment-choice')
    assert Settings(tmp_path).secret('TAKEOFF_OPERATOR_TOKEN') == 'environment-choice'


def test_voice_fails_clearly_without_openai_key(tmp_path, monkeypatch, capsys):
    initialize(tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert main(['--home', str(tmp_path), 'serve', '--voice']) == 1
    assert 'OPENAI_API_KEY is missing' in capsys.readouterr().err
