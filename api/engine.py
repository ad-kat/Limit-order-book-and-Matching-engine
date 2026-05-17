"""
engine.py — async subprocess bridge to the C++ LOB binary.

The C++ binary runs in interactive mode (no args):
  - prints  "READY"  on startup
  - reads one command per line from stdin
  - writes output lines ending with "OK" or "ERROR ..."
  - emits BOOK/TRADE lines before the terminal OK

This module owns the single long-lived subprocess and serializes all
commands through an asyncio Lock so concurrent HTTP requests don't
interleave writes/reads.
"""
from __future__ import annotations

import asyncio
import os
import re
import logging
from typing import Optional

from .models import TradeEvent, BookSnapshot

logger = logging.getLogger("lob.engine")

# Locate the compiled binary relative to the repo root
_BINARY_PATH = os.environ.get(
    "LOB_BINARY",
    os.path.join(os.path.dirname(__file__), "..", "build", "lob"),
)


class EngineError(RuntimeError):
    pass


class LOBEngine:
    """Async wrapper around the C++ LOB subprocess."""

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._ready = False

    async def start(self) -> None:
        """Spawn the C++ binary and wait for READY."""
        binary = os.path.abspath(_BINARY_PATH)
        if not os.path.isfile(binary):
            raise FileNotFoundError(
                f"LOB binary not found at {binary}. "
                "Run: cmake --build build --target lob"
            )

        self._proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for the READY line (timeout 5 s)
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=5.0)
        except asyncio.TimeoutError:
            raise EngineError("C++ engine did not send READY within 5 s")

        if line.decode().strip() != "READY":
            raise EngineError(f"Unexpected startup line: {line!r}")

        self._ready = True
        logger.info("C++ LOB engine started (pid=%d)", self._proc.pid)

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()
            await self._proc.wait()
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready and self._proc is not None and self._proc.returncode is None

    # ── low-level command runner ───────────────────────────────────────────────

    async def _send(self, cmd: str) -> list[str]:
        """
        Send one command line to the engine and collect all reply lines
        up to (and excluding) the terminal OK / ERROR line.
        Returns the list of output lines (without the terminal line).
        Raises EngineError on ERROR response or subprocess death.
        """
        if not self.is_ready:
            raise EngineError("Engine is not running")

        async with self._lock:
            self._proc.stdin.write((cmd + "\n").encode())
            await self._proc.stdin.drain()

            output_lines: list[str] = []
            while True:
                raw = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=3.0
                )
                if not raw:
                    raise EngineError("Engine process died unexpectedly")
                line = raw.decode().rstrip("\n")
                if line == "OK":
                    break
                if line.startswith("ERROR"):
                    raise EngineError(line[len("ERROR "):].strip())
                output_lines.append(line)

        return output_lines

    # ── parsers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_lines(lines: list[str]) -> tuple[list[TradeEvent], Optional[BookSnapshot]]:
        trades: list[TradeEvent] = []
        book: Optional[BookSnapshot] = None

        trade_re = re.compile(
            r"TRADE price=(\d+) qty=(\d+) buy=(\d+) sell=(\d+)"
        )
        book_re = re.compile(
            r"BOOK best_bid=(\S+) best_ask=(\S+)"
        )

        for line in lines:
            m = trade_re.match(line)
            if m:
                trades.append(TradeEvent(
                    price=int(m.group(1)),
                    qty=int(m.group(2)),
                    buy_id=int(m.group(3)),
                    sell_id=int(m.group(4)),
                ))
                continue
            m = book_re.match(line)
            if m:
                bid_raw, ask_raw = m.group(1), m.group(2)
                bid = int(bid_raw) if bid_raw != "none" else None
                ask = int(ask_raw) if ask_raw != "none" else None
                spread = (ask - bid) if (bid is not None and ask is not None) else None
                book = BookSnapshot(best_bid=bid, best_ask=ask, spread=spread)

        return trades, book

    # ── public API ────────────────────────────────────────────────────────────

    async def add_limit(
        self, order_id: int, side: str, price: int, qty: int
    ) -> tuple[list[TradeEvent], Optional[BookSnapshot]]:
        lines = await self._send(f"ADD {order_id} {side} {price} {qty}")
        return self._parse_lines(lines)

    async def add_market(
        self, order_id: int, side: str, qty: int
    ) -> tuple[list[TradeEvent], Optional[BookSnapshot]]:
        lines = await self._send(f"MARKET {order_id} {side} {qty}")
        return self._parse_lines(lines)

    async def cancel(self, order_id: int) -> tuple[bool, Optional[BookSnapshot]]:
        lines = await self._send(f"CANCEL {order_id}")
        _, book = self._parse_lines(lines)
        found = any("OK" in l for l in lines if l.startswith("CANCEL"))
        # also check for NOT_FOUND
        not_found = any("NOT_FOUND" in l for l in lines)
        return (not not_found), book

    async def status(self) -> Optional[BookSnapshot]:
        lines = await self._send("STATUS")
        _, book = self._parse_lines(lines)
        return book
