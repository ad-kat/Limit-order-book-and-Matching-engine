# Limit Order Book & Matching Engine (C++)

A modern C++ implementation of a **limit order book and matching engine** with **price-time priority**, designed to model core exchange / trading-system mechanics.  
The project emphasizes **correctness, performance, and clean system design**, with unit tests and benchmarking support.

---

## Features
- Limit and market orders (buy / sell)
- Price-time priority matching
- Order add / cancel / modify (via cancel + add)
- Trade generation and top-of-book queries (best bid / ask)
- Deterministic replay of order streams
- Unit tests for matching correctness and book invariants
- Benchmarking of throughput and latency under synthetic workloads

---

## Design Overview

### Core Concepts
- **Order**: uniquely identified, immutable price, mutable remaining quantity
- **OrderBook**:
  - Bid book: sorted by **descending price**, FIFO within price level
  - Ask book: sorted by **ascending price**, FIFO within price level
- **Matching Engine**:
  - Aggressive orders match against the opposite side
  - Enforces strict price-time priority
  - Generates trades until filled or book is exhausted

### Data Structures
- Price levels stored using ordered associative containers
- FIFO queues per price level to preserve time priority
- Explicit separation of matching logic from book state

---

## Build Instructions

### Requirements
- Linux / WSL2
- C++20 compatible compiler (GCC ≥ 11)
- CMake ≥ 3.16

### Build
```bash
mkdir -p build
cmake -S . -B build
cmake --build build -j
