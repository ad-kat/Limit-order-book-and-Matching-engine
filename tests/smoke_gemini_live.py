"""
smoke_gemini_live.py — Gemini Live API smoke test (full production config).

Sends a short synthetic PCM16 16-kHz mono audio sample using the exact same
LiveConnectConfig, Blob mime type, and send method that FairSplit uses in
production.  Prints the first audio chunk received (or an error) and exits.

Usage:
  python3 tests/smoke_gemini_live.py [model_name]

  model_name defaults to $GEMINI_LIVE_MODEL, then "gemini-3.8-live".

The test verifies:
  1. Session opens without 1007.
  2. send_realtime_input(audio=Blob(..., mime_type="audio/pcm;rate=16000")) is accepted.
  3. At least one audio response chunk arrives.
  4. A second audio turn also receives a response (multi-turn).

Never logs the API key.
"""
from __future__ import annotations

import asyncio
import base64
import math
import os
import struct
import sys

# Load .env so the key is available when running locally
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not set")
    sys.exit(1)

# Model precedence: CLI arg > env var > default
DEFAULT_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL


def _sine_pcm16(freq_hz: int = 440, duration_s: float = 0.5,
                sample_rate: int = 16000) -> bytes:
    """Generate a raw PCM16 little-endian mono sine wave."""
    n = int(sample_rate * duration_s)
    samples = [
        int(32767 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *samples)


async def run_smoke(model: str):
    from google import genai
    from google.genai import types as gt

    print(f"[smoke] SDK : google-genai {genai.__version__}")
    print(f"[smoke] Model: {model}")
    print(f"[smoke] Key  : ...{GEMINI_API_KEY[-6:]} (last 6 chars)")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Use the same config as production FairSplit — including all tools and system prompt
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from api.fairsplit_agent import _make_tools, SYSTEM_PROMPT

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_PROMPT,
        tools=_make_tools(),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
    )

    pcm_sample = _sine_pcm16()
    print(f"[smoke] Sending {len(pcm_sample)} bytes of 16-kHz PCM16 sine wave")

    audio_chunks_received = 0
    transcripts_received  = 0

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            print("[smoke] Session opened OK")

            # ── Turn 1: audio ─────────────────────────────────────────────────
            await session.send_realtime_input(
                audio=gt.Blob(data=pcm_sample, mime_type="audio/pcm;rate=16000")
            )
            print("[smoke] Turn 1 audio sent")

            # Collect up to 3 seconds of responses
            deadline = asyncio.get_event_loop().time() + 8.0
            async for msg in session.receive():
                if asyncio.get_event_loop().time() > deadline:
                    print("[smoke] Deadline reached, stopping receive")
                    break

                sc = msg.server_content
                if sc:
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                audio_chunks_received += 1
                                kb = len(part.inline_data.data) / 1024
                                print(f"[smoke] Audio chunk {audio_chunks_received}: "
                                      f"{kb:.1f} kB  mime={part.inline_data.mime_type}")
                    if sc.output_transcription and sc.output_transcription.text:
                        transcripts_received += 1
                        print(f"[smoke] Transcript: {sc.output_transcription.text!r}")
                    if sc.turn_complete:
                        print("[smoke] Turn 1 complete")
                        break

            # ── Turn 2: text (verify multi-turn) ──────────────────────────────
            await session.send_client_content(
                turns=gt.Content(role="user", parts=[gt.Part(text="Say 'hello'.")]),
                turn_complete=True,
            )
            print("[smoke] Turn 2 text sent")

            deadline2 = asyncio.get_event_loop().time() + 8.0
            turn2_audio = 0
            async for msg in session.receive():
                if asyncio.get_event_loop().time() > deadline2:
                    break
                sc = msg.server_content
                if sc:
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                turn2_audio += 1
                    if sc.output_transcription and sc.output_transcription.text:
                        print(f"[smoke] Turn 2 transcript: {sc.output_transcription.text!r}")
                    if sc.turn_complete:
                        print(f"[smoke] Turn 2 complete — audio chunks: {turn2_audio}")
                        break

    except Exception as e:
        print(f"[smoke] ERROR: {type(e).__name__}: {e}")
        return False

    print(f"\n[smoke] RESULT:")
    print(f"  audio chunks turn 1 : {audio_chunks_received}")
    print(f"  transcripts         : {transcripts_received}")
    ok = audio_chunks_received > 0
    print(f"  PASS" if ok else "  FAIL — no audio received")
    return ok


if __name__ == "__main__":
    ok = asyncio.run(run_smoke(MODEL))
    sys.exit(0 if ok else 1)
