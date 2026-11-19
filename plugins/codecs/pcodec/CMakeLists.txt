# Preserve the frozen full build. A reduced C-only build must not masquerade
# as these identities (both decode through the full public pc_* reader).
set(PC_SOURCE_BACKEND ON)
set(PC_NATIVE ON)
tsbench_frozen_source(pcodec-native pcodec_c)
if("pcodec-source-auto" IN_LIST BMK_SELECTED_PLUGIN_IDS)
  tsbench_codec_module(tsbench_pcodec_source_auto bmk_pcodec_source_auto adapter.cpp pcodec_c)
endif()
add_executable(tsbench_pcodec_batch_control EXCLUDE_FROM_ALL batch_control.c)
target_link_libraries(tsbench_pcodec_batch_control PRIVATE pcodec_c)
set_target_properties(tsbench_pcodec_batch_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
add_executable(tsbench_pcodec_pages_control EXCLUDE_FROM_ALL pages_control.cpp intmult_control.cpp)
target_link_libraries(tsbench_pcodec_pages_control PRIVATE pcodec_c)
set_target_properties(tsbench_pcodec_pages_control PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
  BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
if("pcodec-c-native-auto" IN_LIST BMK_SELECTED_PLUGIN_IDS)
  tsbench_codec_module(tsbench_pcodec_c_native_auto bmk_pcodec_c_native_auto adapter.cpp pcodec_c)
  target_compile_definitions(tsbench_pcodec_c_native_auto PRIVATE BMK_PCODEC_C_NATIVE=1)
endif()
