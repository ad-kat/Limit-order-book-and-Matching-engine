#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <cctype>
#include <random>
#include <chrono>
#include <algorithm>
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

    const std::size_t sample_every = 1000; // sample 0.1% ops
    std::vector<double> lat_us;
    lat_us.reserve(n / sample_every + 1);

    std::mt19937_64 rng(42);

    // Operation mix: 0-69 ADD, 70-89 CANCEL, 90-99 MARKET
    std::uniform_int_distribution<int> op_dist(0, 99);
    std::uniform_int_distribution<int> side_dist(0, 1);
    std::uniform_int_distribution<int> px_dist(95, 105);
    std::uniform_int_distribution<int> qty_dist(1, 10);
    std::uniform_int_distribution<int> mkt_qty_dist(1, 5);

    std::vector<OrderId> active_ids;
    active_ids.reserve(n / 2);

    OrderId next_id = 1;

    std::size_t adds = 0, cancels = 0, markets = 0;
    std::size_t trades_count = 0;
    std::size_t cancel_ok = 0, cancel_miss = 0;

    auto start = std::chrono::steady_clock::now();

    for (std::size_t i = 0; i < n; ++i) {
        bool sample = (i % sample_every == 0);
        auto t0 = sample ? std::chrono::steady_clock::now()
                         : std::chrono::steady_clock::time_point{};

        int op = op_dist(rng);

        if (op < 70) {
            // ADD limit
            Side side = (side_dist(rng) == 0) ? Side::Buy : Side::Sell;
            std::int64_t px = px_dist(rng);
            std::int64_t qty = qty_dist(rng);

            OrderId id = next_id++;
            auto trades = ob.add_limit(id, side, px, qty);
            trades_count += trades.size();

            active_ids.push_back(id);
            ++adds;

        } else if (op < 90) {
            // CANCEL
            if (!active_ids.empty()) {
                std::uniform_int_distribution<std::size_t> idx_dist(0, active_ids.size() - 1);
                std::size_t idx = idx_dist(rng);
                OrderId id = active_ids[idx];

                bool ok = ob.cancel(id);
                if (ok) ++cancel_ok;
                else    ++cancel_miss;

                // remove id from active_ids in O(1) by swap+pop
                active_ids[idx] = active_ids.back();
                active_ids.pop_back();

                ++cancels;
            } else {
                // fallback to add
                Side side = (side_dist(rng) == 0) ? Side::Buy : Side::Sell;
                std::int64_t px = px_dist(rng);
                std::int64_t qty = qty_dist(rng);

                OrderId id = next_id++;
                auto trades = ob.add_limit(id, side, px, qty);
                trades_count += trades.size();

                active_ids.push_back(id);
                ++adds;
            }

        } else {
            // MARKET
            Side side = (side_dist(rng) == 0) ? Side::Buy : Side::Sell;
            std::int64_t qty = mkt_qty_dist(rng);

            OrderId id = next_id++;
            auto trades = ob.add_market(id, side, qty);
            trades_count += trades.size();

            ++markets;
        }

        if (sample) {
            auto t1 = std::chrono::steady_clock::now();
            std::chrono::duration<double, std::micro> us = t1 - t0;
            lat_us.push_back(us.count());
        }
    }

    auto end = std::chrono::steady_clock::now();
    std::chrono::duration<double> sec = end - start;
    double ops_per_sec = n / sec.count();

    double p50 = 0.0, p95 = 0.0;
    if (!lat_us.empty()) {
        std::sort(lat_us.begin(), lat_us.end());
        std::size_t idx50 = static_cast<std::size_t>(0.50 * (lat_us.size() - 1));
        std::size_t idx95 = static_cast<std::size_t>(0.95 * (lat_us.size() - 1));
        p50 = lat_us[idx50];
        p95 = lat_us[idx95];
    }

    std::cout << "BENCH_MIX ops=" << n
              << " adds=" << adds
              << " cancels=" << cancels
              << " markets=" << markets
              << " trades=" << trades_count
              << " cancel_ok=" << cancel_ok
              << " cancel_miss=" << cancel_miss
              << " seconds=" << sec.count()
              << " ops_per_sec=" << ops_per_sec
              << " p50_us=" << p50
              << " p95_us=" << p95
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
