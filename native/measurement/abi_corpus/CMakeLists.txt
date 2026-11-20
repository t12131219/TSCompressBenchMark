cmake_minimum_required(VERSION 3.22)
project(tsbench_abi_corpus_diagnostic LANGUAGES CXX)

# Build only a measurement wrapper. Load the pre-existing, locked ABI modules
# in the isolated runtime; never rebuild/overwrite a historic codec artifact.
get_filename_component(repo "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
add_executable(tsbench_abi_corpus main.cpp "${repo}/native/runtime/plugin_loader.cpp")
target_include_directories(tsbench_abi_corpus PRIVATE "${repo}/native/runtime" "${repo}/include")
target_link_libraries(tsbench_abi_corpus PRIVATE ${CMAKE_DL_LIBS})
target_compile_features(tsbench_abi_corpus PRIVATE cxx_std_17)
set_target_properties(tsbench_abi_corpus PROPERTIES CXX_EXTENSIONS NO)
