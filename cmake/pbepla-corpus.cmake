# Development/real-corpus control, not part of the locked ABI plugin source.
if(TARGET tba_native AND TARGET tsbench_pbepla_rr)
  add_executable(tsbench_pbepla_corpus_control EXCLUDE_FROM_ALL
      "${PROJECT_SOURCE_DIR}/plugins/codecs/pbepla-rr/corpus_control.cpp")
  target_link_libraries(tsbench_pbepla_corpus_control PRIVATE tba_native ${CMAKE_DL_LIBS})
  target_compile_features(tsbench_pbepla_corpus_control PRIVATE cxx_std_17)
  target_compile_options(tsbench_pbepla_corpus_control PRIVATE -ffp-contract=off -fno-fast-math)
  set_target_properties(tsbench_pbepla_corpus_control PROPERTIES ENABLE_EXPORTS YES
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_pbepla_rr>"
    CXX_EXTENSIONS NO BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endif()
