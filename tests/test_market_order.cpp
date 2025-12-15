#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(MarketOrder, BuyMarketConsumesBestAsks) {
    OrderBook ob;

    // Two ask levels
    ob.add_limit(1, Side::Sell, 101, 3);
    ob.add_limit(2, Side::Sell, 102, 4);

    // Buy market 5 should take 3 @101 then 2 @102
    auto trades = ob.add_market(10, Side::Buy, 5);
    ASSERT_EQ(trades.size(), 2u);

    EXPECT_EQ(trades[0].price, 101);
    EXPECT_EQ(trades[0].qty, 3);
    EXPECT_EQ(trades[0].buy_id, 10u);
    EXPECT_EQ(trades[0].sell_id, 1u);

    EXPECT_EQ(trades[1].price, 102);
    EXPECT_EQ(trades[1].qty, 2);
    EXPECT_EQ(trades[1].buy_id, 10u);
    EXPECT_EQ(trades[1].sell_id, 2u);

    // Market order never rests; bids should be empty
    EXPECT_FALSE(ob.best_bid().has_value());

    // Asks should still exist at 102 (2 remaining)
    ASSERT_TRUE(ob.best_ask().has_value());
    EXPECT_EQ(*ob.best_ask(), 102);
}
