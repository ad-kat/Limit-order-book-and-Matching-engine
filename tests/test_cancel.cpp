#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(Cancel, RemovesRestingOrder) {
    OrderBook ob;

    ob.add_limit(1, Side::Buy, 100, 5);
    ASSERT_TRUE(ob.best_bid().has_value());
    EXPECT_EQ(*ob.best_bid(), 100);

    EXPECT_TRUE(ob.cancel(1));

    // After cancel, book should be empty
    EXPECT_FALSE(ob.best_bid().has_value());
    EXPECT_TRUE(ob.empty());
}
