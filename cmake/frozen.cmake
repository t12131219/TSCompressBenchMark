# Extract only from the verified local archive, with no alternate source override.
function(tsbench_extract_frozen_source source_id)
  set(root "${PROJECT_SOURCE_DIR}")
  set(out "${CMAKE_CURRENT_BINARY_DIR}/source")
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${root}/third_party/sources.lock.json"
    "${root}/third_party/archives/${source_id}-source-unique-v1.tar.gz"
    "${root}/third_party/provenance/${source_id}/source-manifest.json"
    "${root}/third_party/provenance/${source_id}/unique-validation.json"
    "${root}/catalog/selections/unique-v1.csv" "${root}/catalog/selections/unique-v1.manifest.json"
    "${root}/tools/prepare_plugin_source.py" "${root}/tools/probe_release_builds.py")
  execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${root}/tools/prepare_plugin_source.py"
    "${source_id}" "${out}" COMMAND_ERROR_IS_FATAL ANY)
  if(CMAKE_SKIP_RPATH OR CMAKE_SKIP_BUILD_RPATH)
    message(FATAL_ERROR "A relocatable plugin build requires build RPATH")
  endif()
  set(BMK_FROZEN_SOURCE "${out}/${source_id}" PARENT_SCOPE)
endfunction()

function(tsbench_frozen_source source_id target)
  tsbench_extract_frozen_source("${source_id}")
  add_subdirectory("${BMK_FROZEN_SOURCE}" "${CMAKE_CURRENT_BINARY_DIR}/upstream" EXCLUDE_FROM_ALL)
  set_target_properties(${target} PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
  set(BMK_FROZEN_SOURCE "${BMK_FROZEN_SOURCE}" PARENT_SCOPE)
endfunction()

function(tsbench_codec_module target output source frozen_target)
  add_library(${target} SHARED "${source}")
  target_link_libraries(${target} PRIVATE tsbench_plugin_abi ${frozen_target})
  target_include_directories(${target} PRIVATE "${PROJECT_SOURCE_DIR}/plugins/codecs/common")
  set_target_properties(${target} PROPERTIES OUTPUT_NAME "${output}" CXX_EXTENSIONS NO
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
endfunction()
