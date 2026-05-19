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

import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

import httpx
import yfinance as yf
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
from .commentary import get_commentary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lob.api")

# ── Shared singletons ──────────────────────────────────────────────────────────
engine = LOBEngine()
ws_manager = ConnectionManager()

TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]
FEED_SPEED = 0.15   # seconds between bars
_feed_order_id = 100_000

# ── Commentary state ───────────────────────────────────────────────────────────
_commentary_state: dict = {
    "current_symbol": "AAPL",
    "recent_trades": [],
    "trade_count": 0,
    "last_event": "init",
}
_last_commentary_time: float = 0.0
COMMENTARY_INTERVAL = 8.0  # seconds between commentary broadcasts


def to_cents(price: float) -> int:
    return max(1, int(round(price * 100)))


async def _maybe_broadcast_commentary(book, event_type: str):
    """Fire commentary if enough time has passed since last broadcast."""
    global _last_commentary_time
    now = time.time()
    if now - _last_commentary_time < COMMENTARY_INTERVAL:
        return
    if not book:
        return
    _last_commentary_time = now
    state = _commentary_state
    try:
        text = await get_commentary(
            symbol=state["current_symbol"],
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            spread=book.spread,
            last_event=event_type,
            trade_count=state["trade_count"],
            recent_trades=state["recent_trades"][-5:],
        )
        await ws_manager.broadcast("commentary", {
            "symbol": state["current_symbol"],
            "text": text,
            "event": event_type,
        })
    except Exception as e:
        logger.warning(f"[commentary] broadcast failed: {e}")


async def _place_limit(side: str, price_cents: int, qty: int) -> dict:
    global _feed_order_id
    _feed_order_id += 1
    trades, book = await engine.add_limit(_feed_order_id, side, price_cents, qty)
    for t in trades:
        td = t.model_dump()
        await ws_manager.broadcast("trade", td)
        _commentary_state["recent_trades"].append(td)
        _commentary_state["recent_trades"] = _commentary_state["recent_trades"][-20:]
        _commentary_state["trade_count"] += 1
    if book:
        await ws_manager.broadcast("book", _book_dict(book))
        await _maybe_broadcast_commentary(book, "limit")
    return {"trades": trades, "book": book}


async def _place_market(side: str, qty: int) -> dict:
    global _feed_order_id
    _feed_order_id += 1
    trades, book = await engine.add_market(_feed_order_id, side, qty)
    for t in trades:
        td = t.model_dump()
        await ws_manager.broadcast("trade", td)
        _commentary_state["recent_trades"].append(td)
        _commentary_state["recent_trades"] = _commentary_state["recent_trades"][-20:]
        _commentary_state["trade_count"] += 1
    if book:
        await ws_manager.broadcast("book", _book_dict(book))
        await _maybe_broadcast_commentary(book, "market_order")
    return {"trades": trades, "book": book}


async def _cancel_feed(order_id: int):
    try:
        found, book = await engine.cancel(order_id)
        if book:
            await ws_manager.broadcast("cancel", {"order_id": order_id, "book": _book_dict(book)})
    except Exception:
        pass


async def _replay_ticker(ticker: str, resting: list) -> None:
    global _feed_order_id
    logger.info(f"[feed] Fetching {ticker} bars...")
    try:
        hist = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yf.Ticker(ticker).history(period="5d", interval="1m")
        )
    except Exception as e:
        logger.warning(f"[feed] yfinance error: {e}")
        return

    if hist.empty:
        logger.warning(f"[feed] No data for {ticker}")
        return

    avg_vol = hist["Volume"].mean()
    logger.info(f"[feed] Replaying {len(hist)} bars for {ticker}")

    for ts, row in hist.iterrows():
        o, h, l, c, vol = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        mid = to_cents(c)
        bid = to_cents(l)
        ask = to_cents(h)
        if ask - bid < 2:
            bid, ask = mid - 1, mid + 1

        qty_base = max(1, int(vol / avg_vol * 10))

        # Cancel ~20% of resting orders
        to_cancel = [oid for oid in resting if random.random() < 0.20]
        for oid in to_cancel:
            await _cancel_feed(oid)
            resting.remove(oid)

        # Resting SELL limit
        try:
            res = await _place_limit("SELL", ask, qty_base)
            if not res["trades"]:
                resting.append(_feed_order_id)
        except Exception as e:
            logger.debug(f"[feed] limit err: {e}")

        # Resting BUY limit
        try:
            res = await _place_limit("BUY", bid, qty_base)
            if not res["trades"]:
                resting.append(_feed_order_id)
        except Exception as e:
            logger.debug(f"[feed] limit err: {e}")

        # Volume spike → market order
        if vol > avg_vol * 1.5:
            side = "BUY" if c > o else "SELL"
            try:
                res = await _place_market(side, max(1, qty_base // 2))
                logger.info(f"[feed] {ticker} SPIKE {side} → {len(res['trades'])} trade(s)")
            except Exception as e:
                logger.debug(f"[feed] market err: {e}")

        # Keep order_id bounded
        if _feed_order_id > 900_000:
            _feed_order_id = 100_000

        await asyncio.sleep(FEED_SPEED)


async def market_feed_loop():
    """Background task: loops through tickers forever."""
    await asyncio.sleep(5)  # wait for engine to be ready
    resting: list[int] = []
    iteration = 0
    while True:
        iteration += 1
        logger.info(f"[feed] === Cycle {iteration} ===")
        for ticker in TICKERS:
            try:
                _commentary_state["current_symbol"] = ticker
                _commentary_state["trade_count"] = 0
                _commentary_state["recent_trades"] = []
                await _replay_ticker(ticker, resting)
            except Exception as e:
                logger.warning(f"[feed] ticker error: {e}")
        logger.info("[feed] Cycle done. Sleeping 30s...")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the C++ engine and market feed on startup."""
    await engine.start()
    feed_task = asyncio.create_task(market_feed_loop())
    yield
    feed_task.cancel()
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
    try:
        book = await engine.status()
        return book or BookSnapshot()
    except EngineError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/orders/limit", response_model=OrderResponse, tags=["Orders"])
async def place_limit(req: LimitOrderRequest):
    try:
        trades, book = await engine.add_limit(req.order_id, req.side, req.price, req.qty)
    except EngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for t in trades:
        await ws_manager.broadcast("trade", t.model_dump())
    if book:
        await ws_manager.broadcast("book", _book_dict(book))

    return OrderResponse(status="ok", trades=trades, book=book)


@app.post("/orders/market", response_model=OrderResponse, tags=["Orders"])
async def place_market(req: MarketOrderRequest):
    try:
        trades, book = await engine.add_market(req.order_id, req.side, req.qty)
    except EngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for t in trades:
        await ws_manager.broadcast("trade", t.model_dump())
    if book:
        await ws_manager.broadcast("book", _book_dict(book))

    return OrderResponse(status="ok", trades=trades, book=book)


@app.delete("/orders/{order_id}", response_model=CancelResponse, tags=["Orders"])
async def cancel_order(order_id: int):
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
    await ws_manager.connect(ws)
    try:
        book = await engine.status()
        if book:
            await ws.send_json({"event": "book", "payload": _book_dict(book)})
    except Exception:
        pass

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)