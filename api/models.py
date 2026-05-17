"""Pydantic request/response models."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────

class LimitOrderRequest(BaseModel):
    order_id: int = Field(..., gt=0, description="Unique order ID (positive integer)")
    side: Literal["BUY", "SELL"]
    price: int = Field(..., gt=0, description="Limit price (positive integer, e.g. cents)")
    qty: int = Field(..., gt=0, description="Order quantity")


class MarketOrderRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    side: Literal["BUY", "SELL"]
    qty: int = Field(..., gt=0)


# ── Responses ─────────────────────────────────────────────────────────────────

class TradeEvent(BaseModel):
    price: int
    qty: int
    buy_id: int
    sell_id: int


class BookSnapshot(BaseModel):
    best_bid: Optional[int] = None
    best_ask: Optional[int] = None
    spread: Optional[int] = None   # best_ask - best_bid, None if either side is empty


class OrderResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str = ""
    trades: list[TradeEvent] = []
    book: Optional[BookSnapshot] = None


class CancelResponse(BaseModel):
    status: Literal["ok", "not_found", "error"]
    order_id: int
    book: Optional[BookSnapshot] = None


class HealthResponse(BaseModel):
    status: str
    engine: str


# ── WebSocket broadcast payload ───────────────────────────────────────────────

class WsMessage(BaseModel):
    event: Literal["trade", "book", "cancel", "error"]
    payload: dict
