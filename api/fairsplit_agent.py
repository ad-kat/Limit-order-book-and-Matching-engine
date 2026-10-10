"""
fairsplit_agent.py — Gemini Live voice agent WebSocket proxy.

Client connects to /fairsplit/agent WebSocket.
Protocol (client → server):
  - Raw base64 audio chunks (string)
  - JSON: {"type": "text", "text": "..."}  for text input
  - JSON: {"type": "end_audio"}             to signal end of speech turn

Protocol (server → client):
  - {"type": "transcript", "role": "user"|"model", "text": "..."}
  - {"type": "tool_call", "tool": "...", "args": {...}, "result": {...}}
  - {"type": "audio", "data": "<base64>"}
  - {"type": "error", "message": "..."}
  - {"type": "status", "status": "connecting"|"connected"|"listening"|"idle"}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("fairsplit.agent")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.0-flash-live-001"
GEMINI_FALLBACK = "gemini-2.0-flash-exp"

SYSTEM_PROMPT = (
    "You are FairSplit, an AI assistant for finding roommates and shared apartments. "
    "Help users find compatible roommates and apartment groups. "
    "Be friendly, concise, and proactive in suggesting compatible roommates. "
    "When users describe their housing needs, use the available tools to search for "
    "apartments and find compatible roommate groups."
)

TOOLS_SPEC = [
    {
        "name": "search_apartments",
        "description": "Search for available apartments matching user preferences",
        "parameters": {
            "type": "object",
            "properties": {
                "max_budget": {"type": "integer", "description": "Max monthly rent in cents"},
                "neighborhood": {"type": "string", "description": "Preferred neighborhood"},
                "bedrooms": {"type": "integer", "description": "Number of bedrooms"},
            },
        },
    },
    {
        "name": "find_compatible_roommates",
        "description": "Find compatible roommate groups for an apartment",
        "parameters": {
            "type": "object",
            "properties": {
                "apartment_id": {"type": "string", "description": "Apartment UUID"},
                "candidate_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of candidate profile IDs",
                },
            },
            "required": ["apartment_id"],
        },
    },
    {
        "name": "propose_roommate_group",
        "description": "Create a new roommate group for an apartment",
        "parameters": {
            "type": "object",
            "properties": {
                "apartment_id": {"type": "string"},
                "created_by": {"type": "string", "description": "Profile ID of proposer"},
                "member_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Profile IDs of additional members to invite",
                },
            },
            "required": ["apartment_id", "created_by"],
        },
    },
    {
        "name": "get_group_status",
        "description": "Get the current status of a roommate group",
        "parameters": {
            "type": "object",
            "properties": {"group_id": {"type": "string"}},
            "required": ["group_id"],
        },
    },
    {
        "name": "create_group_invitation",
        "description": "Invite someone to join an existing roommate group",
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {"type": "string"},
                "inviter_profile_id": {"type": "string"},
                "invitee_profile_id": {"type": "string"},
            },
            "required": ["group_id", "inviter_profile_id", "invitee_profile_id"],
        },
    },
]


# ── Internal API calls ─────────────────────────────────────────────────────────

async def _call_internal(tool_name: str, args: dict) -> dict:
    """Call the corresponding FastAPI endpoint internally."""
    try:
        import httpx
        base = os.getenv("INTERNAL_API_URL", "http://localhost:8000")

        async with httpx.AsyncClient(timeout=10.0) as client:
            if tool_name == "search_apartments":
                r = await client.post(f"{base}/fairsplit/search", json=args)
                return {"apartments": r.json()}

            elif tool_name == "find_compatible_roommates":
                r = await client.post(f"{base}/fairsplit/match", json=args)
                return r.json()

            elif tool_name == "propose_roommate_group":
                r = await client.post(f"{base}/fairsplit/groups", json=args)
                return r.json()

            elif tool_name == "get_group_status":
                gid = args.get("group_id", "")
                r = await client.get(f"{base}/fairsplit/groups/{gid}")
                return r.json()

            elif tool_name == "create_group_invitation":
                gid = args.get("group_id", "")
                r = await client.post(f"{base}/fairsplit/groups/{gid}/invite", json=args)
                return r.json()

            else:
                return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.warning(f"[agent] internal API call failed: {e}")
        return {"error": str(e)}


# ── Text-based fallback session (no Gemini key) ─────────────────────────────────

async def _text_fallback_session(ws: WebSocket):
    """Simple rule-based fallback when GEMINI_API_KEY is not set."""
    await ws.send_json({"type": "status", "status": "connected"})
    await ws.send_json({
        "type": "transcript",
        "role": "model",
        "text": "Hi! I'm FairSplit. I can help you find apartments and roommates. "
                "Try asking: 'Find 3-bedroom apartments in Brooklyn' or "
                "'Find roommates for apartment apt-brooklyn-3br-001'.",
    })

    while True:
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            break
        try:
            msg = json.loads(raw)
            if msg.get("type") == "text":
                text = msg.get("text", "").lower()
                await ws.send_json({
                    "type": "transcript",
                    "role": "user",
                    "text": msg.get("text", ""),
                })

                # Simple keyword routing
                if "brooklyn" in text or "apartment" in text or "find" in text:
                    args = {}
                    if "brooklyn" in text:
                        args["neighborhood"] = "Brooklyn"
                    result = await _call_internal("search_apartments", args)
                    apts = result.get("apartments", [])[:3]
                    reply = f"I found {len(apts)} apartments."
                    if apts:
                        names = [a.get("title", a.get("id", "?")) for a in apts]
                        reply += " For example: " + ", ".join(names[:3]) + "."
                    await ws.send_json({
                        "type": "tool_call",
                        "tool": "search_apartments",
                        "args": args,
                        "result": result,
                    })
                    await ws.send_json({"type": "transcript", "role": "model", "text": reply})

                elif "roommate" in text or "match" in text:
                    apt_id = "apt-brooklyn-3br-001"
                    result = await _call_internal("find_compatible_roommates",
                                                   {"apartment_id": apt_id})
                    groups = result.get("top_groups", [])
                    reply = (
                        f"For the Park Slope 3BR (${result.get('per_person_rent',0)//100}/person), "
                        f"I found {len(groups)} compatible group(s)."
                    )
                    if groups:
                        first = groups[0]
                        names = [m.get("display_name", "?") for m in first.get("members", [])]
                        reply += f" Best match: {', '.join(names)}."
                    await ws.send_json({
                        "type": "tool_call",
                        "tool": "find_compatible_roommates",
                        "args": {"apartment_id": apt_id},
                        "result": result,
                    })
                    await ws.send_json({"type": "transcript", "role": "model", "text": reply})

                else:
                    await ws.send_json({
                        "type": "transcript",
                        "role": "model",
                        "text": "I can help you search for apartments or find compatible roommates. "
                                "What are you looking for?",
                    })

            elif msg.get("type") == "end_audio":
                await ws.send_json({
                    "type": "transcript",
                    "role": "model",
                    "text": "Voice input requires a GEMINI_API_KEY. "
                            "Please use the text input for now.",
                })
        except (json.JSONDecodeError, KeyError):
            pass


# ── Gemini Live session ────────────────────────────────────────────────────────

async def _gemini_live_session(ws: WebSocket):
    """Full Gemini Live API proxy with tool calling."""
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        logger.error("[agent] google-genai not installed; pip install google-genai>=1.0.0")
        await ws.send_json({"type": "error", "message": "google-genai package not installed"})
        return

    await ws.send_json({"type": "status", "status": "connecting"})

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Build tools list
    function_declarations = []
    for t in TOOLS_SPEC:
        function_declarations.append(
            gtypes.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t.get("parameters", {}),
            )
        )
    tools = [gtypes.Tool(function_declarations=function_declarations)]

    config = gtypes.LiveConnectConfig(
        response_modalities=["AUDIO", "TEXT"],
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
    )

    try:
        model_name = GEMINI_MODEL
        try:
            async with client.aio.live.connect(model=model_name, config=config) as session:
                await ws.send_json({"type": "status", "status": "connected"})
                await _run_live_session(ws, session)
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                # Try fallback model
                async with client.aio.live.connect(model=GEMINI_FALLBACK, config=config) as session:
                    await ws.send_json({"type": "status", "status": "connected"})
                    await _run_live_session(ws, session)
            else:
                raise
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[agent] Gemini Live error: {e}")
        await ws.send_json({"type": "error", "message": str(e)})


async def _run_live_session(ws: WebSocket, session):
    """Run the bidirectional Gemini Live session."""
    async def send_to_gemini():
        """Forward client messages to Gemini."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "text":
                        await session.send(input=msg["text"], end_of_turn=True)
                        await ws.send_json({
                            "type": "transcript",
                            "role": "user",
                            "text": msg["text"],
                        })
                    elif msg.get("type") == "end_audio":
                        await session.send(end_of_turn=True)
                    # else treat as raw base64 audio
                except json.JSONDecodeError:
                    # Raw base64 audio chunk
                    audio_bytes = base64.b64decode(raw)
                    await session.send(
                        input={"mime_type": "audio/pcm", "data": audio_bytes}
                    )
        except WebSocketDisconnect:
            pass

    async def recv_from_gemini():
        """Forward Gemini responses to client."""
        try:
            async for response in session.receive():
                # Text / transcript
                if hasattr(response, "text") and response.text:
                    await ws.send_json({
                        "type": "transcript",
                        "role": "model",
                        "text": response.text,
                    })

                # Audio
                if hasattr(response, "data") and response.data:
                    await ws.send_json({
                        "type": "audio",
                        "data": base64.b64encode(response.data).decode(),
                    })

                # Tool calls
                if hasattr(response, "tool_call") and response.tool_call:
                    for fc in response.tool_call.function_calls:
                        args = dict(fc.args) if fc.args else {}
                        result = await _call_internal(fc.name, args)
                        await ws.send_json({
                            "type": "tool_call",
                            "tool": fc.name,
                            "args": args,
                            "result": result,
                        })
                        # Send tool result back to Gemini
                        await session.send(
                            input=gtypes.LiveClientToolResponse(
                                function_responses=[
                                    gtypes.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response={"result": result},
                                    )
                                ]
                            )
                        )
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"[agent] recv error: {e}")

    await asyncio.gather(send_to_gemini(), recv_from_gemini())


# ── Main WebSocket handler ─────────────────────────────────────────────────────

async def agent_websocket_handler(ws: WebSocket):
    """Entry point called from the FastAPI router."""
    await ws.accept()

    if not GEMINI_API_KEY:
        logger.warning("[agent] GEMINI_API_KEY not configured; using text fallback")
        await ws.send_json({
            "type": "error",
            "message": "GEMINI_API_KEY not configured — voice disabled, text input available",
        })
        await _text_fallback_session(ws)
        return

    await _gemini_live_session(ws)
