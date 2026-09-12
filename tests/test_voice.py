"""Offline protocol tests; these do not establish a live cross-computer call."""

import asyncio
import base64
import io
import json
from pathlib import Path
import sqlite3
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from takeoff_suppliers.voice import OpenAIAudio, attach_voice, current_quote, validate_wav


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 1600)
    return output.getvalue()


QUOTE = {"quote_id": "quote-1", "revision": 1, "total_payable": "130.00",
         "lines": [{"product_id": "board", "quantity": 10, "unit": "each"}],
         "delivery": "Friday", "status": "issued"}
PATH = "/v1/runs/run-1/vendors/local/call"


class Market:
    def __init__(self, directory):
        self.db_path = directory / "market.sqlite3"
        self.quote = dict(QUOTE)

    def get_run(self, run_id):
        return {"buyer_id": "buyer-1" if run_id == "run-1" else "different-buyer"}

    def get_offer(self, run_id, quote_id, buyer_id):
        assert (run_id, quote_id, buyer_id) == ("run-1", "quote-1", "buyer-1")
        return self.quote


class Runtime:
    def __init__(self):
        self.calls = []

    async def respond(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"message": "Ten boards including delivery are 130 dollars.", "offers": [dict(QUOTE)]}


def setup(tmp_path, handler=None, duration=120):
    requests = []

    def transport(request):
        requests.append(request)
        if handler:
            return handler(request)
        if request.url.path.endswith("transcriptions"):
            return httpx.Response(200, json={"text": "Can you deliver ten boards Friday?"})
        return httpx.Response(200, content=wav_bytes())

    audio = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    app = FastAPI()
    market = Market(tmp_path)
    runtime = Runtime()
    attach_voice(app, market, runtime, "buyer-secret", "buyer-1", "openai-secret",
                 audio_client=audio, max_seconds=duration)
    return app, market, runtime, requests


def turn(ws):
    ws.send_bytes(wav_bytes())
    assert ws.receive_json()["type"] == "transcript"
    event = ws.receive_json()
    assert event["type"] == "supplier_turn"
    assert base64.b64decode(event["wav_base64"]) == wav_bytes()
    return event["candidates"][0]


def evidence(tmp_path):
    with sqlite3.connect(tmp_path / "voice.sqlite3") as db:
        rows = db.execute("SELECT evidence FROM voice_calls").fetchall()
    return [json.loads(row[0]) for row in rows]


def test_call_transcribes_speaks_and_confirms_exact_terms(tmp_path):
    app, _, runtime, requests = setup(tmp_path)
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        assert "AI-generated" in ws.receive_json()["disclosure"]
        candidate = turn(ws)
        ws.send_json({"type": "confirm_quote", **candidate})
        confirmed = ws.receive_json()
        assert confirmed["type"] == "confirmed_quote"
        assert confirmed["order_placed"] is False
        assert confirmed["quote"] == QUOTE
    call = evidence(tmp_path)[0]
    assert call["outcome"] == "confirmed_readback"
    assert "secret" not in json.dumps(call)
    assert runtime.calls[0][1]["channel"] == "phone"
    assert requests[0].headers["authorization"] == "Bearer openai-secret"
    assert b"gpt-4o-mini-transcribe" in requests[0].content
    speech = json.loads(requests[1].content)
    assert speech["model"] == "gpt-4o-mini-tts"
    assert "130.00" in speech["input"]


@pytest.mark.parametrize("token,path", [
    ("wrong", PATH), ("buyer-secret", PATH.replace("run-1", "another-run"))])
def test_auth_and_run_ownership_before_provider_call(tmp_path, token, path):
    app, _, runtime, requests = setup(tmp_path)
    with TestClient(app) as client, client.websocket_connect(path) as ws:
        ws.send_json({"token": token})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert not requests and not runtime.calls
    assert not evidence(tmp_path)


def test_changed_or_inexact_quote_is_not_confirmed(tmp_path):
    app, market, _, _ = setup(tmp_path)
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        ws.receive_json()
        candidate = turn(ws)
        ws.send_json({"type": "confirm_quote", **candidate,
                      "quote": {**candidate["quote"], "total_payable": "1.00"}})
        assert ws.receive_json()["type"] == "error"
        market.quote = {**market.quote, "revision": 2}
        ws.send_json({"type": "confirm_quote", **candidate})
        assert "changed" in ws.receive_json()["message"]
        ws.send_json({"type": "end"})
        assert ws.receive_json()["confirmed"] is False
    assert evidence(tmp_path)[0]["confirmed_quote"] is None


