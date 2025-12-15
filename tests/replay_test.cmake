execute_process(
  COMMAND ${LOB_EXE} ${INPUT_FILE}
  RESULT_VARIABLE rc
  OUTPUT_VARIABLE out
  OUTPUT_STRIP_TRAILING_WHITESPACE
)

if(NOT rc EQUAL 0)
  message(FATAL_ERROR "lob exited with code ${rc}")
endif()

file(READ "${EXPECTED_FILE}" expected)
string(STRIP "${expected}" expected)

if(NOT out STREQUAL expected)
  message("=== Expected ===")
  message("${expected}")
  message("=== Got ===")
  message("${out}")
  message(FATAL_ERROR "Output mismatch")
endif()
