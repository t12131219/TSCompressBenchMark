if(TARGET reference AND TARGET tsbench_huff0_reference)
  add_executable(tsbench_huff0_corpus_table_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/plugins/codecs/huff0-reference/corpus_table_control.cpp")
  target_link_libraries(tsbench_huff0_corpus_table_control PRIVATE reference)
  target_compile_features(tsbench_huff0_corpus_table_control PRIVATE cxx_std_17)
  set_target_properties(tsbench_huff0_corpus_table_control PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_huff0_reference>" CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endif()
