# M3 corpus drivers are separate from the frozen ABI plugin sources hashed in M0.
if(TARGET titchy_c)
  add_executable(tsbench_titchy_corpus_access_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/titchy-batch/corpus_access_control.cpp")
  target_link_libraries(tsbench_titchy_corpus_access_control PRIVATE titchy_c)
  set_target_properties(tsbench_titchy_corpus_access_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:titchy_c>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

if(TARGET titchy_c)
  add_executable(tsbench_titchy_corpus_stream_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/titchy-batch/corpus_stream_control.cpp")
  target_link_libraries(tsbench_titchy_corpus_stream_control PRIVATE titchy_c)
  set_target_properties(tsbench_titchy_corpus_stream_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:titchy_c>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

if(TARGET repaired_codec AND TARGET tsbench_sprintz_fire)
  add_executable(tsbench_sprintz_corpus_query_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/sprintz-fire/corpus_query_control.cpp")
  target_link_libraries(tsbench_sprintz_corpus_query_control PRIVATE repaired_codec)
  set_target_properties(tsbench_sprintz_corpus_query_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_sprintz_fire>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

if(TARGET gorilla_c AND TARGET tsbench_gorilla_tv)
  add_executable(tsbench_gorilla_corpus_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/gorilla-tv/corpus_control.cpp")
  target_link_libraries(tsbench_gorilla_corpus_control PRIVATE gorilla_c)
  set_target_properties(tsbench_gorilla_corpus_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_gorilla_tv>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

if(TARGET selfstar_c AND TARGET tsbench_selfstar_batch)
  add_executable(tsbench_selfstar_corpus_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/selfstar-batch/corpus_control.cpp")
  target_link_libraries(tsbench_selfstar_corpus_control PRIVATE selfstar_c)
  set_target_properties(tsbench_selfstar_corpus_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_selfstar_batch>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endif()

if(TARGET zfp_native_c AND TARGET tsbench_zfp_reversible)
  add_executable(tsbench_zfp_corpus_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/zfp-reversible/corpus_control.cpp")
  target_link_libraries(tsbench_zfp_corpus_control PRIVATE zfp_native_c)
  set_target_properties(tsbench_zfp_corpus_control PROPERTIES
    CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_zfp_reversible>"
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
  target_compile_options(tsbench_zfp_corpus_control PRIVATE -ffp-contract=off -fno-fast-math)
endif()
