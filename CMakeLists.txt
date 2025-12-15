cmake_minimum_required(VERSION 3.16)
project(LimitOrderBookAndMatchingEngine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_compile_options(-Wall -Wextra -Wpedantic)

# ---- Library target (your core engine) ----
add_library(lob_core
    src/order_book.cpp
)
target_include_directories(lob_core PUBLIC include)

# ---- Main executable ----
add_executable(lob src/main.cpp)
target_link_libraries(lob PRIVATE lob_core)

# ---- Tests ----
include(CTest)
enable_testing()

include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.zip
)
# For Linux/WSL this is usually fine; keep it to avoid Windows CRT issues if you ever build on Windows.
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)


add_executable(lob_tests
    tests/test_matching_basic.cpp
    tests/test_fifo_same_price.cpp
    tests/test_market_order.cpp
    tests/test_multilevel_fill.cpp
    tests/test_cancel.cpp
    tests/test_cancel_filled.cpp
)
target_link_libraries(lob_tests PRIVATE lob_core GTest::gtest_main)

add_test(NAME replay_sample
  COMMAND ${CMAKE_COMMAND}
    -DLOB_EXE=$<TARGET_FILE:lob>
    -DINPUT_FILE=${CMAKE_SOURCE_DIR}/data/sample.txt
    -DEXPECTED_FILE=${CMAKE_SOURCE_DIR}/tests/expected_sample_output.txt
    -P ${CMAKE_SOURCE_DIR}/tests/replay_test.cmake
)
add_test(NAME bench_smoke COMMAND $<TARGET_FILE:lob> --bench 10000)
ctest --test-dir build --output-on-failure

include(GoogleTest)
gtest_discover_tests(lob_tests)
