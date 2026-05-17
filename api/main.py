"""
main.py — FastAPI application for the C++ Limit Order Book engine.

Endpoints:
  GET  /health                  → engine health check
  GET  /book                    → current best bid/ask
  POST /orders/limit            → place a limit order
  POST /orders/market           → place a market order
  DELETE /orders/{order_id}     → cancel an order
  WS   /ws                      → real-time trade + book stream

Run locally:
  uvicorn api.main:app --reload --port 8000

Swagger UI: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .engine import LOBEngine, EngineError
from .models import (
    LimitOrderRequest,
    MarketOrderRequest,
    OrderResponse,
    CancelResponse,
    HealthResponse,
    BookSnapshot,
)
from .ws_manager import ConnectionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lob.api")

# ── Shared singletons ──────────────────────────────────────────────────────────
engine = LOBEngine()
ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the C++ engine on startup, shut it down on exit."""
    await engine.start()
    yield
    await engine.stop()


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Limit Order Book API",
    description=(
        "REST + WebSocket interface to a high-performance C++ matching engine. "
        "Supports limit orders, market orders, cancellations, and real-time "
        "trade/book streaming via WebSocket."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the React dashboard (any origin in dev; lock down in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _book_dict(book: BookSnapshot | None) -> dict:
    if book is None:
        return {"best_bid": None, "best_ask": None, "spread": None}
    return book.model_dump()


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["Meta"])
async def health():
    return HealthResponse(
        status="ok" if engine.is_ready else "degraded",
        engine="C++ LOB (interactive subprocess)",
    )


@app.get("/book", response_model=BookSnapshot, tags=["Book"])
async def get_book():
    """Return the current best bid and best ask."""
    try:
        book = await engine.status()
        return book or BookSnapshot()
    except EngineError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/orders/limit", response_model=OrderResponse, tags=["Orders"])
async def place_limit(req: LimitOrderRequest):
    """Place a limit order. Returns any trades that were immediately executed."""
    try:
        trades, book = await engine.add_limit(
            req.order_id, req.side, req.price, req.qty
        )
    except EngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Broadcast to WebSocket clients
    for t in trades:
        await ws_manager.broadcast("trade", t.model_dump())
    if book:
        await ws_manager.broadcast("book", _book_dict(book))

    return OrderResponse(
        status="ok",
        trades=trades,
        book=book,
    )


@app.post("/orders/market", response_model=OrderResponse, tags=["Orders"])
async def place_market(req: MarketOrderRequest):
    """Place a market order. Fills immediately against resting orders."""
    try:
        trades, book = await engine.add_market(req.order_id, req.side, req.qty)
    except EngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for t in trades:
        await ws_manager.broadcast("trade", t.model_dump())
    if book:
        await ws_manager.broadcast("book", _book_dict(book))

    return OrderResponse(
        status="ok",
        trades=trades,
        book=book,
    )


@app.delete("/orders/{order_id}", response_model=CancelResponse, tags=["Orders"])
async def cancel_order(order_id: int):
    """Cancel a resting limit order by ID."""
    try:
        found, book = await engine.cancel(order_id)
    except EngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if book:
        await ws_manager.broadcast("cancel", {"order_id": order_id, "book": _book_dict(book)})

    return CancelResponse(
        status="ok" if found else "not_found",
        order_id=order_id,
        book=book,
    )


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Real-time stream of trade and book events.

    Connect with any WS client:
      wscat -c ws://localhost:8000/ws

    Messages are JSON:
      {"event": "trade",  "payload": {"price": 101, "qty": 5, ...}}
      {"event": "book",   "payload": {"best_bid": 100, "best_ask": 101, "spread": 1}}
      {"event": "cancel", "payload": {"order_id": 42, "book": {...}}}
    """
    await ws_manager.connect(ws)
    # Send current book state on connect
    try:
        book = await engine.status()
        if book:
            await ws.send_json({"event": "book", "payload": _book_dict(book)})
    except Exception:
        pass

    try:
        while True:
            # Keep connection alive; clients can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
