"""Optional turn-based live voice transport; no automatic purchasing actions.

WAV input/output travels over one WebSocket. Audio transcription and synthesis
use OpenAI HTTP APIs. A confirmed call quote is evidence of readback, not an order.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import io
import inspect
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid
import wave

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

MAX_AUDIO_BYTES = 2_000_000
MAX_SECONDS = 120
MAX_EXCHANGES = 8


def validate_wav(audio: bytes) -> None:
    """Reject oversized, malformed or excessively long turns before upload."""
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("A WAV turn must be between 1 byte and 2 MB.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getnchannels() not in (1, 2) or wav.getsampwidth() not in (1, 2, 3, 4):
                raise ValueError("Unsupported WAV format.")
            if not 8000 <= wav.getframerate() <= 48000:
                raise ValueError("WAV sample rate must be 8–48 kHz.")
            if wav.getnframes() / wav.getframerate() > 30:
                raise ValueError("Each audio turn must be at most 30 seconds.")
            expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(wav.getnframes())) != expected:
                raise ValueError("Truncated WAV data.")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Provide a complete PCM WAV file.") from exc


class OpenAIAudio:
    """Thin injectable HTTP audio client. The caller owns its HTTP lifecycle."""

    def __init__(self, client: httpx.AsyncClient, api_key: str):
        self.client = client
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def transcribe(self, audio: bytes) -> str:
        validate_wav(audio)
        response = await self.client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=self.headers,
            data={"model": "gpt-4o-mini-transcribe", "response_format": "json"},
            files={"file": ("turn.wav", audio, "audio/wav")},
        )
        response.raise_for_status()
        text = response.json().get("text", "").strip()
        if not text:
            raise ValueError("No intelligible speech. Repeat the request.")
        return text

    async def speak(self, text: str) -> bytes:
        if not text or len(text) > 16000:
            raise ValueError("Supplier readback is too long for a voice turn.")
        parts = []
        size = 0
        # The speech endpoint accepts at most 4096 input characters per request.
        # Retain every readback character; merge WAV frames, never WAV headers.
        for start in range(0, len(text), 4096):
            response = await self.client.post(
                "https://api.openai.com/v1/audio/speech",
                headers=self.headers,
                json={"model": "gpt-4o-mini-tts", "voice": "coral", "input": text[start:start + 4096],
                      "response_format": "wav"},
            )
            response.raise_for_status()
            size += len(response.content)
            if size > 8_000_000:
                raise ValueError("Supplier audio exceeded the call limit.")
            parts.append(response.content)
        if len(parts) == 1:
            return parts[0]
        output = io.BytesIO()
        with wave.open(output, "wb") as merged:
            format_key = None
            for part in parts:
                with wave.open(io.BytesIO(part), "rb") as source:
                    current = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
                    if format_key is None:
                        format_key = current
                        merged.setparams(source.getparams())
                    elif current != format_key:
                        raise ValueError("Speech audio formats changed during the readback.")
                    merged.writeframes(source.readframes(source.getnframes()))
        return output.getvalue()


def quote_digest(quote: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(quote, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def current_quote(quote: dict[str, Any]) -> bool:
    """Readback cannot revive an expired, rejected, or superseded proposal."""
    if quote.get("status") != "issued":
        return False
    expires = quote.get("expires_at")
    if expires is None:
        return True
    try:
        expiry = (float(expires) if isinstance(expires, (float, int))
                  else datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp())
        return expiry > datetime.now(timezone.utc).timestamp()
    except (ValueError, TypeError, AttributeError):
        return False


class CallEvidence:
    """Separate local evidence ledger; stores text and terms, never keys/audio."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS voice_calls "
                       "(call_id TEXT PRIMARY KEY, run_id TEXT, buyer_id TEXT, "
                       "vendor_id TEXT, outcome TEXT, evidence TEXT)")

    def save(self, call: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO voice_calls VALUES (?, ?, ?, ?, ?, ?)",
                       (call["call_id"], call["run_id"], call["buyer_id"],
                        call["vendor_id"], call["outcome"], json.dumps(call)))


