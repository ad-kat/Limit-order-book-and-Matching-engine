"""
market_feed.py — Real market data ingestion for the LOB engine.

Fetches real OHLCV data from Yahoo Finance (yfinance, free, no API key).
Converts each bar into realistic limit + market orders.
Feeds them to the running FastAPI server (POST /orders/limit etc).

Strategy per bar:
  - Derive synthetic bid/ask from OHLC (bid = low, ask = high, mid = close)
  - Place a resting SELL limit at ask, BUY limit at bid
  - If volume spike → fire a market order to simulate aggression
  - Randomly cancel ~20% of resting orders (realistic churn)

Run:
  python3 market_feed.py --ticker AAPL --interval 1m --period 1d --speed 0.1
  python3 market_feed.py --ticker AAPL --api-url https://your-railway-url.up.railway.app
  (speed = seconds between bars; 0.1 = fast replay, 1.0 = real-time feel)
"""

import argparse
import time
import random
import requests
import yfinance as yf

session = requests.Session()


def to_cents(price: float) -> int:
    """Convert float price to integer cents (engine uses integers)."""
    return max(1, int(round(price * 100)))


def place_limit(api: str, order_id: int, side: str, price_cents: int, qty: int) -> dict:
    r = session.post(f"{api}/orders/limit", json={
        "order_id": order_id,
        "side": side,
        "price": price_cents,
        "qty": qty,
    }, timeout=3)
    return r.json()


def place_market(api: str, order_id: int, side: str, qty: int) -> dict:
    r = session.post(f"{api}/orders/market", json={
        "order_id": order_id,
        "side": side,
        "qty": qty,
    }, timeout=3)
    return r.json()


def cancel(api: str, order_id: int) -> dict:
    r = session.delete(f"{api}/orders/{order_id}", timeout=3)
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="AAPL")
    ap.add_argument("--interval", default="1m", help="1m 2m 5m")
    ap.add_argument("--period", default="1d", help="1d 5d")
    ap.add_argument("--speed", type=float, default=0.2,
                    help="Seconds between bars (0.1=fast, 1.0=slow)")
    ap.add_argument("--api-url", default="http://127.0.0.1:8000",
                    help="Base URL of the LOB API (default: http://127.0.0.1:8000)")
    args = ap.parse_args()

    api = args.api_url.rstrip("/")
    print(f"API target: {api}")
    print(f"Fetching {args.ticker} {args.interval} bars ({args.period})...")

    ticker = yf.Ticker(args.ticker)
    hist = ticker.history(period=args.period, interval=args.interval)

    if hist.empty:
        print("No data returned. Market may be closed. Try --period 5d.")
        return

    print(f"Got {len(hist)} bars. Replaying into LOB engine...\n")

    order_id = 1000          # start high so no clash with manual orders
    resting: list[int] = []  # track live order IDs for cancels
    avg_vol = hist["Volume"].mean()

    for ts, row in hist.iterrows():
        o, h, l, c, vol = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]

        # Synthetic bid/ask from bar
        mid   = to_cents(c)
        bid   = to_cents(l)           # conservative bid = bar low
        ask   = to_cents(h)           # conservative ask = bar high
        spread = ask - bid
        if spread < 2:                # enforce min 2-cent spread
            bid  = mid - 1
            ask  = mid + 1

        qty_base = max(1, int(vol / avg_vol * 10))  # scale qty to relative volume

        # Cancel ~20% of resting orders (realistic churn)
        to_cancel = [oid for oid in resting if random.random() < 0.20]
        for oid in to_cancel:
            try:
                cancel(api, oid)
                resting.remove(oid)
            except Exception:
                pass

        # Place resting SELL limit at ask
        res = place_limit(api, order_id, "SELL", ask, qty_base)
        trades = res.get("trades", [])
        if not trades:               # only track if not immediately filled
            resting.append(order_id)
        order_id += 1

        # Place resting BUY limit at bid
        res = place_limit(api, order_id, "BUY", bid, qty_base)
        trades = res.get("trades", [])
        if not trades:
            resting.append(order_id)
        order_id += 1

        # Volume spike → aggressive market order
        if vol > avg_vol * 1.5:
            side = "BUY" if c > o else "SELL"
            mkt_qty = max(1, qty_base // 2)
            res = place_market(api, order_id, side, mkt_qty)
            trades = res.get("trades", [])
            trade_str = f"  → {len(trades)} trade(s)" if trades else ""
            print(f"[{ts}] SPIKE vol={int(vol):>10,} MARKET {side} {mkt_qty}{trade_str}")
            order_id += 1
        else:
            book = res.get("book", {})
            bb = book.get("best_bid") or "none"
            ba = book.get("best_ask") or "none"
            bb_str = f"${int(bb)/100:.2f}" if bb != "none" else "none"
            ba_str = f"${int(ba)/100:.2f}" if ba != "none" else "none"
            print(f"[{ts}] O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} "
                  f"bid={bb_str} ask={ba_str} resting={len(resting)}")

        time.sleep(args.speed)

    print(f"\nDone. {order_id - 1000} orders sent.")


if __name__ == "__main__":
    main()