"""Offline tests for browser recording uploads and private evidence files."""
from email.message import Message
import asyncio
import io
import json
import stat
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from integrations.voice.human_call import HumanCall, MAX_RECORDING_BYTES, make_handler


WEBM = b'\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm' + b'audio-placeholder'


def make_call(tmp_path):
    return HumanCall({'run_id': 'run-test', 'vendor_id': 'local', 'allowed_actions': {},
                      'objective': 'Discuss a material package.'}, {}, tmp_path, 'session-test')


def request(call, data=WEBM, *, content_length=None, mime='audio/webm', origin='https://seller.example',
            path=None, transfer=None, extra_length=None):
    server = SimpleNamespace(token='private-token', calls={call.attempt_id: call},
                             public_origin='https://seller.example')
    handler = make_handler(server).__new__(make_handler(server))
    handler.path = path or f'/s/private-token/api/recording?attempt={call.attempt_id}'
    handler.headers = Message()
    for name, value in [('Host', '127.0.0.1:3000'), ('Origin', origin), ('Content-Type', mime),
                        ('Content-Length', str(len(data)) if content_length is None else content_length)]:
        handler.headers[name] = value
    if extra_length is not None:
        handler.headers['Content-Length'] = extra_length
    if transfer:
        handler.headers['Transfer-Encoding'] = transfer
    handler.connection = SimpleNamespace(settimeout=lambda value: None)
    handler.rfile = io.BytesIO(data)
    response = []
    handler.reply = lambda status, body, *args: response.append((status, body))
    handler.do_POST()
    return response[0]


def test_recording_is_private_idempotent_and_cannot_be_overwritten(tmp_path):
    call = make_call(tmp_path)
    assert request(call) == (201, {'saved': True, 'bytes': len(WEBM)})
    assert request(call)[0] == 201
    assert request(call, WEBM + b'changed')[0] == 409
    assert (call.directory / 'call.webm').read_bytes() == WEBM
    saved = json.loads((call.directory / 'call.json').read_text())
    assert saved['evidence']['audio_sha256']
    assert stat.S_IMODE(call.directory.stat().st_mode) == 0o700
    for name in ('call.webm', 'call.json'):
        assert stat.S_IMODE((call.directory / name).stat().st_mode) == 0o600


@pytest.mark.parametrize('kwargs, expected', [
    ({'content_length': 'bad'}, 400), ({'content_length': '-1'}, 400),
    ({'content_length': str(MAX_RECORDING_BYTES + 1)}, 400),
    ({'content_length': str(len(WEBM) + 3)}, 400),
    ({'extra_length': '3'}, 400), ({'transfer': 'chunked'}, 400),
    ({'mime': 'text/plain'}, 415), ({'data': b'not audio'}, 400),
    ({'data': b'\x1a\x45\xdf\xa3not-WebM'}, 400),
    ({'origin': 'https://unrelated.ts.net'}, 403), ({'origin': 'http://localhost:9000'}, 403),
    ({'origin': 'http://['}, 403),
])
def test_bad_uploads_and_untrusted_origins_never_write_recordings(tmp_path, kwargs, expected):
    call = make_call(tmp_path)
    assert request(call, **kwargs)[0] == expected
    assert not (call.directory / 'call.webm').exists()
    assert 'audio_path' not in call.result['evidence']


def test_unknown_duplicate_attempt_and_noncanonical_endpoint_rejected(tmp_path):
    call = make_call(tmp_path)
    prefix = '/s/private-token'
    for path, expected in [
        (prefix + '/api/recording?attempt=unknown', 404),
        (prefix + f'/api/recording?attempt={call.attempt_id}&attempt={call.attempt_id}', 400),
        (prefix + f'/other/api/recording?attempt={call.attempt_id}', 404),
        ('/s/wrong/api/recording?attempt=' + call.attempt_id, 404),
    ]:
        assert request(call, path=path)[0] == expected
    assert not (call.directory / 'call.webm').exists()


def test_transcript_merges_fragments_and_preserves_timeline_and_audio_evidence(tmp_path):
    call = make_call(tmp_path)
    call.seller_text.extend([{'text': 'Hello ', 'start_ms': 100}, {'text': 'there.', 'start_ms': 150}])
    call.buyer_text.append({'text': 'Good morning.', 'start_ms': 200})
    call.save_recording(WEBM)
    call.finish('unconfirmed', 'session closed by the seller')
    transcript = (call.directory / 'transcript.txt').read_text()
    assert 'SELLER Hello there.' in transcript
    assert 'BUYER  Good morning.' in transcript
    assert transcript.index('Hello there.') < transcript.index('Good morning.')
    assert stat.S_IMODE((call.directory / 'transcript.txt').stat().st_mode) == 0o600
    assert json.loads((call.directory / 'call.json').read_text())['evidence']['audio_sha256']


def test_observer_persists_speech_received_after_end_call(tmp_path):
    call = make_call(tmp_path)
    call.request['constraints'] = {'max_seconds': 60}

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            return self.frames()

        async def frames(self):
            call.finish('unconfirmed', 'buyer ended the call')
            yield json.dumps({'type': 'session.output_transcript.delta', 'delta': 'Thank you, goodbye.',
                              'start_ms': 500, 'end_ms': 900})
            yield json.dumps({'type': 'session.closed'})

    with patch('websockets.asyncio.client.connect', return_value=Connection()):
        asyncio.run(call.observe())
    assert 'Thank you, goodbye.' in (call.directory / 'transcript.txt').read_text()


def test_evidence_replace_failure_preserves_prior_file_and_removes_temporary(tmp_path):
    call = make_call(tmp_path)
    before = (call.directory / 'call.json').read_bytes()
    with patch('integrations.voice.human_call.os.replace', side_effect=OSError('disk unavailable')):
        with pytest.raises(OSError):
            call.save()
    assert (call.directory / 'call.json').read_bytes() == before
    assert {path.name for path in call.directory.iterdir()} == {'call.json'}


def test_http_logs_redact_bearer_url_token(capsys):
    handler_type = make_handler(SimpleNamespace(token='private-token'))
    handler = handler_type.__new__(handler_type)
    handler.address_string = lambda: '127.0.0.1'
    handler.log_message('%s', 'POST /s/private-token/api/recording?attempt=call HTTP/1.1')
    output = capsys.readouterr().err
    assert 'private-token' not in output
    assert '/s/[redacted]/api/recording' in output
