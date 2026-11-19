# Zstd and XZ use the same frozen lzbench library, even when enabled separately.
tsbench_frozen_source(lzbench-native lzbench_native)
if("zstd" IN_LIST BMK_SELECTED_PLUGIN_IDS)
  tsbench_codec_module(tsbench_zstd bmk_zstd adapter.cpp lzbench_native)
  target_include_directories(tsbench_zstd PRIVATE "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/zstd/lib")
  add_executable(tsbench_zstd_batch_control EXCLUDE_FROM_ALL direct_control.c)
  target_include_directories(tsbench_zstd_batch_control PRIVATE "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/zstd/lib")
  target_link_libraries(tsbench_zstd_batch_control PRIVATE lzbench_native)
  set_target_properties(tsbench_zstd_batch_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()
if("xz-baseline" IN_LIST BMK_SELECTED_PLUGIN_IDS)
  tsbench_codec_module(tsbench_xz_baseline bmk_xz_baseline xz_adapter.cpp lzbench_native)
  target_include_directories(tsbench_xz_baseline PRIVATE "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/xz/src/liblzma/api")
  add_executable(tsbench_xz_batch_control EXCLUDE_FROM_ALL xz_batch_control.cpp)
  target_include_directories(tsbench_xz_batch_control PRIVATE "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/xz/src/liblzma/api")
  target_link_libraries(tsbench_xz_batch_control PRIVATE lzbench_native)
  set_target_properties(tsbench_xz_batch_control PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

# Separate native byte-session observer; uses the same frozen DSO as both adapters.
add_executable(tsbench_lzbench_session_control EXCLUDE_FROM_ALL session_control.cpp)
target_link_libraries(tsbench_lzbench_session_control PRIVATE lzbench_native)
set_target_properties(tsbench_lzbench_session_control PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES
  CXX_EXTENSIONS NO BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")

# Identical frozen feature driver, linked beside the selected DSO for sealed use.
add_executable(tsbench_lzbench_feature_control EXCLUDE_FROM_ALL "${BMK_FROZEN_SOURCE}/tools/feature_worker.cpp")
add_executable(tsbench_lzbench_xz_sync_control EXCLUDE_FROM_ALL "${PROJECT_SOURCE_DIR}/tests/native/lzbench_contract.cpp")
target_include_directories(tsbench_lzbench_xz_sync_control PRIVATE
  "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/zstd/lib"
  "${BMK_FROZEN_SOURCE}/vendor/lzbench/lz/xz/src/liblzma/api")
foreach(control IN ITEMS tsbench_lzbench_feature_control tsbench_lzbench_xz_sync_control)
  target_link_libraries(${control} PRIVATE lzbench_native)
  set_target_properties(${control} PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endforeach()
