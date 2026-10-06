cmake_minimum_required(VERSION 3.16)
project(fabba_rewrite LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(FABBA_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
set(FABBA_SOURCE_ROOT "" CACHE PATH "Optional frozen fABBA upstream snapshot")
set(FABBA_DATASETS_ROOT "" CACHE PATH "Optional read-only project datasets directory")
find_package(Threads REQUIRED)

add_library(fabba STATIC src/canonical/fabba.cpp)
set_target_properties(fabba PROPERTIES POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
target_include_directories(fabba PUBLIC include)
target_link_libraries(fabba PUBLIC Threads::Threads)
target_compile_features(fabba PUBLIC cxx_std_17)
target_compile_options(fabba PRIVATE -Wall -Wextra -Wpedantic -Wconversion
    -Wsign-conversion -Wshadow -Werror)

if(FABBA_ENABLE_SANITIZERS)
  target_compile_options(fabba PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(fabba PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

enable_testing()
add_executable(fabba_tests tests/unit/test_fabba.cpp)
target_link_libraries(fabba_tests PRIVATE fabba)
target_compile_options(fabba_tests PRIVATE -Wall -Wextra -Wpedantic -Wconversion
    -Wsign-conversion -Wshadow -Werror)
add_test(NAME fabba_tests COMMAND fabba_tests)

add_executable(fabba_cli tests/cross_decode/fabba_cli.cpp)
target_link_libraries(fabba_cli PRIVATE fabba)
target_compile_options(fabba_cli PRIVATE -Wall -Wextra -Wpedantic -Wconversion
    -Wsign-conversion -Wshadow -Werror)

add_library(fabba_c SHARED src/standalone/fabba_c.cpp)
set_target_properties(fabba_c PROPERTIES CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
target_compile_definitions(fabba_c PRIVATE FABBA_C_BUILD)
target_link_libraries(fabba_c PRIVATE fabba)
target_include_directories(fabba_c PUBLIC include)
target_compile_features(fabba_c PRIVATE cxx_std_17)
target_compile_options(fabba_c PRIVATE -Wall -Wextra -Wpedantic -Wconversion
    -Wsign-conversion -Wshadow -Werror)
if(UNIX AND NOT APPLE)
  target_link_options(fabba_c PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/src/standalone/fabba.exports.map")
endif()

add_executable(fabba_standalone_preflight tests/qualification/standalone_preflight.cpp)
target_link_libraries(fabba_standalone_preflight PRIVATE fabba_c)
target_compile_options(fabba_standalone_preflight PRIVATE -Wall -Wextra -Wpedantic
    -Wconversion -Wsign-conversion -Wshadow -Werror)
add_test(NAME fabba_standalone_preflight COMMAND fabba_standalone_preflight)

add_executable(fabba_c_header_smoke tests/qualification/c_header_smoke.c)
target_link_libraries(fabba_c_header_smoke PRIVATE fabba_c)
target_compile_features(fabba_c_header_smoke PRIVATE c_std_11)
target_compile_options(fabba_c_header_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME fabba_c_header_smoke COMMAND fabba_c_header_smoke)

if(FABBA_ENABLE_SANITIZERS)
  foreach(target fabba_c fabba_standalone_preflight fabba_c_header_smoke)
    target_compile_options(${target} PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer)
  endforeach()
endif()

add_executable(fabba_performance tests/performance/benchmark.cpp)
target_link_libraries(fabba_performance PRIVATE fabba)
target_compile_options(fabba_performance PRIVATE -Wall -Wextra -Wpedantic
    -Wconversion -Wsign-conversion -Wshadow -Werror)

find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND AND FABBA_SOURCE_ROOT)
  add_test(NAME fabba_golden_and_differential COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/cross_decode/run_differential.py
      --cpp-cli $<TARGET_FILE:fabba_cli>
      --oracle ${CMAKE_CURRENT_SOURCE_DIR}/tests/oracle/fabba_oracle.py
      --vectors ${CMAKE_CURRENT_SOURCE_DIR}/tests/golden/fabba_vectors.json)
  add_test(NAME fabba_native_capability_validation COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/capability/run_capability_validation.py
      --cpp-cli $<TARGET_FILE:fabba_cli>
      --source-root ${FABBA_SOURCE_ROOT})
  if(FABBA_DATASETS_ROOT)
    add_test(NAME fabba_dataset_validation COMMAND ${Python3_EXECUTABLE}
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/datasets/run_dataset_validation.py
        --cpp-cli $<TARGET_FILE:fabba_cli>
        --oracle ${CMAKE_CURRENT_SOURCE_DIR}/tests/oracle/fabba_oracle.py
        --datasets-root ${FABBA_DATASETS_ROOT}
        --json-output ${CMAKE_CURRENT_SOURCE_DIR}/validation/dataset_validation_result.json)
  endif()
endif()
