tsbench_frozen_source(alp-native alp_native)
tsbench_codec_module(tsbench_alp_auto bmk_alp_auto adapter.cpp alp_native)

add_executable(tsbench_alp_fenv_control EXCLUDE_FROM_ALL fenv_control.c)
target_link_libraries(tsbench_alp_fenv_control PRIVATE alp_native m)
set_target_properties(tsbench_alp_fenv_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")

add_executable(tsbench_alp_decode_control EXCLUDE_FROM_ALL decode_control.c)
target_link_libraries(tsbench_alp_decode_control PRIVATE alp_native)
set_target_properties(tsbench_alp_decode_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES
  C_EXTENSIONS NO BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
