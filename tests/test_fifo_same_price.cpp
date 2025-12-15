#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(FIFO, SamePriceExecutesOlderFirst) {
    OrderBook ob;

    // Two sells at same price, different order ids -> FIFO should fill id=1 then id=2
    ob.add_limit(1, Side::Sell, 101, 5);
    ob.add_limit(2, Side::Sell, 101, 5);

    // Buy 7 @ 101 -> should consume 5 from id=1, then 2 from id=2
    auto trades = ob.add_limit(3, Side::Buy, 101, 7);
    ASSERT_EQ(trades.size(), 2u);

    EXPECT_EQ(trades[0].price, 101);
    EXPECT_EQ(trades[0].qty, 5);
    EXPECT_EQ(trades[0].buy_id, 3u);
    EXPECT_EQ(trades[0].sell_id, 1u);

    EXPECT_EQ(trades[1].price, 101);
    EXPECT_EQ(trades[1].qty, 2);
    EXPECT_EQ(trades[1].buy_id, 3u);
    EXPECT_EQ(trades[1].sell_id, 2u);

    // Remaining ask should still be 101 (3 left from order 2)
    ASSERT_TRUE(ob.best_ask().has_value());
    EXPECT_EQ(*ob.best_ask(), 101);
}
