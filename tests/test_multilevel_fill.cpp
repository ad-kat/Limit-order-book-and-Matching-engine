#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(Matching, LimitBuyFillsAcrossMultipleAskLevels) {
    OrderBook ob;

    ob.add_limit(1, Side::Sell, 101, 2);
    ob.add_limit(2, Side::Sell, 102, 3);
    ob.add_limit(3, Side::Sell, 103, 5);

    // Buy 6 @ 102 -> should fill 2@101 + 3@102, then rest 1@102? NO, can't: it is incoming buy.
    // Actually buy 6 @ 102 will fill 2+3=5, leaving 1 unfilled -> it should REST as bid @102 with qty 1.
    auto trades = ob.add_limit(10, Side::Buy, 102, 6);
    ASSERT_EQ(trades.size(), 2u);

    EXPECT_EQ(trades[0].price, 101);
    EXPECT_EQ(trades[0].qty, 2);
    EXPECT_EQ(trades[1].price, 102);
    EXPECT_EQ(trades[1].qty, 3);

    // Remaining ask should now be 103
    ASSERT_TRUE(ob.best_ask().has_value());
    EXPECT_EQ(*ob.best_ask(), 103);

    // Remaining unfilled 1 should rest as best bid=102
    ASSERT_TRUE(ob.best_bid().has_value());
    EXPECT_EQ(*ob.best_bid(), 102);
}
