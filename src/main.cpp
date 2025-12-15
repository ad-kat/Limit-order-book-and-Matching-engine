#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <cctype>
#include <random>
#include <chrono>
#include "order_book.hpp"

static Side parse_side(const std::string& s) {
    if (s == "BUY") return Side::Buy;
    if (s == "SELL") return Side::Sell;
    throw std::invalid_argument("Invalid side: " + s);
}

static void print_trades(const std::vector<Trade>& trades) {
    for (const auto& t : trades) {
        std::cout << "TRADE price=" << t.price
                  << " qty=" << t.qty
                  << " buy=" << t.buy_id
                  << " sell=" << t.sell_id << "\n";
    }
}

static int run_bench(std::size_t n) {
    OrderBook ob;

    std::mt19937_64 rng(42);
    std::uniform_int_distribution<int> side_dist(0, 1);
    std::uniform_int_distribution<int> px_dist(95, 105);
    std::uniform_int_distribution<int> qty_dist(1, 10);

    std::size_t trades_count = 0;

    auto start = std::chrono::steady_clock::now();

    for (std::size_t i = 1; i <= n; ++i) {
        Side side = (side_dist(rng) == 0) ? Side::Buy : Side::Sell;
        std::int64_t px = px_dist(rng);
        std::int64_t qty = qty_dist(rng);

        auto trades = ob.add_limit(static_cast<OrderId>(i), side, px, qty);
        trades_count += trades.size();
    }

    auto end = std::chrono::steady_clock::now();
    std::chrono::duration<double> sec = end - start;

    double ops_per_sec = n / sec.count();

    std::cout << "BENCH orders=" << n
              << " trades=" << trades_count
              << " seconds=" << sec.count()
              << " ops_per_sec=" << ops_per_sec
              << "\n";

    return 0;
}

int main(int argc, char** argv) {
    OrderBook ob;

    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input_file>\n";
        std::cerr << "Commands:\n";
        std::cerr << "  ADD <id> <BUY|SELL> <price> <qty>\n";
        std::cerr << "  MARKET <id> <BUY|SELL> <qty>\n";
        std::cerr << "  CANCEL <id>\n";
        return 1;
    }
    if (argc == 3 && std::string(argv[1]) == "--bench") {
    std::size_t n = std::stoull(argv[2]);
    return run_bench(n);
}

    std::ifstream in(argv[1]);
    if (!in) {
        std::cerr << "Failed to open file: " << argv[1] << "\n";
        return 1;
    }

    std::string line;
    std::size_t lineno = 0;

    while (std::getline(in, line)) {
        ++lineno;

        // trim leading spaces
        std::size_t i = 0;
        while (i < line.size() && std::isspace(static_cast<unsigned char>(line[i]))) ++i;
        if (i == line.size()) continue;          // blank
        if (line[i] == '#') continue;            // comment

        std::istringstream ss(line);
        std::string cmd;
        ss >> cmd;

        try {
            if (cmd == "ADD") {
                OrderId id;
                std::string side_s;
                std::int64_t price, qty;
                ss >> id >> side_s >> price >> qty;
                auto trades = ob.add_limit(id, parse_side(side_s), price, qty);
                print_trades(trades);
            } else if (cmd == "MARKET") {
                OrderId id;
                std::string side_s;
                std::int64_t qty;
                ss >> id >> side_s >> qty;
                auto trades = ob.add_market(id, parse_side(side_s), qty);
                print_trades(trades);
            } else if (cmd == "CANCEL") {
                OrderId id;
                ss >> id;
                bool ok = ob.cancel(id);
                std::cout << "CANCEL id=" << id << " " << (ok ? "OK" : "NOT_FOUND") << "\n";
            } else {
                throw std::invalid_argument("Unknown command: " + cmd);
            }
        } catch (const std::exception& e) {
            std::cerr << "Error on line " << lineno << ": " << e.what() << "\n";
            std::cerr << "  Line: " << line << "\n";
            return 2;
        }
    }

    std::cout << "FINAL best_bid="
              << (ob.best_bid() ? std::to_string(*ob.best_bid()) : "none")
              << " best_ask="
              << (ob.best_ask() ? std::to_string(*ob.best_ask()) : "none")
              << "\n";

    return 0;
}
