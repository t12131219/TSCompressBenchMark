# Keep new corpus controls outside the build-identity inputs of the baseline ABI plugins.
if(TARGET lzbench_native AND TARGET tsbench_zstd)
  add_executable(tsbench_lzbench_corpus_session_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/zstd/corpus_session_control.cpp")
  target_link_libraries(tsbench_lzbench_corpus_session_control PRIVATE lzbench_native)
  target_compile_features(tsbench_lzbench_corpus_session_control PRIVATE cxx_std_17)
  set_target_properties(tsbench_lzbench_corpus_session_control PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_zstd>" CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endif()
