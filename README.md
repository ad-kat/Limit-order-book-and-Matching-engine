# Limit Order Book and Matching Engine (C++)

A single-threaded **price–time priority limit order book and matching engine** implemented in modern C++ with correctness tests, replay support, and performance benchmarks.

This project models the core matching logic used in electronic exchanges and trading systems.

---

## Features
- Price–time priority matching (FIFO within price levels)
- Supports **LIMIT**, **MARKET**, and **CANCEL** orders
- File-based order flow replay (exchange-style logs)
- O(1) order cancellation using iterator-based indexing
- Deterministic benchmarks with throughput and latency (p50 / p95)
- Unit tests + integration replay tests

---

## Data Structures & Design
- **Price levels**: `std::map`
  - bids sorted descending
  - asks sorted ascending
- **FIFO queues per level**: `std::list<Order>`
- **Order index**: `unordered_map<OrderId, iterator>` for O(1) cancel
- **Matching**: price-time priority, partial fills supported

### Time Complexity
| Operation | Complexity |
|---------|------------|
| Add order | O(log N) |
| Match | O(trades) |
| Cancel | **O(1)** |
| Best bid / ask | O(1) |

---

## Build
```bash
cmake -S . -B build
cmake --build build -j
```
## Release build (recommended for benchmarks)
```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j
```
##Run – Order Flow Replay
```bash
./build/lob data/sample.txt
```
##Example input:
```sql
ADD 1 SELL 101 10
ADD 2 BUY 102 7
ADD 3 BUY 100 5
ADD 4 SELL 99 2
CANCEL 3
MARKET 5 BUY 4
```
##Output
```sql
TRADE price=101 qty=7 buy=2 sell=1
TRADE price=100 qty=2 buy=3 sell=4
CANCEL id=3 OK
TRADE price=101 qty=3 buy=5 sell=1
FINAL best_bid=none best_ask=none
```
##Run Benchmarks
```bash
./build-release/lob --bench 1000000
```
Example result (WSL2, GCC 13, Release build):
```makefile
BENCH_MIX ops=1000000
adds=700408 cancels=199148 markets=100444
ops_per_sec≈1.95M
p50≈0.55µs  p95≈1.21µs
```
##Tests
```bash
ctest --test-dir build --output-on-failure
```
Includes:
- FIFO correctness
- Partial fills
- Multi-level matching
- Market orders
- Cancel semantics
- Replay integration test
