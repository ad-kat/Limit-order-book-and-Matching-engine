#include <iostream>
#include "order_book.hpp"

static void print_trades(const std::vector<Trade>& trades) {
    for (const auto& t : trades) {
        std::cout << "TRADE price=" << t.price
                  << " qty=" << t.qty
                  << " buy=" << t.buy_id
                  << " sell=" << t.sell_id << "\n";
    }
}

int main() {
    OrderBook ob;

    // Add ask: sell 10 @ 101
    print_trades(ob.add_limit(1, Side::Sell, 101, 10));

    // Add bid: buy 7 @ 102 -> should trade against ask at 101 for qty 7
    print_trades(ob.add_limit(2, Side::Buy, 102, 7));

    std::cout << "best_bid=" << (ob.best_bid().has_value() ? std::to_string(*ob.best_bid()) : "none") << "\n";
    std::cout << "best_ask=" << (ob.best_ask().has_value() ? std::to_string(*ob.best_ask()) : "none") << "\n";

    return 0;
}
