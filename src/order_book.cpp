#include "order_book.hpp"

#include <stdexcept>

OrderBook::OrderBook() : next_seq_(1) {}

std::optional<std::int64_t> OrderBook::best_bid() const {
    if (bids_.empty()) return std::nullopt;
    return bids_.begin()->first; // because bids_ is descending
}

std::optional<std::int64_t> OrderBook::best_ask() const {
    if (asks_.empty()) return std::nullopt;
    return asks_.begin()->first; // ascending
}

bool OrderBook::empty() const {
    return bids_.empty() && asks_.empty();
}

std::vector<Trade> OrderBook::add_limit(OrderId id, Side side, std::int64_t price, std::int64_t qty) {
    if (qty <= 0) throw std::invalid_argument("qty must be > 0");
    if (price <= 0) throw std::invalid_argument("price must be > 0");
    if (index_.count(id)) throw std::invalid_argument("duplicate order id");

    Order incoming{ id, side, price, qty, next_seq_++ };

    // 1) Match against opposite book
    auto trades = match_incoming(incoming);

    // 2) If not fully filled, rest it on the book
    if (incoming.qty > 0) {
        if (side == Side::Buy) {
            bids_[price].q.push_back(incoming);
        } else {
            asks_[price].q.push_back(incoming);
        }
        index_[id] = Locator{ side, price, incoming.seq };
    }

    return trades;
}

std::vector<Trade> OrderBook::add_market(OrderId id, Side side, std::int64_t qty) {
    if (qty <= 0) throw std::invalid_argument("qty must be > 0");
    if (index_.count(id)) throw std::invalid_argument("duplicate order id");

    // Market order has no price cap; we treat it as “cross everything”
    // We’ll encode market price as 0; matching logic will ignore it for market orders.
    Order incoming{ id, side, 0, qty, next_seq_++ };

    auto trades = match_incoming(incoming);
    // Market order never rests. Any unfilled qty is just dropped.

    return trades;
}

bool OrderBook::cancel(OrderId id) {
    auto it = index_.find(id);
    if (it == index_.end()) return false;

    const Locator loc = it->second;

    if (loc.side == Side::Buy) {
        auto lvl_it = bids_.find(loc.price);
        if (lvl_it == bids_.end()) {
            index_.erase(it);
            return false;
        }

        auto& dq = lvl_it->second.q;
        for (auto qit = dq.begin(); qit != dq.end(); ++qit) {
            if (qit->id == id) {
                dq.erase(qit);
                index_.erase(it);
                maybe_erase_empty_level(Side::Buy, loc.price);
                return true;
            }
        }

        index_.erase(it);
        return false;
    } else { // Side::Sell
        auto lvl_it = asks_.find(loc.price);
        if (lvl_it == asks_.end()) {
            index_.erase(it);
            return false;
        }

        auto& dq = lvl_it->second.q;
        for (auto qit = dq.begin(); qit != dq.end(); ++qit) {
            if (qit->id == id) {
                dq.erase(qit);
                index_.erase(it);
                maybe_erase_empty_level(Side::Sell, loc.price);
                return true;
            }
        }

        index_.erase(it);
        return false;
    }
}



void OrderBook::maybe_erase_empty_level(Side side, std::int64_t price) {
    if (side == Side::Buy) {
        auto it = bids_.find(price);
        if (it != bids_.end() && it->second.q.empty()) bids_.erase(it);
    } else {
        auto it = asks_.find(price);
        if (it != asks_.end() && it->second.q.empty()) asks_.erase(it);
    }
}

// This is the heart.
/*
This function takes one incoming order and tries to execute it immediately against the existing order book.

It:

1. Matches by price first

2. Matches by time second (FIFO)

3. Generates trades

4. Updates quantities

5. Cleans up filled orders and empty price levels

This is the matching engine.
*/
std::vector<Trade> OrderBook::match_incoming(Order& incoming) {
    std::vector<Trade> trades;

    auto is_market = (incoming.price == 0);

    if (incoming.side == Side::Buy) {
        // Match against asks: lowest price first
        while (incoming.qty > 0 && !asks_.empty()) {
            auto lvl_it = asks_.begin();
            auto ask_price = lvl_it->first;

            if (!is_market && ask_price > incoming.price) break; // can't cross

            auto& dq = lvl_it->second.q;

            // Consume FIFO at this price level
            while (incoming.qty > 0 && !dq.empty()) {
                Order& resting = dq.front(); // SELL order

                std::int64_t fill = std::min(incoming.qty, resting.qty);

                trades.push_back(Trade{
                    /*price=*/ask_price,
                    /*qty=*/fill,
                    /*buy_id=*/incoming.id,
                    /*sell_id=*/resting.id
                });

                incoming.qty -= fill;
                resting.qty -= fill;

                if (resting.qty == 0) {
                    // remove from index and pop
                    index_.erase(resting.id);
                    dq.pop_front();
                }
            }

            // Remove empty price level
            if (dq.empty()) {
                asks_.erase(lvl_it);
            }
        }
    } else {
        // incoming.side == Side::Sell
        // Match against bids: highest price first
        while (incoming.qty > 0 && !bids_.empty()) {
            auto lvl_it = bids_.begin();
            auto bid_price = lvl_it->first;

            if (!is_market && bid_price < incoming.price) break; // can't cross

            auto& dq = lvl_it->second.q;

            while (incoming.qty > 0 && !dq.empty()) {
                Order& resting = dq.front(); // BUY order

                std::int64_t fill = std::min(incoming.qty, resting.qty);

                trades.push_back(Trade{
                    /*price=*/bid_price,
                    /*qty=*/fill,
                    /*buy_id=*/resting.id,
                    /*sell_id=*/incoming.id
                });

                incoming.qty -= fill;
                resting.qty -= fill;

                if (resting.qty == 0) {
                    index_.erase(resting.id);
                    dq.pop_front();
                }
            }

            if (dq.empty()) {
                bids_.erase(lvl_it);
            }
        }
    }

    return trades;
}

