cmake_minimum_required(VERSION 3.16)
project(abba_rewrite LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(ABBA_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
set(ABBA_SOURCE_ROOT "" CACHE PATH "Optional frozen ABBA upstream snapshot")
set(ABBA_DATASETS_ROOT "" CACHE PATH "Optional read-only project datasets directory")

add_library(abba_ckmeans STATIC
    src/canonical/ckmeans/Ckmeans.1d.dp.cpp
    src/canonical/ckmeans/dynamic_prog.cpp
    src/canonical/ckmeans/fill_SMAWK.cpp
    src/canonical/ckmeans/fill_log_linear.cpp
    src/canonical/ckmeans/fill_quadratic.cpp
    src/canonical/ckmeans/select_levels.cpp
)
set_target_properties(abba_ckmeans PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_include_directories(abba_ckmeans PUBLIC src/canonical/ckmeans)
target_compile_features(abba_ckmeans PUBLIC cxx_std_17)
target_compile_options(abba_ckmeans PRIVATE -Wall -Wextra -Wpedantic)

add_library(abba STATIC src/canonical/abba.cpp)
set_target_properties(abba PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_include_directories(abba PUBLIC include PRIVATE src/canonical)
target_compile_features(abba PUBLIC cxx_std_17)
target_compile_options(abba PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
target_link_libraries(abba PUBLIC abba_ckmeans)

if(ABBA_ENABLE_SANITIZERS)
    foreach(target abba_ckmeans abba)
        target_compile_options(${target} PUBLIC
            -fsanitize=address,undefined -fno-omit-frame-pointer
        )
        target_link_options(${target} PUBLIC
            -fsanitize=address,undefined -fno-omit-frame-pointer
        )
    endforeach()
endif()

enable_testing()
add_executable(abba_tests tests/unit/test_abba.cpp)
target_link_libraries(abba_tests PRIVATE abba)
target_compile_options(abba_tests PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
add_test(NAME abba_tests COMMAND abba_tests)

add_executable(abba_cli tests/cross_decode/abba_cli.cpp)
target_link_libraries(abba_cli PRIVATE abba)
target_compile_options(abba_cli PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)

add_library(abba_c SHARED src/standalone/abba_c.cpp)
set_target_properties(abba_c PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_definitions(abba_c PRIVATE ABBA_C_BUILD)
target_link_libraries(abba_c PRIVATE abba)
target_include_directories(abba_c PUBLIC include)
target_compile_features(abba_c PRIVATE cxx_std_17)
target_compile_options(abba_c PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
if(UNIX AND NOT APPLE)
    target_link_options(abba_c PRIVATE
        "-Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/src/standalone/abba.exports.map"
    )
endif()

add_executable(abba_standalone_preflight
    tests/qualification/standalone_preflight.cpp
)
target_link_libraries(abba_standalone_preflight PRIVATE abba_c)
target_compile_options(abba_standalone_preflight PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)
if(ABBA_ENABLE_SANITIZERS)
    target_compile_options(abba_standalone_preflight PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
    target_link_options(abba_standalone_preflight PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
endif()
add_test(NAME abba_standalone_preflight COMMAND abba_standalone_preflight)

add_executable(abba_c_header_smoke tests/qualification/c_header_smoke.c)
target_link_libraries(abba_c_header_smoke PRIVATE abba_c)
target_compile_features(abba_c_header_smoke PRIVATE c_std_11)
target_compile_options(abba_c_header_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(ABBA_ENABLE_SANITIZERS)
    target_compile_options(abba_c_header_smoke PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
    target_link_options(abba_c_header_smoke PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
    )
endif()
add_test(NAME abba_c_header_smoke COMMAND abba_c_header_smoke)

add_executable(abba_performance tests/performance/benchmark.cpp)
target_link_libraries(abba_performance PRIVATE abba)
target_compile_options(abba_performance PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
)

find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND AND ABBA_SOURCE_ROOT)
    add_executable(abba_source_ckmeans_oracle
        tests/oracle/ckmeans_oracle_cli.cpp
        ${ABBA_SOURCE_ROOT}/src/Ckmeans.1d.dp.cpp
        ${ABBA_SOURCE_ROOT}/src/dynamic_prog.cpp
        ${ABBA_SOURCE_ROOT}/src/fill_SMAWK.cpp
        ${ABBA_SOURCE_ROOT}/src/fill_log_linear.cpp
        ${ABBA_SOURCE_ROOT}/src/fill_quadratic.cpp
        ${ABBA_SOURCE_ROOT}/src/select_levels.cpp
    )
    target_include_directories(abba_source_ckmeans_oracle PRIVATE ${ABBA_SOURCE_ROOT}/src)
    target_compile_features(abba_source_ckmeans_oracle PRIVATE cxx_std_11)

    add_test(
        NAME abba_golden_and_differential
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/cross_decode/run_differential.py
                --cpp-cli $<TARGET_FILE:abba_cli>
                --oracle ${CMAKE_CURRENT_SOURCE_DIR}/tests/oracle/abba_oracle.py
                --ckmeans-cli $<TARGET_FILE:abba_source_ckmeans_oracle>
                --vectors ${CMAKE_CURRENT_SOURCE_DIR}/tests/golden/abba_vectors.json
    )
    add_test(
        NAME abba_native_capability_validation
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/capability/run_capability_validation.py
                --cpp-cli $<TARGET_FILE:abba_cli>
                --source-root ${ABBA_SOURCE_ROOT}
    )
    if(ABBA_DATASETS_ROOT)
        add_test(
            NAME abba_dataset_validation
            COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/datasets/run_dataset_validation.py
                    --cpp-cli $<TARGET_FILE:abba_cli>
                    --oracle ${CMAKE_CURRENT_SOURCE_DIR}/tests/oracle/abba_oracle.py
                    --ckmeans-cli $<TARGET_FILE:abba_source_ckmeans_oracle>
                    --datasets-root ${ABBA_DATASETS_ROOT}
                    --json-output ${CMAKE_CURRENT_SOURCE_DIR}/validation/dataset_validation_result.json
        )
    endif()
endif()
