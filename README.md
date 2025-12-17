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
