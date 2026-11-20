cmake_minimum_required(VERSION 3.22)
project(tsbench_column_batch_diagnostic LANGUAGES CXX)

# Load the already frozen public ABI modules; never overwrite a codec build.
get_filename_component(repo "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
add_executable(tsbench_column_batch main.cpp "${repo}/native/runtime/plugin_loader.cpp")
target_include_directories(tsbench_column_batch PRIVATE "${repo}/native/runtime" "${repo}/include")
target_compile_features(tsbench_column_batch PRIVATE cxx_std_17)
set_target_properties(tsbench_column_batch PROPERTIES CXX_EXTENSIONS NO)
target_link_libraries(tsbench_column_batch PRIVATE ${CMAKE_DL_LIBS})
