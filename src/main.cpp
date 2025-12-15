#include <iostream>
#include "order_book.hpp"

int main() {
    OrderBook ob;
    std::cout << ob.health() << "\n";
    return 0;
}
