if(TARGET tsbench_huff0_reference)
  add_executable(tsbench_huff0_fec1_control EXCLUDE_FROM_ALL
    "${PROJECT_SOURCE_DIR}/native/worker/huff0_fec1_control.cpp")
  target_link_libraries(tsbench_huff0_fec1_control PRIVATE tsbench_plugin_loader tsbench_huff0_reference)
  set_target_properties(tsbench_huff0_fec1_control PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:tsbench_huff0_reference>" CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endif()
