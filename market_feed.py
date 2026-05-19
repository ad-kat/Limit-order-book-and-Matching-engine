"""
market_feed.py — Real market data ingestion for the LOB engine.

Fetches real OHLCV data from Yahoo Finance (yfinance, free, no API key).
Converts each bar into realistic limit + market orders.
Feeds them to the running FastAPI server (POST /orders/limit etc).

Run locally:
  python3 market_feed.py --ticker AAPL --speed 0.2
  python3 market_feed.py --ticker AAPL --speed 0.05 --api-url https://your-railway-url.up.railway.app

Railway worker: set API_URL env var, runs with --loop flag forever.
"""

import argparse
import time
import random
import requests
import yfinance as yf
import os

session = requests.Session()

TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]


def to_cents(price: float) -> int:
    return max(1, int(round(price * 100)))


def place_limit(api, order_id, side, price_cents, qty):
    r = session.post(f"{api}/orders/limit", json={
        "order_id": order_id, "side": side, "price": price_cents, "qty": qty,
    }, timeout=5)
    return r.json()


def place_market(api, order_id, side, qty):
    r = session.post(f"{api}/orders/market", json={
        "order_id": order_id, "side": side, "qty": qty,
    }, timeout=5)
    return r.json()


def cancel_order(api, order_id):
    r = session.delete(f"{api}/orders/{order_id}", timeout=5)
    return r.json()


def replay_ticker(api, ticker, speed, order_id_start):
    print(f"\n[feed] Fetching {ticker} 1m bars (5d)...")
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1m")
    except Exception as e:
        print(f"[feed] yfinance error: {e}")
        return order_id_start

    if hist.empty:
        print(f"[feed] No data for {ticker}, skipping.")
        return order_id_start

    print(f"[feed] Got {len(hist)} bars. Replaying...")
    order_id = order_id_start
    resting = []
    avg_vol = hist["Volume"].mean()

    for ts, row in hist.iterrows():
        o, h, l, c, vol = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        mid = to_cents(c)
        bid = to_cents(l)
        ask = to_cents(h)
        if ask - bid < 2:
            bid, ask = mid - 1, mid + 1

        qty_base = max(1, int(vol / avg_vol * 10))

        for oid in [o for o in resting if random.random() < 0.20]:
            try:
                cancel_order(api, oid)
                resting.remove(oid)
            except Exception:
                pass

        try:
            res = place_limit(api, order_id, "SELL", ask, qty_base)
            if not res.get("trades"):
                resting.append(order_id)
        except Exception as e:
            print(f"[feed] error: {e}")
        order_id += 1

        try:
            res = place_limit(api, order_id, "BUY", bid, qty_base)
            if not res.get("trades"):
                resting.append(order_id)
        except Exception as e:
            print(f"[feed] error: {e}")
        order_id += 1

        if vol > avg_vol * 1.5:
            side = "BUY" if c > o else "SELL"
            mkt_qty = max(1, qty_base // 2)
            try:
                res = place_market(api, order_id, side, mkt_qty)
                trades = res.get("trades", [])
                print(f"[{ts}] {ticker} SPIKE {side} {mkt_qty} → {len(trades)} trade(s)")
            except Exception as e:
                print(f"[feed] error: {e}")
            order_id += 1
        else:
            try:
                book = res.get("book", {})
                bb = book.get("best_bid") or "none"
                ba = book.get("best_ask") or "none"
                bb_str = f"${int(bb)/100:.2f}" if bb != "none" else "none"
                ba_str = f"${int(ba)/100:.2f}" if ba != "none" else "none"
                print(f"[{ts}] {ticker} bid={bb_str} ask={ba_str} resting={len(resting)}")
            except Exception:
                pass

        time.sleep(speed)

    return order_id if order_id < 900_000 else 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--speed", type=float, default=0.2)
    ap.add_argument("--api-url", default=os.environ.get("API_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--loop", action="store_true", default=False)
    args = ap.parse_args()

    api = args.api_url.rstrip("/")
    tickers = [args.ticker] if args.ticker else TICKERS
    print(f"[feed] API: {api} | tickers: {tickers} | loop: {args.loop}")

    order_id = 1000
    while True:
        for ticker in tickers:
            order_id = replay_ticker(api, ticker, args.speed, order_id)
        if not args.loop:
            break
        print("[feed] Cycle done. Sleeping 30s...")
        time.sleep(30)


if __name__ == "__main__":
    main()