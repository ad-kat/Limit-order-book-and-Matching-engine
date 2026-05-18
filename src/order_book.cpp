#include "order_book.hpp"

#include <mutex>
#include <stdexcept>

// ── Constructor ───────────────────────────────────────────────────────────────

OrderBook::OrderBook() : next_seq_(1) {}

// ── Read-only queries (shared lock) ──────────────────────────────────────────

std::optional<std::int64_t> OrderBook::best_bid() const {
    std::shared_lock lock(mtx_);
    if (bids_.empty()) return std::nullopt;
    return bids_.begin()->first;
}

std::optional<std::int64_t> OrderBook::best_ask() const {
    std::shared_lock lock(mtx_);
    if (asks_.empty()) return std::nullopt;
    return asks_.begin()->first;
}

bool OrderBook::empty() const {
    std::shared_lock lock(mtx_);
    return bids_.empty() && asks_.empty();
}

// ── Mutating operations (exclusive lock) ─────────────────────────────────────

std::vector<Trade> OrderBook::add_limit(OrderId id, Side side,
                                        std::int64_t price, std::int64_t qty) {
    if (qty   <= 0) throw std::invalid_argument("qty must be > 0");
    if (price <= 0) throw std::invalid_argument("price must be > 0");

    std::unique_lock lock(mtx_);

    if (index_.count(id)) throw std::invalid_argument("duplicate order id");

    // fetch_add returns old value; post-increment gives unique seq per order
    Order incoming{ id, side, price, qty, next_seq_.fetch_add(1, std::memory_order_relaxed) };

    auto trades = match_incoming(incoming);

    if (incoming.qty > 0) {
        if (side == Side::Buy) {
            auto& lst = bids_[price].q;
            lst.push_back(incoming);
            index_[id] = Locator{ side, price, std::prev(lst.end()) };
        } else {
            auto& lst = asks_[price].q;
            lst.push_back(incoming);
            index_[id] = Locator{ side, price, std::prev(lst.end()) };
        }
    }

    return trades;
}

std::vector<Trade> OrderBook::add_market(OrderId id, Side side, std::int64_t qty) {
    if (qty <= 0) throw std::invalid_argument("qty must be > 0");

    std::unique_lock lock(mtx_);

    if (index_.count(id)) throw std::invalid_argument("duplicate order id");

    // Market order: price = 0 signals "cross everything"
    Order incoming{ id, side, 0, qty, next_seq_.fetch_add(1, std::memory_order_relaxed) };

    return match_incoming(incoming);
    // Market orders never rest; unfilled qty is dropped.
}

bool OrderBook::cancel(OrderId id) {
    std::unique_lock lock(mtx_);

    auto it = index_.find(id);
    if (it == index_.end()) return false;

    const Locator loc = it->second;

    if (loc.side == Side::Buy) {
        auto lvl_it = bids_.find(loc.price);
        if (lvl_it == bids_.end()) { index_.erase(it); return false; }
        lvl_it->second.q.erase(loc.it);   // O(1) — iterator still valid
        index_.erase(it);
        if (lvl_it->second.q.empty()) bids_.erase(lvl_it);
    } else {
        auto lvl_it = asks_.find(loc.price);
        if (lvl_it == asks_.end()) { index_.erase(it); return false; }
        lvl_it->second.q.erase(loc.it);
        index_.erase(it);
        if (lvl_it->second.q.empty()) asks_.erase(lvl_it);
    }

    return true;
}

// ── Internal helpers (called under exclusive lock) ────────────────────────────

void OrderBook::maybe_erase_empty_level(Side side, std::int64_t price) {
    if (side == Side::Buy) {
        auto it = bids_.find(price);
        if (it != bids_.end() && it->second.q.empty()) bids_.erase(it);
    } else {
        auto it = asks_.find(price);
        if (it != asks_.end() && it->second.q.empty()) asks_.erase(it);
    }
}

// ── Matching engine (price-time priority FIFO) ────────────────────────────────
//
// Consumes `incoming` against the opposite side.
// Generates Trade records, updates resting order qty, removes fully-filled orders.
// Called exclusively under unique_lock — no additional locking needed here.

std::vector<Trade> OrderBook::match_incoming(Order& incoming) {
    std::vector<Trade> trades;

    const bool is_market = (incoming.price == 0);

    if (incoming.side == Side::Buy) {
        // Match against asks: lowest price first
        while (incoming.qty > 0 && !asks_.empty()) {
            auto lvl_it    = asks_.begin();
            const auto ask_price = lvl_it->first;

            if (!is_market && ask_price > incoming.price) break;

            auto& q = lvl_it->second.q;

            while (incoming.qty > 0 && !q.empty()) {
                auto   it      = q.begin();
                Order& resting = *it;

                const std::int64_t fill = std::min(incoming.qty, resting.qty);

                trades.push_back(Trade{ ask_price, fill, incoming.id, resting.id });

                incoming.qty -= fill;
                resting.qty  -= fill;

                if (resting.qty == 0) {
                    index_.erase(resting.id);
                    q.erase(it);
                }
            }

            if (q.empty()) asks_.erase(lvl_it);
        }
    } else {
        // Match against bids: highest price first
        while (incoming.qty > 0 && !bids_.empty()) {
            auto lvl_it    = bids_.begin();
            const auto bid_price = lvl_it->first;

            if (!is_market && bid_price < incoming.price) break;

            auto& q = lvl_it->second.q;

            while (incoming.qty > 0 && !q.empty()) {
                auto   it      = q.begin();
                Order& resting = *it;

                const std::int64_t fill = std::min(incoming.qty, resting.qty);

                trades.push_back(Trade{ bid_price, fill, resting.id, incoming.id });

                incoming.qty -= fill;
                resting.qty  -= fill;

                if (resting.qty == 0) {
                    index_.erase(resting.id);
                    q.erase(it);
                }
            }

            if (q.empty()) bids_.erase(lvl_it);
        }
    }

    return trades;
}
