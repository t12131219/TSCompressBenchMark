add_library(tsbench_raw_store SHARED raw_store.c)
target_link_libraries(tsbench_raw_store PRIVATE tsbench_plugin_abi)
set_target_properties(tsbench_raw_store PROPERTIES
  C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  C_VISIBILITY_PRESET hidden OUTPUT_NAME "bmk_raw_store")
