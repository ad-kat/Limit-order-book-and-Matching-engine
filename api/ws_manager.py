"""
ws_manager.py — WebSocket connection manager.

All connected clients receive every trade and book-update event
broadcast by the REST handlers in real time.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("lob.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        logger.info("WS client connected  (total=%d)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients = [c for c in self._clients if c is not ws]
        logger.info("WS client disconnected (total=%d)", len(self._clients))

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        """Send a JSON message to all connected clients."""
        msg = json.dumps({"event": event, "payload": payload})
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        # Clean up closed sockets
        if dead:
            async with self._lock:
                self._clients = [c for c in self._clients if c not in dead]
