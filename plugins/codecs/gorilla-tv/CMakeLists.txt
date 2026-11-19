tsbench_frozen_source(gorilla-native gorilla_c)
tsbench_codec_module(tsbench_gorilla_tv bmk_gorilla_tv adapter.cpp gorilla_c)

# Independent direct C entry; not part of the plugin API or performance path.
add_executable(tsbench_gorilla_batch_control EXCLUDE_FROM_ALL direct_control.c state_control.c)
target_link_libraries(tsbench_gorilla_batch_control PRIVATE gorilla_c)
set_target_properties(tsbench_gorilla_batch_control PROPERTIES
  C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")

# The development CTest observer keeps its historic path. For the sealed
# closure, build the same diagnostic beside its DSO so RUNPATH is local.
add_executable(tsbench_gorilla_sealed_work_control EXCLUDE_FROM_ALL
  "${PROJECT_SOURCE_DIR}/tests/native/gorilla_work_control.c")
set_target_properties(tsbench_gorilla_sealed_work_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES
  ENABLE_EXPORTS YES BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
target_compile_definitions(tsbench_gorilla_sealed_work_control PRIVATE _GNU_SOURCE)
target_compile_options(tsbench_gorilla_sealed_work_control PRIVATE -fno-builtin-memcpy)
target_link_libraries(tsbench_gorilla_sealed_work_control PRIVATE gorilla_c ${CMAKE_DL_LIBS})
