cmake_minimum_required(VERSION 3.16)
project(LimitOrderBookAndMatchingEngine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Helpful warnings
add_compile_options(-Wall -Wextra -Wpedantic)

include_directories(include)

add_executable(lob
    src/main.cpp
    src/order_book.cpp
)