def test_disconnect_retains_unconfirmed_evidence(tmp_path):
    app, _, _, _ = setup(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(PATH) as ws:
            ws.send_json({"token": "buyer-secret"})
            ws.receive_json()
            turn(ws)
    assert evidence(tmp_path)[0]["outcome"] == "disconnected_unconfirmed"


def test_eight_exchange_limit_still_allows_readback_confirmation(tmp_path):
    app, _, runtime, requests = setup(tmp_path)
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        ws.receive_json()
        for _ in range(8):
            candidate = turn(ws)
        ws.send_bytes(wav_bytes())
        assert "limit" in ws.receive_json()["message"]
        ws.send_json({"type": "confirm_quote", **candidate})
        assert ws.receive_json()["type"] == "confirmed_quote"
    assert len(runtime.calls) == 8
    assert len({kwargs["request_id"] for _, kwargs in runtime.calls}) == 8
    assert len(requests) == 16


def test_provider_error_is_sanitized_and_unconfirmed(tmp_path):
    app, _, runtime, _ = setup(tmp_path, lambda _: httpx.Response(500, text="private-provider-error"))
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        ws.receive_json()
        ws.send_bytes(wav_bytes())
        event = ws.receive_json()
        assert event["type"] == "error"
        assert "private" not in str(event)
    assert not runtime.calls
    assert evidence(tmp_path)[0]["outcome"] == "error_unconfirmed"


def test_total_deadline_includes_provider_wait(tmp_path):
    async def slow(request):
        await asyncio.sleep(0.15)
        return httpx.Response(200, json={"text": "late"})

    app = FastAPI()
    market = Market(tmp_path)
    audio = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    attach_voice(app, market, Runtime(), "buyer-secret", "buyer-1", "key",
                 audio_client=audio, max_seconds=0.05)
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        ws.receive_json()
        ws.send_bytes(wav_bytes())
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert evidence(tmp_path)[0]["outcome"] == "timeout_unconfirmed"


def test_audio_validation():
    validate_wav(wav_bytes())
    with pytest.raises(ValueError):
        validate_wav(b"not-wav")
    with pytest.raises(ValueError):
        validate_wav(b"x" * 2_000_001)
    with pytest.raises(ValueError):
        validate_wav(wav_bytes()[:-1])


def test_expired_or_nonissued_quotes_cannot_be_confirmed():
    assert current_quote(QUOTE)
    assert not current_quote({**QUOTE, "status": "rejected"})
    assert not current_quote({**QUOTE, "expires_at": "2020-01-01T00:00:00Z"})
    assert not current_quote({**QUOTE, "expires_at": 1})
    assert not current_quote({**QUOTE, "expires_at": "unknown"})


def test_long_readback_chunks_fit_speech_limit_and_merge_wav_frames():
    inputs = []
    def provider(request):
        text = json.loads(request.content)["input"]
        assert len(text) <= 4096
        inputs.append(text)
        return httpx.Response(200, content=wav_bytes())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await OpenAIAudio(client, "key").speak("quoted terms " * 800)

    audio = asyncio.run(run())
    assert "".join(inputs) == "quoted terms " * 800
    assert len(inputs) == 3
    with wave.open(io.BytesIO(audio), "rb") as merged:
        assert merged.getnframes() == 1600 * 3
        assert merged.getframerate() == 16000


def test_sync_runtime_receives_remaining_budget_and_cancellation(tmp_path):
    class SyncRuntime:
        cancel = None

        def respond(self, *args, timeout_seconds, cancel_event, **kwargs):
            assert 0 < timeout_seconds <= 120
            assert not cancel_event.is_set()
            self.cancel = cancel_event
            return {"message": "Please clarify the required delivery date.", "offers": []}

    runtime = SyncRuntime()
    def provider(request):
        if request.url.path.endswith("transcriptions"):
            return httpx.Response(200, json={"text": "Can you deliver?"})
        return httpx.Response(200, content=wav_bytes())

    app = FastAPI()
    attach_voice(app, Market(tmp_path), runtime, "buyer-secret", "buyer-1", "key",
                 audio_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    with TestClient(app) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"token": "buyer-secret"})
        ws.receive_json()
        ws.send_bytes(wav_bytes())
        assert ws.receive_json()["type"] == "transcript"
        assert ws.receive_json()["candidates"] == []
        ws.send_json({"type": "end"})
        ws.receive_json()
    assert runtime.cancel.is_set()
