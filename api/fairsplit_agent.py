"""
fairsplit_agent.py — Gemini Live voice agent WebSocket proxy.

google-genai 2.29.0 / Gemini Live API (Oct 2026).

Model: $GEMINI_LIVE_MODEL (default: gemini-3.8-live)
Audio in:  PCM 16-bit LE, 16 kHz, mono  (mime: audio/pcm;rate=16000)
Audio out: PCM 16-bit LE, 24 kHz, mono  (mime: audio/pcm;rate=24000)

Architecture:
  Browser <--WS--> FastAPI handler
    _send_loop   — browser → Gemini write queue
    _recv_loop   — Gemini → browser, also pushes tool responses to write queue
    _writer_loop — single serialized consumer of write queue → Gemini

All sends to Gemini go through the write queue to prevent concurrent-send
races that cause the session to silently hang after tool calls.

Client → server WebSocket messages (JSON):
  {"type":"text","text":"..."}           — text turn
  {"type":"audio_chunk","data":"<b64>"}  — PCM16 audio (16 kHz)
  {"type":"activity_start"}             — user began speaking
  {"type":"activity_end"}               — user stopped speaking (Gemini may respond)
  {"type":"ping"}                        — keepalive (ignored)

Server → client WebSocket messages (JSON):
  {"type":"status",     "status":"connecting"|"connected"|"idle"|"error"}
  {"type":"transcript", "role":"user"|"model", "text":"..."}
  {"type":"audio",      "data":"<b64 PCM 24 kHz>", "mime":"audio/pcm;rate=24000"}
  {"type":"tool_call",  "tool":"...", "args":{...}, "result":{...}}
  {"type":"interrupted"}                — Gemini interrupted its own output
  {"type":"turn_complete"}              — Gemini finished a turn
  {"type":"error",      "message":"..."}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("fairsplit.agent")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Read GEMINI_LIVE_MODEL first; never fall back to a non-live GEMINI_MODEL.
GEMINI_MODEL = os.getenv("GEMINI_LIVE_MODEL") or "models/gemini-2.5-flash-native-audio-latest"

_DEMO_OWNER_PROFILE_ID = "profile-alex-001"

SYSTEM_PROMPT = (
    "You are FairSplit, an AI assistant helping students find compatible roommates "
    "and shared apartments in New York City. "
    "Be warm, concise, and proactive. "
    "When a user describes housing needs, use the available tools to search apartments "
    "and find compatible roommate groups. "
    "Always confirm before creating a group invitation. "
    "After any tool call, immediately summarize the result in spoken audio for the user. "
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


# ── Tool declarations ──────────────────────────────────────────────────────────

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
                        "neighborhood": {"type": "STRING", "description": "Preferred neighborhood or borough, e.g. Brooklyn"},
                        "bedrooms":     {"type": "INTEGER", "description": "Number of bedrooms"},
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
                        "title":           {"type": "STRING"},
                        "neighborhood":    {"type": "STRING"},
                        "city":            {"type": "STRING"},
                        "rooms_available": {"type": "INTEGER"},
                        "rent_per_room_dollars": {
                            "type": "NUMBER",
                            "description": "Monthly rent per room in US dollars. Do NOT send cents.",
                        },
                        "available_from":  {"type": "STRING", "description": "YYYY-MM-DD"},
                        "smoking_policy":  {"type": "STRING", "description": "non_smoker | smoker | no_preference"},
                        "description":     {"type": "STRING"},
                        "owner_profile_id": {
                            "type": "STRING",
                            "description": f"For demo sessions use '{_DEMO_OWNER_PROFILE_ID}'.",
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
                        "neighborhood": {"type": "STRING"},
                        "max_rent_per_room_dollars": {"type": "NUMBER"},
                    },
                },
            ),
        ])
    ]


# ── Internal tool dispatch ─────────────────────────────────────────────────────

def _trim_result(result: dict, tool_name: str) -> dict:
    """Keep only essential fields in tool results to avoid oversized FunctionResponses."""
    if tool_name == "search_apartments":
        apts = result.get("apartments", [])[:5]
        trimmed = []
        for a in apts:
            trimmed.append({
                "id":           a.get("id", ""),
                "title":        a.get("title", ""),
                "neighborhood": a.get("neighborhood", ""),
                "bedrooms":     a.get("bedrooms"),
                "per_person_rent_dollars": round(a.get("per_person_rent", 0) / 100, 2),
                "available_from": a.get("available_from", ""),
            })
        return {"apartments": trimmed, "count": len(trimmed)}
    if tool_name == "find_compatible_roommates":
        groups = result.get("top_groups", [])[:3]
        trimmed = []
        for g in groups:
            members = [{"display_name": m.get("display_name", ""), "id": m.get("id", "")}
                       for m in g.get("members", [])]
            trimmed.append({
                "members": members,
                "score":   round(g.get("score", 0), 1),
                "explanation": g.get("explanation", "")[:200],
            })
        return {
            "top_groups":      trimmed,
            "per_person_rent_dollars": round(result.get("per_person_rent", 0) / 100, 2),
        }
    return result


async def _call_internal(tool_name: str, args: dict) -> dict:
    import httpx
    base = os.getenv("INTERNAL_API_URL", "http://localhost:8000")
    t0 = time.monotonic()
    logger.info(f"[tool] http_start  tool={tool_name}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if tool_name == "search_apartments":
                search_args = dict(args)
                per_person = search_args.pop("max_rent_per_person_dollars", None)
                num_people = search_args.pop("num_people", None)
                if per_person is not None:
                    bedrooms = search_args.get("bedrooms") or num_people or 1
                    people   = num_people or bedrooms
                    search_args["max_budget"] = int(float(per_person) * people * 100)
                r = await client.post(f"{base}/fairsplit/search", json=search_args)
                r.raise_for_status()
                result = {"apartments": r.json()}

            elif tool_name == "find_compatible_roommates":
                r = await client.post(f"{base}/fairsplit/match", json=args)
                r.raise_for_status()
                result = r.json()

            elif tool_name == "propose_roommate_group":
                r = await client.post(f"{base}/fairsplit/groups", json=args)
                r.raise_for_status()
                result = r.json()

            elif tool_name == "get_group_status":
                r = await client.get(f"{base}/fairsplit/groups/{args.get('group_id','')}")
                r.raise_for_status()
                result = r.json()

            elif tool_name == "create_group_invitation":
                gid = args.get("group_id", "")
                r = await client.post(f"{base}/fairsplit/groups/{gid}/invite", json=args)
                r.raise_for_status()
                result = r.json()

            elif tool_name == "create_housing_offer":
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
                    f"{base}/fairsplit/offers", json=payload,
                    headers={"X-Demo-Profile-Id": owner_id},
                )
                r.raise_for_status()
                result = r.json()

            elif tool_name == "search_room_offers":
                params: dict = {}
                if args.get("neighborhood"):
                    params["neighborhood"] = args["neighborhood"]
                if args.get("max_rent_per_room_dollars"):
                    params["max_rent_per_room_cents"] = int(float(args["max_rent_per_room_dollars"]) * 100)
                r = await client.get(f"{base}/fairsplit/offers", params=params)
                r.raise_for_status()
                result = {"offers": r.json()}

            else:
                result = {"error": f"Unknown tool: {tool_name}"}

        elapsed = time.monotonic() - t0
        logger.info(f"[tool] http_done   tool={tool_name}  status={r.status_code}  elapsed={elapsed:.3f}s")
        return result

    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.warning(f"[tool] http_error  tool={tool_name}  elapsed={elapsed:.3f}s  error={e}")
        return {"error": str(e)}


# ── Text fallback (no GEMINI_API_KEY) ─────────────────────────────────────────

async def _text_fallback_session(ws: WebSocket):
    await ws.send_json({"type": "status", "status": "connected"})
    await ws.send_json({
        "type": "transcript", "role": "model",
        "text": "Hi! I'm FairSplit (demo mode — no Gemini key configured). "
                "Type 'Find apartments in Brooklyn' or 'Find roommates' to try the API.",
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
            reply = "I can search apartments or find roommates. What would you like?"
        await ws.send_json({"type": "transcript", "role": "model", "text": reply})


# ── Gemini write queue writer ──────────────────────────────────────────────────
#
# All sends to Gemini are serialized through a single asyncio.Queue.
# This prevents concurrent-send races between _send_loop (forwarding
# browser audio) and _recv_loop (sending tool responses), which caused
# the session to silently hang after tool calls.

_WRITER_SENTINEL = None

async def _writer_loop(session, queue: asyncio.Queue):
    """Drain the Gemini write queue — only task that calls session.send_*."""
    from google.genai import types as gt
    while True:
        item = await queue.get()
        if item is _WRITER_SENTINEL:
            queue.task_done()
            break
        cmd, payload = item
        try:
            t0 = time.monotonic()
            if cmd == "audio":
                # Use media= (primary documented parameter) instead of audio=
                await session.send_realtime_input(media=payload)
            elif cmd == "text":
                await session.send_client_content(**payload)
            elif cmd == "tool_response":
                logger.info(f"[tool] send_tool_response_start  id={payload.get('id')}")
                await session.send_tool_response(**payload)
                logger.info(f"[tool] send_tool_response_done   elapsed={time.monotonic()-t0:.3f}s")
            elif cmd == "activity_start":
                await session.send_realtime_input(activity_start=gt.ActivityStart())
            elif cmd == "activity_end":
                await session.send_realtime_input(activity_end=gt.ActivityEnd())
        except Exception as e:
            logger.warning(f"[writer] cmd={cmd} error: {e}")
        finally:
            queue.task_done()


# ── Gemini receive loop ────────────────────────────────────────────────────────

async def _recv_loop(ws: WebSocket, session, queue: asyncio.Queue):
    """Read Gemini messages; forward audio/transcripts; push tool responses to queue."""
    from google.genai import types as gt
    audio_chunks_fwd = 0
    try:
        async for msg in session.receive():
            sc = msg.server_content
            if sc:
                if getattr(sc, "interrupted", False):
                    logger.info("[recv] interrupted")
                    await ws.send_json({"type": "interrupted"})

                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            audio_chunks_fwd += 1
                            encoded = base64.b64encode(part.inline_data.data).decode()
                            logger.debug(
                                f"[recv] audio_chunk #{audio_chunks_fwd}  "
                                f"bytes={len(part.inline_data.data)}"
                            )
                            await ws.send_json({
                                "type": "audio",
                                "data": encoded,
                                "mime": part.inline_data.mime_type or "audio/pcm;rate=24000",
                            })
                        if part.text and not getattr(part, "thought", False):
                            pass  # text parts covered by transcription below

                if sc.output_transcription and sc.output_transcription.text:
                    await ws.send_json({
                        "type": "transcript", "role": "model",
                        "text": sc.output_transcription.text,
                    })

                if sc.input_transcription and sc.input_transcription.text:
                    await ws.send_json({
                        "type": "transcript", "role": "user",
                        "text": sc.input_transcription.text,
                    })

                if getattr(sc, "turn_complete", False):
                    logger.info(f"[recv] turn_complete  audio_chunks_fwd={audio_chunks_fwd}")
                    await ws.send_json({"type": "turn_complete"})
                    audio_chunks_fwd = 0  # reset per turn

                if getattr(sc, "go_away", None):
                    logger.warning("[recv] go_away received — Gemini closing session")
                    break

            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    fc_args = dict(fc.args) if fc.args else {}
                    logger.info(f"[tool] tool_call_received  name={fc.name}  id={fc.id}  args_keys={list(fc_args.keys())}")

                    result = await _call_internal(fc.name, fc_args)
                    trimmed = _trim_result(result, fc.name)

                    # Notify browser
                    try:
                        await ws.send_json({
                            "type": "tool_call", "tool": fc.name,
                            "args": fc_args, "result": trimmed,
                        })
                    except Exception:
                        pass

                    # Serialize tool response through write queue — do NOT call
                    # session.send_tool_response directly (would race with audio sends)
                    logger.info(f"[tool] queuing_tool_response  name={fc.name}  id={fc.id}")
                    fr_kwargs = {
                        "function_responses": [
                            gt.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response={"result": trimmed},
                            )
                        ]
                    }
                    await queue.put(("tool_response", fr_kwargs))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[recv] error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # Signal writer to stop
        await queue.put(_WRITER_SENTINEL)


# ── Browser → Gemini send loop ────────────────────────────────────────────────

async def _send_loop(ws: WebSocket, queue: asyncio.Queue):
    """Forward browser WebSocket messages to the Gemini write queue."""
    from google.genai import types as gt
    try:
        while True:
            raw = await ws.receive()
            if "text" in raw:
                data = raw["text"]
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    # Treat as raw base64 audio
                    audio_bytes = base64.b64decode(data)
                    if audio_bytes:
                        await queue.put(("audio", gt.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")))
                    continue

                mtype = msg.get("type")

                if mtype == "text":
                    await queue.put(("text", {
                        "turns": gt.Content(role="user", parts=[gt.Part(text=msg["text"])]),
                        "turn_complete": True,
                    }))

                elif mtype == "audio_chunk":
                    audio_bytes = base64.b64decode(msg["data"])
                    if audio_bytes:
                        await queue.put(("audio", gt.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")))

                elif mtype == "activity_start":
                    logger.info("[send] activity_start from browser")
                    await queue.put(("activity_start", None))

                elif mtype == "activity_end":
                    logger.info("[send] activity_end from browser")
                    await queue.put(("activity_end", None))

                elif mtype in ("end_audio", "ping"):
                    pass  # ignored — VAD handles turn boundaries

            elif "bytes" in raw:
                if raw["bytes"]:
                    await queue.put(("audio", gt.Blob(data=raw["bytes"], mime_type="audio/pcm;rate=16000")))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[send] error: {e}")
    finally:
        # Signal writer to stop (in case recv_loop already did, this is a no-op)
        await queue.put(_WRITER_SENTINEL)


# ── Main Gemini Live session ───────────────────────────────────────────────────

async def _gemini_live_session(ws: WebSocket):
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        await ws.send_json({"type": "error", "message": "google-genai not installed"})
        return

    model = GEMINI_MODEL
    logger.info(f"[agent] session_start  model={model}  modalities=[AUDIO]  transcription=input+output")
    await ws.send_json({"type": "status", "status": "connecting"})

    client = genai.Client(api_key=GEMINI_API_KEY)

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_PROMPT,
        tools=_make_tools(),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
    )

    write_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            logger.info(f"[agent] session_open  model={model}")
            await ws.send_json({"type": "status", "status": "connected"})

            # Run three tasks concurrently:
            # 1. _send_loop:   browser → write queue
            # 2. _recv_loop:   Gemini → browser (tool responses → write queue)
            # 3. _writer_loop: write queue → Gemini (serialized, no races)
            results = await asyncio.gather(
                _send_loop(ws, write_queue),
                _recv_loop(ws, session, write_queue),
                _writer_loop(session, write_queue),
                return_exceptions=True,
            )
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.warning(f"[agent] task {i} exited with exception: {r}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        err_str = str(e)
        logger.error(f"[agent] session_error  model={model}  error={err_str}")
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
