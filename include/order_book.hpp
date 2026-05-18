#pragma once

#include <atomic>
#include <functional>
#include <list>
#include <cstdint>
#include <map>
#include <optional>
#include <shared_mutex>
#include <unordered_map>
#include <vector>

enum class Side : uint8_t { Buy, Sell };

using OrderId = std::uint64_t;

struct Order {
    OrderId      id;
    Side         side;
    std::int64_t price;  // limit price; 0 = market
    std::int64_t qty;    // remaining quantity
    std::uint64_t seq;   // monotone sequence for time-priority
};

struct Trade {
    std::int64_t price;
    std::int64_t qty;
    OrderId      buy_id;
    OrderId      sell_id;
};

class OrderBook {
public:
    OrderBook();

    // Returns trades generated. [[nodiscard]]: caller must not silently drop fills.
    [[nodiscard]] std::vector<Trade> add_limit(OrderId id, Side side,
                                               std::int64_t price, std::int64_t qty);
    [[nodiscard]] std::vector<Trade> add_market(OrderId id, Side side,
                                                std::int64_t qty);

    // Returns true if order was found and removed.
    [[nodiscard]] bool cancel(OrderId id);

    // Read-only queries — safe to call concurrently.
    [[nodiscard]] std::optional<std::int64_t> best_bid() const;
    [[nodiscard]] std::optional<std::int64_t> best_ask() const;
    [[nodiscard]] bool empty() const;

private:
    struct Level {
        std::list<Order> q;  // FIFO; std::list gives stable iterators
    };

    // bids: highest price first
    std::map<std::int64_t, Level, std::greater<>> bids_;
    // asks: lowest price first
    std::map<std::int64_t, Level> asks_;

    struct Locator {
        Side                       side;
        std::int64_t               price;
        std::list<Order>::iterator it;  // O(1) erase handle
    };

    std::unordered_map<OrderId, Locator> index_;

    // Atomic sequence counter — safe for concurrent ID generation.
    std::atomic<std::uint64_t> next_seq_;

    // shared_mutex: concurrent readers (best_bid/ask), exclusive writers (add/cancel).
    mutable std::shared_mutex mtx_;

    // Internals (called under exclusive lock only).
    std::vector<Trade> match_incoming(Order& incoming);
    void maybe_erase_empty_level(Side side, std::int64_t price);
};
