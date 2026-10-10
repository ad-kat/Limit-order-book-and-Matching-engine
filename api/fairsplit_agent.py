"""
fairsplit_agent.py — Gemini Live voice agent WebSocket proxy.

Verified against google-genai 2.29.0 / Gemini Live API (Oct 2026).

Model: $GEMINI_LIVE_MODEL (default: gemini-3.8-live)  — bidiGenerateContent
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
# Model is configurable via GEMINI_LIVE_MODEL env var.
# Default: gemini-3.8-live — independently verified to support native audio I/O,
# real-time audio input via send_realtime_input, and function calling.
# Do NOT use the models/ prefix — the SDK resolves the name correctly without it.
GEMINI_MODEL    = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")

_DEMO_OWNER_PROFILE_ID = "profile-alex-001"   # demo session owner for offer creation

SYSTEM_PROMPT = (
    "You are FairSplit, an AI assistant helping students find compatible roommates "
    "and shared apartments in New York City. "
    "Be warm, concise, and proactive. "
    "When a user describes housing needs, use the available tools to search apartments "
    "and find compatible roommate groups. "
    "Always confirm before creating a group invitation. "
    "Synthetic demo data is in use — label any results as demo data.\n\n"
    "BUDGET MATH: When a user gives a per-person budget, pass it as "
    "max_rent_per_person_dollars (plain US dollars, e.g. 1300 for $1,300/person) "
    "and set num_people to the number of people sharing. "
    "Example: '$1,300/person, 3 people' -> max_rent_per_person_dollars=1300, num_people=3. "
    "The server multiplies these for you — do NOT pre-multiply or convert to cents.\n\n"
    "ROOM OFFERS: When a user says they already have a room and want to find a roommate, "
    "gather: neighborhood, rent per room (dollars/month), move-in date, smoking policy, "
    "and number of rooms available. "
    "Always resolve the full date as YYYY-MM-DD — if the year is unclear, ask. "
    "Today is October 2026, so 'May 15' means 2027-05-15 unless the user says otherwise. "
    "Repeat all details back and wait for explicit yes/confirm before calling "
    "create_housing_offer. "
    f"Always use owner_profile_id='{_DEMO_OWNER_PROFILE_ID}' for demo session offers."
)

# ── Tool declarations (genai 2.x keyword-arg style) ────────────────────────────

def _make_tools():
    from google.genai import types as gt
    return [
        gt.Tool(function_declarations=[
            gt.FunctionDeclaration(
                name="search_apartments",
                description=(
                    "Search available apartments matching user preferences. "
                    "Always use max_rent_per_person_dollars (not total rent, not cents). "
                    "Pass num_people so the server computes the correct total."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "max_rent_per_person_dollars": {
                            "type": "NUMBER",
                            "description": (
                                "Maximum rent per person in US dollars (e.g. 1300 for $1,300/person). "
                                "Do NOT multiply by num_people — the server does that."
                            ),
                        },
                        "num_people": {
                            "type": "INTEGER",
                            "description": "Number of people sharing the apartment (default: same as bedrooms)",
                        },
                        "neighborhood":  {"type": "STRING",  "description": "Preferred neighborhood or borough, e.g. Brooklyn"},
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
            gt.FunctionDeclaration(
                name="create_housing_offer",
                description=(
                    "Post a room offer from someone who already has a place and wants a roommate. "
                    "ONLY call this after the user has explicitly confirmed all details. "
                    "Gather neighborhood, rent, date, smoking policy, and rooms_available first. "
                    "Rent is in US dollars per room per month — do NOT convert to cents."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Short listing title, e.g. 'Private room in Bushwick share'",
                        },
                        "neighborhood": {"type": "STRING", "description": "Brooklyn neighborhood or NYC area"},
                        "city":         {"type": "STRING", "description": "City (default: New York)"},
                        "rooms_available": {
                            "type": "INTEGER",
                            "description": "Number of rooms being offered (usually 1)",
                        },
                        "rent_per_room_dollars": {
                            "type": "NUMBER",
                            "description": "Monthly rent per room in US dollars (e.g. 1200 for $1,200/mo). Do NOT send cents.",
                        },
                        "available_from": {
                            "type": "STRING",
                            "description": "Move-in date as YYYY-MM-DD (fully resolved, no relative dates)",
                        },
                        "smoking_policy": {
                            "type": "STRING",
                            "description": "non_smoker | smoker | no_preference",
                        },
                        "description": {
                            "type": "STRING",
                            "description": "Optional free-text description of the room/apartment",
                        },
                        "owner_profile_id": {
                            "type": "STRING",
                            "description": f"Profile ID of the offer owner. For demo sessions use '{_DEMO_OWNER_PROFILE_ID}'.",
                        },
                    },
                    "required": [
                        "title", "neighborhood", "rooms_available",
                        "rent_per_room_dollars", "available_from",
                        "smoking_policy", "owner_profile_id",
                    ],
                },
            ),
            gt.FunctionDeclaration(
                name="search_room_offers",
                description="Search existing room offers from people who already have a place",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "neighborhood": {"type": "STRING", "description": "Neighborhood or borough"},
                        "max_rent_per_room_dollars": {
                            "type": "NUMBER",
                            "description": "Maximum monthly rent per room in US dollars",
                        },
                    },
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
                # BUG 2 FIX: normalize per-person dollars to total cents.
                # Gemini sends max_rent_per_person_dollars + num_people;
                # the search endpoint expects max_budget in cents (total).
                search_args = dict(args)
                per_person = search_args.pop("max_rent_per_person_dollars", None)
                num_people = search_args.pop("num_people", None)
                if per_person is not None:
                    bedrooms = search_args.get("bedrooms") or num_people or 1
                    people   = num_people or bedrooms
                    search_args["max_budget"] = int(float(per_person) * people * 100)
                r = await client.post(f"{base}/fairsplit/search", json=search_args)
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

            elif tool_name == "create_housing_offer":
                # BUG 2 pattern: normalize dollars → cents exactly once here
                dollars = args.get("rent_per_room_dollars")
                if dollars is None:
                    return {"error": "rent_per_room_dollars is required"}
                owner_id = args.get("owner_profile_id", _DEMO_OWNER_PROFILE_ID)
                payload = {
                    "title":               args.get("title", "Room available"),
                    "neighborhood":        args.get("neighborhood", ""),
                    "city":                args.get("city", "New York"),
                    "rooms_available":     args.get("rooms_available", 1),
                    "rent_per_room_cents": int(float(dollars) * 100),
                    "available_from":      args.get("available_from", ""),
                    "smoking_policy":      args.get("smoking_policy", "no_preference"),
                    "description":         args.get("description"),
                    "owner_profile_id":    owner_id,
                }
                r = await client.post(
                    f"{base}/fairsplit/offers",
                    json=payload,
                    headers={"X-Demo-Profile-Id": owner_id},
                )
                r.raise_for_status()
                return r.json()

            elif tool_name == "search_room_offers":
                params: dict = {}
                if args.get("neighborhood"):
                    params["neighborhood"] = args["neighborhood"]
                if args.get("max_rent_per_room_dollars"):
                    params["max_rent_per_room_cents"] = int(
                        float(args["max_rent_per_room_dollars"]) * 100
                    )
                r = await client.get(f"{base}/fairsplit/offers", params=params)
                r.raise_for_status()
                return {"offers": r.json()}

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
                    # BUG 3 FIX: do NOT send audio_stream_end — it permanently
                    # terminates Gemini's audio input for this session, preventing
                    # follow-up turns. Gemini's built-in VAD detects speech boundaries.
                    pass

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

    model = GEMINI_MODEL
    logger.info(
        f"[agent] Starting Gemini Live session  model={model}  "
        f"modalities=[AUDIO]  input_transcription=True  output_transcription=True"
    )
    await ws.send_json({"type": "status", "status": "connecting"})

    client = genai.Client(api_key=GEMINI_API_KEY)

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_PROMPT,
        tools=_make_tools(),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            logger.info(f"[agent] Session open  model={model}")
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
        logger.error(f"[agent] Session error  model={model}  error={err_str}")
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
