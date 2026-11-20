cmake_minimum_required(VERSION 3.20)
project(TSBenchMatchedAbi LANGUAGES CXX)

# Separate development build: never replace an already frozen worker binary.
get_filename_component(TSBENCH_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(worker_source "${TSBENCH_ROOT}/native/worker/worker_main.cpp")
set_source_files_properties("${worker_source}" PROPERTIES COMPILE_DEFINITIONS "main=tsbench_matched_worker_main")
add_executable(tsbench_matched_abi_worker main.cpp "${worker_source}" "${TSBENCH_ROOT}/native/runtime/plugin_loader.cpp")
target_compile_features(tsbench_matched_abi_worker PRIVATE cxx_std_17)
set_target_properties(tsbench_matched_abi_worker PROPERTIES CXX_EXTENSIONS NO)
target_include_directories(tsbench_matched_abi_worker PRIVATE "${TSBENCH_ROOT}/include" "${TSBENCH_ROOT}/native/runtime" ../common)
target_link_libraries(tsbench_matched_abi_worker PRIVATE ${CMAKE_DL_LIBS})
