cmake_minimum_required(VERSION 3.22)
project(tsbench_fixed_batch_measurement LANGUAGES CXX)

# Build only the measurement driver; load codec modules from the frozen M3 build.
get_filename_component(repo "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
add_executable(tsbench_fixed_batch_corpus main.cpp "${repo}/native/runtime/plugin_loader.cpp")
target_include_directories(tsbench_fixed_batch_corpus PRIVATE "${repo}/native/runtime" "${repo}/include")
target_compile_features(tsbench_fixed_batch_corpus PRIVATE cxx_std_17)
set_target_properties(tsbench_fixed_batch_corpus PROPERTIES CXX_EXTENSIONS NO)
target_link_libraries(tsbench_fixed_batch_corpus PRIVATE ${CMAKE_DL_LIBS})
