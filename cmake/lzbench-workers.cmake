# New corpus control, without changing frozen plugin/previous session identities.
if(TARGET lzbench_native AND TARGET tsbench_zstd)
  add_executable(tsbench_lzbench_corpus_worker_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/zstd/corpus_worker_control.cpp")
  target_link_libraries(tsbench_lzbench_corpus_worker_control PRIVATE lzbench_native)
  get_target_property(lzbench_worker_source lzbench_native SOURCE_DIR)
  target_include_directories(tsbench_lzbench_corpus_worker_control PRIVATE
    "${lzbench_worker_source}/vendor/lzbench/lz/xz/src/liblzma/api")
  target_compile_features(tsbench_lzbench_corpus_worker_control PRIVATE cxx_std_17)
  set_target_properties(tsbench_lzbench_corpus_worker_control PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_zstd>" CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endif()