def attach_voice(app: FastAPI, market: Any, runtime: Any, buyer_token: str,
                 buyer_id: str, openai_api_key: str, *,
                 audio_client: httpx.AsyncClient | None = None,
                 evidence_path: str | Path | None = None,
                 max_seconds: float = MAX_SECONDS) -> None:
    """Attach the optional call route; runtime and market stay application owned.

    market.get_run(run_id) returns buyer_id; market.get_offer(run_id, quote_id, buyer_id)
    returns the current public quote. runtime.respond returns
    {message: str, offers: list[dict]}. An injected HTTP client enables offline QA.
    """
    if not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError("Call duration must be greater than zero and at most 120 seconds.")
    evidence = CallEvidence(evidence_path or Path(market.db_path).parent / "voice.sqlite3")

    @app.websocket("/v1/runs/{run_id}/vendors/{vendor_id}/call")
    async def call_socket(ws: WebSocket, run_id: str, vendor_id: str) -> None:
        await ws.accept()
        call = {"call_id": str(uuid.uuid4()), "run_id": run_id,
                "buyer_id": buyer_id, "vendor_id": vendor_id,
                "outcome": "unconfirmed", "events": [], "confirmed_quote": None,
                "transport": "websocket_audio", "started_at": time.time()}
        authenticated = False
        deadline = time.monotonic() + max_seconds
        cancel_event = threading.Event()
        owned_client = audio_client is None
        client = audio_client or httpx.AsyncClient(timeout=30)
        audio_api = OpenAIAudio(client, openai_api_key)
        try:
            async with asyncio.timeout(max_seconds):
                async with asyncio.timeout(min(10, max_seconds)):
                    auth = await ws.receive_json()
                token = auth.get("token", "")
                if (not buyer_token or not isinstance(token, str)
                        or not hmac.compare_digest(token.encode(), buyer_token.encode())):
                    await ws.close(code=1008, reason="Unauthorized")
                    return
                run = market.get_run(run_id)
                if run.get("buyer_id") != buyer_id:
                    await ws.close(code=1008, reason="Run unavailable")
                    return
                authenticated = True
                if not openai_api_key:
                    await ws.send_json({"type": "error", "message": "Voice API is not configured."})
                    return
                await ws.send_json({"type": "ready", "call_id": call["call_id"],
                                    "max_exchanges": MAX_EXCHANGES,
                                    "max_seconds": max_seconds,
                                    "disclosure": "You are speaking with an AI supplier using an AI-generated voice."})
                candidates: dict[str, dict[str, Any]] = {}
                exchanges = 0
                while True:
                    frame = await ws.receive()
                    if frame["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect(frame.get("code", 1000))
                    raw_audio = frame.get("bytes")
                    if raw_audio is None:
                        raw_text = frame.get("text", "")
                        if len(raw_text) > MAX_AUDIO_BYTES * 2:
                            raise ValueError("Input frame is too large.")
                        message = json.loads(raw_text)
                        kind = message.get("type")
                        if kind == "end":
                            call["outcome"] = "ended_unconfirmed"
                            await ws.send_json({"type": "ended", "confirmed": False})
                            break
                        if kind == "confirm_quote":
                            digest = message.get("readback_digest")
                            supplied = message.get("quote")
                            candidate = candidates.get(digest) if isinstance(digest, str) else None
                            if not candidate or supplied != candidate:
                                await ws.send_json({"type": "error", "message": "Repeat the exact candidate quote and readback digest."})
                                continue
                            current = market.get_offer(run_id, candidate["quote_id"], buyer_id)
                            if current != candidate or not current_quote(current):
                                await ws.send_json({"type": "error", "message": "Quote changed; request a fresh readback."})
                                continue
                            call["confirmed_quote"] = candidate
                            call["outcome"] = "confirmed_readback"
                            call["events"].append({"type": "readback_confirmed", "quote": candidate})
                            # Save before acknowledging; this confirms terms, never purchases.
                            evidence.save(call)
                            await ws.send_json({"type": "confirmed_quote", "call_id": call["call_id"],
                                                "quote": candidate, "order_placed": False})
                            break
                        if kind != "audio":
                            raise ValueError("Send audio, confirm_quote, or end.")
                        encoded = message.get("wav_base64", "")
                        if not isinstance(encoded, str) or len(encoded) > 2_700_000:
                            raise ValueError("Invalid audio frame.")
                        raw_audio = base64.b64decode(encoded, validate=True)
                    if exchanges >= MAX_EXCHANGES:
                        await ws.send_json({"type": "error", "message": "Exchange limit reached; confirm the last quote or end."})
                        continue
                    transcript = await audio_api.transcribe(raw_audio)
                    exchanges += 1
                    candidates.clear()
                    call["events"].append({"type": "buyer_transcript", "text": transcript})
                    await ws.send_json({"type": "transcript", "text": transcript})
                    args = (run_id, vendor_id, buyer_id, transcript)
                    kwargs = {"channel": "phone", "request_id": f"{call['call_id']}:{exchanges}"}
                    if inspect.iscoroutinefunction(runtime.respond):
                        result = await runtime.respond(*args, **kwargs)
                    else:
                        result = await asyncio.to_thread(
                            runtime.respond, *args, **kwargs,
                            timeout_seconds=max(0.001, deadline - time.monotonic()),
                            cancel_event=cancel_event,
                        )
                    # Runtime commercial functions supply canonical public quotes.
                    offers = result.get("offers", [])
                    readback = result["message"]
                    if offers:
                        readback += "\nPlease confirm these exact quoted terms; this is not an order: "
                        readback += json.dumps(offers, sort_keys=True, ensure_ascii=False)
                    voice = await audio_api.speak(readback)
                    for quote in offers:
                        candidates[quote_digest(quote)] = quote
                    call["events"].append({"type": "supplier_readback", "text": readback,
                                           "offers": offers})
                    evidence.save(call)
                    await ws.send_json({"type": "supplier_turn", "text": readback,
                                        "wav_base64": base64.b64encode(voice).decode(),
                                        "candidates": [{"quote": q, "readback_digest": d}
                                                       for d, q in candidates.items()]})
        except WebSocketDisconnect:
            call["outcome"] = "disconnected_unconfirmed"
            call["confirmed_quote"] = None
        except TimeoutError:
            call["outcome"] = "timeout_unconfirmed"
            call["confirmed_quote"] = None
        except Exception:
            call["outcome"] = "error_unconfirmed"
            call["confirmed_quote"] = None
            # Do not expose provider errors, prompts, tokens, or private state.
            try:
                await ws.send_json({"type": "error", "message": "Call could not confirm a quote. Continue with the core suppliers."})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            cancel_event.set()
            if authenticated:
                call["finished_at"] = time.time()
                evidence.save(call)
            if owned_client:
                await client.aclose()
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass


async def dial(url: str, token: str, wav_paths: list[Path], output_directory: Path) -> None:
    """Interactive calling client. Caller supplies WAV turns and confirms manually."""
    from websockets.asyncio.client import connect

    if not url.startswith(("wss://", "ws://127.0.0.1", "ws://localhost")):
        raise ValueError("Use wss:// outside a local development connection.")
    output_directory.mkdir(parents=True, exist_ok=True)
    async with connect(url, max_size=12_000_000, open_timeout=10) as socket:
        await socket.send(json.dumps({"token": token}))
        print(await socket.recv())
        for index, path in enumerate(wav_paths, 1):
            audio = path.read_bytes()
            validate_wav(audio)
            await socket.send(audio)
            while True:
                event = json.loads(await socket.recv())
                encoded = event.pop("wav_base64", None)
                if encoded:
                    destination = output_directory / f"supplier-{index}.wav"
                    destination.write_bytes(base64.b64decode(encoded))
                    print(f"Supplier audio: {destination}")
                print(json.dumps(event, indent=2))
                if event["type"] == "supplier_turn":
                    for candidate in event["candidates"]:
                        answer = await asyncio.to_thread(input, "Confirm this exact readback (not an order)? [yes/no] ")
                        if answer.strip().lower() == "yes":
                            await socket.send(json.dumps({"type": "confirm_quote", **candidate}))
                            print(await socket.recv())
                            return
                    break
                if event["type"] in ("error", "ended"):
                    return
        await socket.send(json.dumps({"type": "end"}))
        print(await socket.recv())


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the optional supplier voice endpoint with WAV turns.")
    parser.add_argument("url")
    parser.add_argument("wav", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, default=Path(".local/suppliers/call-audio"))
    args = parser.parse_args()
    token = os.environ.get("TAKEOFF_BUYER_TOKEN", "")
    if not token:
        parser.error("Set TAKEOFF_BUYER_TOKEN in the local environment.")
    asyncio.run(dial(args.url, token, args.wav, args.output))


if __name__ == "__main__":
    main()
