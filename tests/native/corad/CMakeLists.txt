# Keep the original native controls usable without the optional worker route.
if(NOT TARGET corad_c)
  tsbench_frozen_source(corad-native corad_c)
endif()
get_target_property(corad_source corad_c SOURCE_DIR)
add_custom_target(tsbench_corad_diagnostic ALL DEPENDS corad_c)
add_test(NAME tsbench.control.corad COMMAND "${Python3_EXECUTABLE}" -I -B
  "${PROJECT_SOURCE_DIR}/tests/isolation/corad_native_control.py" --build-inputs
  $<TARGET_FILE:corad_c> "${corad_source}/source_backend/train.py"
  "${PROJECT_BINARY_DIR}/corad-native-control")
set_tests_properties(tsbench.control.corad PROPERTIES TIMEOUT 90 LABELS "direct-control")
