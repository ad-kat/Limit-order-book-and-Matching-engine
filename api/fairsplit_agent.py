"""
fairsplit_agent.py — Gemini Live voice agent WebSocket proxy.

Verified against google-genai 2.29.0 / Gemini Live API (Oct 2026).

Model: models/gemini-2.5-flash-native-audio-latest  (bidiGenerateContent)
Audio in:  PCM 16-bit LE, 16 kHz, mono  (mime: audio/pcm;rate=16000)
Audio out: PCM 16-bit LE, 24 kHz, mono  (mime: audio/pcm;rate=24000)

Client → server WebSocket messages:
  JSON {"type":"text","text":"..."}       — text turn
  JSON {"type":"end_audio"}              — explicit end-of-turn after audio
  JSON {"type":"ping"}                   — keepalive
  raw bytes / base64 string              — PCM audio chunk (16 kHz, 16-bit LE)

Server → client WebSocket messages:
  {"type":"status",     "status":"connecting"|"connected"|"idle"|"error"}
  {"type":"transcript", "role":"user"|"model", "text":"..."}
  {"type":"audio",      "data":"<base64 PCM 24 kHz>", "mime":"audio/pcm;rate=24000"}
  {"type":"tool_call",  "tool":"...", "args":{...}, "result":{...}}
  {"type":"error",      "message":"..."}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("fairsplit.agent")

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
# Primary model: supports bidiGenerateContent + native audio I/O
GEMINI_MODEL    = "models/gemini-2.5-flash-native-audio-latest"
# Fallback: also supports bidiGenerateContent
GEMINI_FALLBACK = "models/gemini-3.1-flash-live-preview"

SYSTEM_PROMPT = (
    "You are FairSplit, an AI assistant helping students find compatible roommates "
    "and shared apartments in New York City. "
    "Be warm, concise, and proactive. "
    "When a user describes housing needs, use the available tools to search apartments "
    "and find compatible roommate groups. "
    "Always confirm before creating a group invitation. "
    "Synthetic demo data is in use — label any results as demo data."
)

# ── Tool declarations (genai 2.x keyword-arg style) ────────────────────────────

def _make_tools():
    from google.genai import types as gt
    return [
        gt.Tool(function_declarations=[
            gt.FunctionDeclaration(
                name="search_apartments",
                description="Search available apartments matching user preferences",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "max_budget":    {"type": "INTEGER", "description": "Max total monthly rent in cents (e.g. 366000 for $3,660)"},
                        "neighborhood":  {"type": "STRING",  "description": "Preferred neighborhood, e.g. Brooklyn"},
                        "bedrooms":      {"type": "INTEGER", "description": "Number of bedrooms"},
                    },
                },
            ),
            gt.FunctionDeclaration(
                name="find_compatible_roommates",
                description="Find compatible roommate groups for a specific apartment",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "apartment_id":  {"type": "STRING", "description": "Apartment UUID"},
                        "candidate_ids": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Optional candidate profile IDs to evaluate",
                        },
                    },
                    "required": ["apartment_id"],
                },
            ),
            gt.FunctionDeclaration(
                name="propose_roommate_group",
                description="Create a new roommate group for an apartment",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "apartment_id": {"type": "STRING"},
                        "created_by":   {"type": "STRING", "description": "Profile ID of the proposer"},
                        "member_ids":   {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Additional member profile IDs to invite",
                        },
                    },
                    "required": ["apartment_id", "created_by"],
                },
            ),
            gt.FunctionDeclaration(
                name="get_group_status",
                description="Get the current status of a roommate group",
                parameters={
                    "type": "OBJECT",
                    "properties": {"group_id": {"type": "STRING"}},
                    "required": ["group_id"],
                },
            ),
            gt.FunctionDeclaration(
                name="create_group_invitation",
                description="Invite someone to join an existing roommate group (requires prior user confirmation)",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "group_id":           {"type": "STRING"},
                        "inviter_profile_id": {"type": "STRING"},
                        "invitee_profile_id": {"type": "STRING"},
                    },
                    "required": ["group_id", "inviter_profile_id", "invitee_profile_id"],
                },
            ),
        ])
    ]


# ── Internal tool dispatch ─────────────────────────────────────────────────────

async def _call_internal(tool_name: str, args: dict) -> dict:
    try:
        import httpx
        base = os.getenv("INTERNAL_API_URL", "http://localhost:8000")
        async with httpx.AsyncClient(timeout=10.0) as client:
            if tool_name == "search_apartments":
                r = await client.post(f"{base}/fairsplit/search", json=args)
                r.raise_for_status()
                return {"apartments": r.json()}

            elif tool_name == "find_compatible_roommates":
                r = await client.post(f"{base}/fairsplit/match", json=args)
                r.raise_for_status()
                return r.json()

            elif tool_name == "propose_roommate_group":
                r = await client.post(f"{base}/fairsplit/groups", json=args)
                r.raise_for_status()
                return r.json()

            elif tool_name == "get_group_status":
                gid = args.get("group_id", "")
                r = await client.get(f"{base}/fairsplit/groups/{gid}")
                r.raise_for_status()
                return r.json()

            elif tool_name == "create_group_invitation":
                gid = args.get("group_id", "")
                r = await client.post(f"{base}/fairsplit/groups/{gid}/invite", json=args)
                r.raise_for_status()
                return r.json()

            else:
                return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.warning(f"[agent] internal call {tool_name} failed: {e}")
        return {"error": str(e)}


# ── Text fallback (no GEMINI_API_KEY) ─────────────────────────────────────────

async def _text_fallback_session(ws: WebSocket):
    await ws.send_json({"type": "status", "status": "connected"})
    await ws.send_json({
        "type": "transcript", "role": "model",
        "text": "Hi! I'm FairSplit (demo mode — no Gemini key). "
                "Try: 'Find apartments in Brooklyn' or 'Find roommates'.",
    })
    while True:
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            break
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") != "text":
            continue
        text = msg.get("text", "")
        await ws.send_json({"type": "transcript", "role": "user", "text": text})
        tl = text.lower()
        if "brooklyn" in tl or "apartment" in tl or "find" in tl:
            args = {"neighborhood": "Brooklyn"} if "brooklyn" in tl else {}
            result = await _call_internal("search_apartments", args)
            apts = result.get("apartments", [])[:3]
            names = [a.get("title", a.get("id", "?")) for a in apts]
            reply = f"Found {len(apts)} apartments" + (f": {', '.join(names)}." if names else ".")
            await ws.send_json({"type": "tool_call", "tool": "search_apartments", "args": args, "result": result})
        elif "roommate" in tl or "match" in tl:
            apt_id = "apt-brooklyn-3br-001"
            result = await _call_internal("find_compatible_roommates", {"apartment_id": apt_id})
            groups = result.get("top_groups", [])
            ppr = result.get("per_person_rent", 0)
            reply = f"Found {len(groups)} compatible group(s) at ${ppr//100}/person."
            if groups:
                names = [m.get("display_name", "?") for m in groups[0].get("members", [])]
                reply += f" Best match: {', '.join(names)}."
            await ws.send_json({"type": "tool_call", "tool": "find_compatible_roommates",
                                "args": {"apartment_id": apt_id}, "result": result})
        else:
            reply = "I can search apartments or find roommates. What do you need?"
        await ws.send_json({"type": "transcript", "role": "model", "text": reply})


# ── Gemini Live receive loop ───────────────────────────────────────────────────

async def _recv_loop(ws: WebSocket, session, transcript_buf: list):
    """Read all Gemini server messages; forward audio, transcripts, tool calls."""
    from google.genai import types as gt
    try:
        async for msg in session.receive():
            sc = msg.server_content
            if sc:
                # Audio chunks
                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            encoded = base64.b64encode(part.inline_data.data).decode()
                            await ws.send_json({
                                "type": "audio",
                                "data": encoded,
                                "mime": part.inline_data.mime_type or "audio/pcm;rate=24000",
                            })
                        if part.text and not getattr(part, "thought", False):
                            transcript_buf.append(part.text)

                # Output transcription (streamed word-by-word)
                if sc.output_transcription and sc.output_transcription.text:
                    await ws.send_json({
                        "type": "transcript", "role": "model",
                        "text": sc.output_transcription.text,
                    })

                # Input transcription (what user said)
                if sc.input_transcription and sc.input_transcription.text:
                    await ws.send_json({
                        "type": "transcript", "role": "user",
                        "text": sc.input_transcription.text,
                    })

            # Tool calls
            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    args = dict(fc.args) if fc.args else {}
                    result = await _call_internal(fc.name, args)
                    await ws.send_json({
                        "type": "tool_call", "tool": fc.name,
                        "args": args, "result": result,
                    })
                    await session.send_tool_response(function_responses=[
                        gt.FunctionResponse(id=fc.id, name=fc.name, response={"result": result})
                    ])

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[agent] recv_loop error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Gemini Live send loop ──────────────────────────────────────────────────────

async def _send_loop(ws: WebSocket, session):
    """Forward client WebSocket messages to Gemini."""
    from google.genai import types as gt
    try:
        while True:
            raw = await ws.receive()
            # FastAPI WebSocket can receive text or bytes
            if "text" in raw:
                data = raw["text"]
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    # Treat as raw base64 audio
                    audio_bytes = base64.b64decode(data)
                    await session.send_realtime_input(
                        audio=gt.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                    )
                    continue

                if msg.get("type") == "text":
                    await session.send_client_content(
                        turns=gt.Content(role="user", parts=[gt.Part(text=msg["text"])]),
                        turn_complete=True,
                    )

                elif msg.get("type") == "audio_chunk":
                    audio_bytes = base64.b64decode(msg["data"])
                    await session.send_realtime_input(
                        audio=gt.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                    )

                elif msg.get("type") == "end_audio":
                    await session.send_realtime_input(audio_stream_end=True)

                # "ping" and unknown types are silently ignored

            elif "bytes" in raw:
                # Raw PCM bytes from client
                await session.send_realtime_input(
                    audio=gt.Blob(data=raw["bytes"], mime_type="audio/pcm;rate=16000")
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[agent] send_loop error: {e}")


# ── Main Gemini Live session ───────────────────────────────────────────────────

async def _gemini_live_session(ws: WebSocket):
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        await ws.send_json({"type": "error", "message": "google-genai not installed"})
        return

    await ws.send_json({"type": "status", "status": "connecting"})

    client = genai.Client(api_key=GEMINI_API_KEY)

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_PROMPT,
        tools=_make_tools(),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
    )

    model = GEMINI_MODEL
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            await ws.send_json({"type": "status", "status": "connected"})
            transcript_buf: list = []
            await asyncio.gather(
                _send_loop(ws, session),
                _recv_loop(ws, session, transcript_buf),
            )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        err_str = str(e)
        logger.error(f"[agent] {model} error: {err_str}")
        # Try fallback model
        if "not found" in err_str.lower() or "404" in err_str or "unsupported" in err_str.lower():
            logger.info(f"[agent] Retrying with fallback {GEMINI_FALLBACK}")
            try:
                async with client.aio.live.connect(model=GEMINI_FALLBACK, config=config) as session:
                    await ws.send_json({"type": "status", "status": "connected"})
                    transcript_buf: list = []
                    await asyncio.gather(
                        _send_loop(ws, session),
                        _recv_loop(ws, session, transcript_buf),
                    )
            except Exception as e2:
                logger.error(f"[agent] fallback error: {e2}")
                try:
                    await ws.send_json({"type": "error", "message": str(e2)})
                except Exception:
                    pass
        else:
            try:
                await ws.send_json({"type": "error", "message": err_str})
            except Exception:
                pass


# ── Entry point ────────────────────────────────────────────────────────────────

async def agent_websocket_handler(ws: WebSocket):
    await ws.accept()
    if not GEMINI_API_KEY:
        logger.warning("[agent] GEMINI_API_KEY not set — text fallback active")
        await ws.send_json({
            "type": "error",
            "message": "GEMINI_API_KEY not configured — voice disabled, text input available",
        })
        await _text_fallback_session(ws)
        return
    await _gemini_live_session(ws)
