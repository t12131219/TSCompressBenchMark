tsbench_extract_frozen_source(elf-selfstar-native)
# The unmodified release also creates a globally named bench_c target, which
# collides with pcodec. Build only the frozen selfstar_c library with the
# release's C11 and floating-point flags, not its standalone benchmark tool.
add_library(selfstar_c SHARED "${BMK_FROZEN_SOURCE}/src/selfstar.c")
set_target_properties(selfstar_c PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)
target_include_directories(selfstar_c PUBLIC "${BMK_FROZEN_SOURCE}/include" PRIVATE "${BMK_FROZEN_SOURCE}/src")
target_compile_options(selfstar_c PRIVATE -ffp-contract=off -fno-fast-math)
target_link_options(selfstar_c PRIVATE "LINKER:--no-undefined")
target_link_libraries(selfstar_c PUBLIC m)
tsbench_codec_module(tsbench_selfstar_batch bmk_selfstar_batch adapter.cpp selfstar_c)
# Direct native lifecycle control is not part of the plugin or benchmark clock.
add_executable(tsbench_selfstar_ordered_control EXCLUDE_FROM_ALL ordered_control.cpp)
target_compile_features(tsbench_selfstar_ordered_control PRIVATE cxx_std_17)
target_link_libraries(tsbench_selfstar_ordered_control PRIVATE selfstar_c)
set_target_properties(tsbench_selfstar_ordered_control PROPERTIES BUILD_RPATH_USE_ORIGIN YES)
