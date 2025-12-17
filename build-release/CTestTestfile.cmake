# CMake generated Testfile for 
# Source directory: /home/adkat/LimitOrderBookandMatchingEngine
# Build directory: /home/adkat/LimitOrderBookandMatchingEngine/build-release
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
include("/home/adkat/LimitOrderBookandMatchingEngine/build-release/lob_tests[1]_include.cmake")
add_test(replay_sample "/usr/bin/cmake" "-DLOB_EXE=/home/adkat/LimitOrderBookandMatchingEngine/build-release/lob" "-DINPUT_FILE=/home/adkat/LimitOrderBookandMatchingEngine/data/sample.txt" "-DEXPECTED_FILE=/home/adkat/LimitOrderBookandMatchingEngine/tests/expected_sample_output.txt" "-P" "/home/adkat/LimitOrderBookandMatchingEngine/tests/replay_test.cmake")
set_tests_properties(replay_sample PROPERTIES  _BACKTRACE_TRIPLES "/home/adkat/LimitOrderBookandMatchingEngine/CMakeLists.txt;44;add_test;/home/adkat/LimitOrderBookandMatchingEngine/CMakeLists.txt;0;")
add_test(bench_smoke "/home/adkat/LimitOrderBookandMatchingEngine/build-release/lob" "--bench" "10000")
set_tests_properties(bench_smoke PROPERTIES  _BACKTRACE_TRIPLES "/home/adkat/LimitOrderBookandMatchingEngine/CMakeLists.txt;51;add_test;/home/adkat/LimitOrderBookandMatchingEngine/CMakeLists.txt;0;")
subdirs("_deps/googletest-build")
