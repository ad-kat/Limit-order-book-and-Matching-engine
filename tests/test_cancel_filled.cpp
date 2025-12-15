#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(Cancel, FilledOrderCannotBeCanceled) {
    OrderBook ob;

    ob.add_limit(1, Side::Sell, 101, 5);
    ob.add_limit(2, Side::Buy, 101, 5); // fills order 1 completely

    EXPECT_FALSE(ob.cancel(1)); // should already be gone
}
