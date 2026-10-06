cmake_minimum_required(VERSION 3.16)
project(prometheus_xor2_chunk_rewrite LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(PXOR2_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
set(PXOR2_GO_ORACLE "" CACHE FILEPATH "Optional prebuilt frozen Go XOR2 oracle")
set(PXOR2_DATASETS_ROOT "" CACHE PATH "Optional read-only project datasets directory")

add_library(prometheus_xor2_chunk STATIC
    src/canonical/prometheus_xor2_chunk.cpp
)
set_target_properties(prometheus_xor2_chunk PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(prometheus_xor2_chunk PUBLIC include)
target_compile_features(prometheus_xor2_chunk PUBLIC cxx_std_17)
target_compile_options(prometheus_xor2_chunk PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
if(PXOR2_ENABLE_SANITIZERS)
    target_compile_options(prometheus_xor2_chunk PUBLIC
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
    target_link_options(prometheus_xor2_chunk PUBLIC
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
endif()

enable_testing()
add_executable(prometheus_xor2_chunk_tests tests/unit/test_prometheus_xor2_chunk.cpp)
target_link_libraries(prometheus_xor2_chunk_tests PRIVATE prometheus_xor2_chunk)
target_compile_options(prometheus_xor2_chunk_tests PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
add_test(NAME prometheus_xor2_chunk_tests COMMAND prometheus_xor2_chunk_tests)

add_executable(prometheus_xor2_chunk_cli tests/cross_decode/xor2_chunk_cli.cpp)
target_link_libraries(prometheus_xor2_chunk_cli PRIVATE prometheus_xor2_chunk)
target_compile_options(prometheus_xor2_chunk_cli PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)

add_library(prometheus_xor2_chunk_c SHARED
    src/standalone/prometheus_xor2_chunk_c.cpp
)
target_link_libraries(prometheus_xor2_chunk_c PRIVATE prometheus_xor2_chunk)
target_include_directories(prometheus_xor2_chunk_c PUBLIC include)
target_compile_features(prometheus_xor2_chunk_c PRIVATE cxx_std_17)
target_compile_options(prometheus_xor2_chunk_c PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)

add_executable(prometheus_xor2_chunk_standalone_preflight
    tests/qualification/standalone_preflight.cpp
)
target_link_libraries(prometheus_xor2_chunk_standalone_preflight PRIVATE prometheus_xor2_chunk_c)
target_compile_options(prometheus_xor2_chunk_standalone_preflight PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
if(PXOR2_ENABLE_SANITIZERS)
    target_compile_options(prometheus_xor2_chunk_standalone_preflight PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
    target_link_options(prometheus_xor2_chunk_standalone_preflight PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
endif()
add_test(
    NAME prometheus_xor2_chunk_standalone_preflight
    COMMAND prometheus_xor2_chunk_standalone_preflight
)

add_executable(prometheus_xor2_chunk_performance tests/performance/benchmark.cpp)
target_link_libraries(prometheus_xor2_chunk_performance PRIVATE prometheus_xor2_chunk)
target_compile_options(prometheus_xor2_chunk_performance PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)

find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND AND PXOR2_GO_ORACLE)
    add_test(
        NAME prometheus_xor2_chunk_cross_decode
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/cross_decode/run_cross_decode.py
                --cpp-cli $<TARGET_FILE:prometheus_xor2_chunk_cli>
                --go-oracle ${PXOR2_GO_ORACLE}
    )
    if(PXOR2_DATASETS_ROOT)
        add_test(
            NAME prometheus_xor2_chunk_dataset_validation
            COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/datasets/run_dataset_validation.py
                    --cpp-cli $<TARGET_FILE:prometheus_xor2_chunk_cli>
                    --go-oracle ${PXOR2_GO_ORACLE}
                    --datasets-root ${PXOR2_DATASETS_ROOT}
                    --json-output ${CMAKE_CURRENT_SOURCE_DIR}/validation/dataset_validation_result.json
        )
    endif()
endif()
