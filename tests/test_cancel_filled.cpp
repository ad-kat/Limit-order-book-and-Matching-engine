#include <gtest/gtest.h>
#include "order_book.hpp"

TEST(Cancel, FilledOrderCannotBeCanceled) {
    OrderBook ob;

    (void)ob.add_limit(1, Side::Sell, 101, 5);
    auto fills = ob.add_limit(2, Side::Buy, 101, 5); // fills order 1 completely
    EXPECT_EQ(fills.size(), 1u); // sanity: one trade expected

    EXPECT_FALSE(ob.cancel(1)); // should already be gone
}
