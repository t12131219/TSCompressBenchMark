# Regenerate only from the locked local parent; never link the TV library.
tsbench_extract_frozen_source(gorilla-native)
set(extract "${PROJECT_SOURCE_DIR}/tools/extract_gorilla_bit_io.py")
set(parent "${BMK_FROZEN_SOURCE}/src/gorilla.c")
set(output "${CMAKE_CURRENT_BINARY_DIR}/unique_gorilla_bits.inc")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${extract}" "${parent}")
execute_process(COMMAND "${Python3_EXECUTABLE}" -I -B "${extract}" "${parent}" "${output}"
    COMMAND_ERROR_IS_FATAL ANY)

function(bmk_gorilla_derived role timestamp)
  set(target "tsbench_gorilla_${role}_derived")
  if("gorilla-${role}-derived" IN_LIST BMK_SELECTED_PLUGIN_IDS)
    add_library(${target} SHARED adapter.cpp column.c)
    target_compile_definitions(${target} PRIVATE BMK_GORILLA_TIMESTAMP=${timestamp})
    target_link_libraries(${target} PRIVATE tsbench_plugin_abi)
    target_include_directories(${target} PRIVATE "${PROJECT_SOURCE_DIR}/plugins/codecs/common" "${CMAKE_CURRENT_BINARY_DIR}")
    set_target_properties(${target} PROPERTIES OUTPUT_NAME "bmk_gorilla_${role}_derived"
      C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO CXX_EXTENSIONS NO
      C_VISIBILITY_PRESET hidden CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
  endif()
endfunction()
bmk_gorilla_derived(t 1)
bmk_gorilla_derived(v 0)
