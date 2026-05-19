"""
commentary.py — LLM commentary agent for the LOB engine.

Tries Gemini Flash first, falls back to Groq/Llama if Gemini fails.
Caches responses by market state fingerprint to avoid burning quota.

Cache key: symbol + price_bucket + spread_bucket + event + trade_bucket
TTL: 60s — commentary stays relevant for ~1 min
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("lob.commentary")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 60.0

_gemini_fail_count = 0
_gemini_fail_reset = 0.0
GEMINI_BACKOFF = 120.0


def _fingerprint(symbol, best_bid, best_ask, spread, last_event, trade_count):
    bid_bucket = round((best_bid or 0) / 50) * 50
    spread_bucket = round((spread or 0) / 10) * 10
    trade_bucket = min(trade_count // 3, 10)
    key = f"{symbol}|{bid_bucket}|{spread_bucket}|{last_event}|{trade_bucket}"
    return hashlib.md5(key.encode()).hexdigest()


def _cache_get(fp):
    if fp in _cache:
        text, ts = _cache[fp]
        if time.time() - ts < CACHE_TTL:
            return text
        del _cache[fp]
    return None


def _cache_set(fp, text):
    _cache[fp] = (text, time.time())


def _build_prompt(symbol, best_bid, best_ask, spread, last_event, trade_count, recent_trades):
    bid_str = f"${best_bid/100:.2f}" if best_bid else "none"
    ask_str = f"${best_ask/100:.2f}" if best_ask else "none"
    spread_str = f"${spread/100:.2f}" if spread else "unknown"
    lines = [f"  {t.get('side','?')} {t.get('qty','?')} @ ${t.get('price',0)/100:.2f}" for t in (recent_trades or [])[-3:]]
    trades_str = "\n".join(lines) if lines else "  none"
    return (
        f"You are a real-time market microstructure commentator.\n"
        f"Give ONE punchy sentence (max 20 words) about current order flow. "
        f"Use trading terminology. No bullets, no multiple sentences.\n\n"
        f"Symbol: {symbol}\nBest bid: {bid_str}  Best ask: {ask_str}  Spread: {spread_str}\n"
        f"Last event: {last_event}  Total trades: {trade_count}\nRecent trades:\n{trades_str}\n\nCommentary:"
    )


async def _try_gemini(prompt, api_key):
    global _gemini_fail_count, _gemini_fail_reset
    if _gemini_fail_count >= 3 and time.time() < _gemini_fail_reset:
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 60},
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(f"{GEMINI_URL}?key={api_key}", json=payload)
            if r.status_code == 200:
                _gemini_fail_count = 0
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
            _gemini_fail_count += 1
            _gemini_fail_reset = time.time() + GEMINI_BACKOFF
            logger.warning(f"[commentary] Gemini {r.status_code} — fail #{_gemini_fail_count}")
            return None
    except Exception as e:
        _gemini_fail_count += 1
        _gemini_fail_reset = time.time() + GEMINI_BACKOFF
        logger.warning(f"[commentary] Gemini error: {e}")
        return None


async def _try_groq(prompt, api_key):
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 60,
        "temperature": 0.7,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(GROQ_URL, json=payload, headers={"Authorization": f"Bearer {api_key}"})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip().strip('"')
            logger.warning(f"[commentary] Groq {r.status_code}")
            return None
    except Exception as e:
        logger.warning(f"[commentary] Groq error: {e}")
        return None


async def get_commentary(symbol, best_bid, best_ask, spread, last_event, trade_count, recent_trades):
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")

    if not gemini_key and not groq_key:
        return "Commentary unavailable: no API key set."

    fp = _fingerprint(symbol, best_bid, best_ask, spread, last_event, trade_count)
    cached = _cache_get(fp)
    if cached:
        logger.debug(f"[commentary] cache hit: {symbol}")
        return cached

    prompt = _build_prompt(symbol, best_bid, best_ask, spread, last_event, trade_count, recent_trades)

    text = None
    if gemini_key:
        text = await _try_gemini(prompt, gemini_key)
        if text:
            logger.info(f"[commentary] Gemini → {symbol}: {text}")

    if not text and groq_key:
        text = await _try_groq(prompt, groq_key)
        if text:
            logger.info(f"[commentary] Groq → {symbol}: {text}")

    if text:
        _cache_set(fp, text)
        return text

    return f"{symbol}: monitoring order flow."
