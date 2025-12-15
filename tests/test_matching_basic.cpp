#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(MatchingBasic, PartialFillLeavesRestingAsk) {
    OrderBook ob;

    // Resting ask: sell 10 @ 101
    auto t1 = ob.add_limit(1, Side::Sell, 101, 10);
    EXPECT_TRUE(t1.empty());

    // Incoming buy: buy 7 @ 102 -> trades at 101 for qty 7
    auto t2 = ob.add_limit(2, Side::Buy, 102, 7);
    ASSERT_EQ(t2.size(), 1u);
    EXPECT_EQ(t2[0].price, 101);
    EXPECT_EQ(t2[0].qty, 7);
    EXPECT_EQ(t2[0].buy_id, 2u);
    EXPECT_EQ(t2[0].sell_id, 1u);

    // After partial fill, ask level 101 should still exist (3 remaining)
    EXPECT_FALSE(ob.best_ask().has_value() == false);
    EXPECT_TRUE(ob.best_ask().has_value());
    EXPECT_EQ(*ob.best_ask(), 101);

    // No bids should remain (buy was fully filled and doesn't rest)
    EXPECT_FALSE(ob.best_bid().has_value());
}
