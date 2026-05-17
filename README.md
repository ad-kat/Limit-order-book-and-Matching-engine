# Limit Order Book & Matching Engine

A price-time priority matching engine written in C++20, capable of ~1.9M operations/sec with sub-microsecond median latency. The FastAPI layer, React dashboard, and market data feed are all demo infrastructure — the C++ engine is the actual project.

---

## How it works

```
Real NASDAQ tick data (yfinance)
        ↓
market_feed.py  →  POST /orders/limit  /orders/market
                         ↓
              FastAPI + async subprocess bridge
                         ↓
         C++ LOB binary — matching engine core
                         ↓
              WebSocket /ws → React dashboard
```

The Python server spawns the C++ binary in interactive mode and pipes commands over stdin/stdout. An `asyncio.Lock` serialises concurrent HTTP requests so nothing interleaves. Every trade and book update is broadcast to connected WebSocket clients immediately.

---

## Why these data structures

The cancel path is where most LOB implementations get it wrong. A naïve approach scans the price level queue linearly — O(n) per cancel, which falls apart under real order churn.

Here, each resting order is indexed by `unordered_map<OrderId, list::iterator>`. Cancellation is O(1): look up the iterator, call `list::erase()`, done. `std::list` is the right structure because erase-by-iterator is O(1) and doesn't invalidate other iterators — something `std::deque` can't offer.

Price levels live in `std::map<int64_t, Level>` (bids with `std::greater<>` for descending order), which keeps the best bid/ask at `begin()` without manual sorting.

**Benchmarks** (70% limit adds, 20% cancels, 10% market orders):
```
~1.9M ops/sec   p50 = 0.4µs   p95 = 0.9µs
```

```bash
./build/lob --bench 1000000
```

---

## Running the full stack

Three terminals. Run them in order.

### Terminal 1 — C++ engine + API

```bash
# First time only
python3 -m venv lobenv
pip install -r requirements.txt

source lobenv/bin/activate
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target lob -j$(nproc)

LOB_BINARY=./build/lob uvicorn api.main:app --reload --port 8000
```

> cmake warnings about `DOWNLOAD_EXTRACT_TIMESTAMP` and clock skew are harmless.

Swagger UI: **http://localhost:8000/docs**

### Terminal 2 — Real market data feed

```bash
source lobenv/bin/activate
pip install yfinance   # first time only

python3 market_feed.py --ticker AAPL --speed 0.2
```

| Flag | Default | What it does |
|------|---------|-------------|
| `--ticker` | `AAPL` | Any Yahoo Finance ticker — `TSLA`, `SPY`, `NVDA`, `MSFT` |
| `--interval` | `1m` | Bar size: `1m`, `2m`, `5m` |
| `--period` | `1d` | `1d` for today, `5d` for a week |
| `--speed` | `0.2` | Seconds per bar — `0.1` fast, `1.0` real-time |

Data is in-memory only — restarting the API resets engine state.

### Terminal 3 — React dashboard

```bash
cd lob-dashboard

# WSL users only — fixes Windows Node conflict
export PATH=/usr/bin:$PATH

# First time only
npm install

npm run dev
# → http://localhost:5173
```

The dashboard connects to `ws://localhost:8000/ws` automatically and falls back to mock data if the API isn't running.

> **WSL note:** If `npm install` fails with UNC path errors, your terminal is using the Windows Node installation. The `export PATH=/usr/bin:$PATH` line above fixes it. To make it permanent: `echo 'export PATH=/usr/bin:$PATH' >> ~/.bashrc`

---

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Engine status |
| `GET` | `/book` | Best bid / best ask / spread |
| `POST` | `/orders/limit` | Place a limit order |
| `POST` | `/orders/market` | Place a market order |
| `DELETE` | `/orders/{id}` | Cancel a resting order |

Place a sell, then cross the spread:
```bash
curl -X POST http://localhost:8000/orders/limit \
  -H "Content-Type: application/json" \
  -d '{"order_id": 1, "side": "SELL", "price": 101, "qty": 10}'

curl -X POST http://localhost:8000/orders/limit \
  -H "Content-Type: application/json" \
  -d '{"order_id": 2, "side": "BUY", "price": 103, "qty": 5}'
# → "trades": [{"price": 101, "qty": 5, "buy_id": 2, "sell_id": 1}]
```

Watch live via WebSocket:
```bash
npm install -g wscat
wscat -c ws://localhost:8000/ws
```

---

## Tests

```bash
cmake --build build --target lob_tests
ctest --test-dir build --output-on-failure
```

Covers basic matching, FIFO same-price priority, market orders, multi-level fills, cancel, and cancel of already-filled orders.

---

## Docker

```bash
docker compose up --build
```

Multi-stage: Stage 1 compiles on Ubuntu, Stage 2 copies the binary into `python:3.12-slim`.

---

## Project structure

```
.
├── src/
│   ├── main.cpp            # File replay / interactive / benchmark modes
│   └── order_book.cpp      # Matching engine
├── include/
│   └── order_book.hpp      # OrderBook, Order, Trade, Side
├── api/                    # Demo layer
│   ├── main.py             # FastAPI app
│   ├── engine.py           # Async subprocess bridge
│   ├── models.py           # Pydantic models
│   └── ws_manager.py       # WebSocket broadcast
├── lob-dashboard/          # React + Vite dashboard
│   └── src/
│       ├── App.jsx
│       ├── hooks/useLOB.js
│       └── components/
├── tests/                  # GoogleTest suite
├── data/sample.txt         # Hand-written order feed
├── market_feed.py          # Real market data ingestion
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Roadmap

- [x] C++ matching engine — price-time priority FIFO, ~1.9M ops/sec, sub-μs latency
- [x] O(1) cancel — `unordered_map<OrderId, list::iterator>` index
- [x] Benchmark harness — mixed workload, p50/p95 latency reporting
- [x] GoogleTest suite — matching, FIFO priority, market orders, multi-level fills, cancel
- [x] FastAPI layer — REST + WebSocket, async subprocess bridge
- [x] Real market data ingestion — Yahoo Finance OHLCV → LOB order flow
- [x] Docker — multi-stage build
- [x] React dashboard — pastel purple, live order book depth + trade tape, mock fallback
- [ ] LLM commentary agent — narrates market microstructure in real time
- [ ] Deploy — Railway (API) + Vercel (dashboard), public URLs
- [ ] SQLite trade log — persist sessions across restarts
- [ ] Thread-safe LOB — `std::shared_mutex` for concurrent access
- [ ] Lock-free order ID generator — `std::atomic<uint64_t>`
- [ ] FIX 4.2 parser — industry-standard order ingestion
- [ ] ML anomaly detection — spoofing and wash trading flags

---

**Adri Katyayan** — [LinkedIn](https://www.linkedin.com/in/adri-katyayan-21a0b2222/) · [GitHub](https://github.com/ad-kat)
MS Computer Science, Stony Brook University