# Package-specific development probes, not production build registration.
option(TSBENCH_CORAD_DIAGNOSTIC "Enable the CORAD source-side training diagnostic" OFF)
if(TSBENCH_CORAD_DIAGNOSTIC)
  add_subdirectory(tests/native/corad)
endif()

if(TARGET tsbench_corad_frozen)
  add_test(NAME tsbench.worker.corad-frozen.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/corad_worker_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_corad_frozen> $<TARGET_FILE:corad_c>
    "${CMAKE_CURRENT_BINARY_DIR}/corad-worker-control.json")
  set_tests_properties(tsbench.worker.corad-frozen.recovery PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_raw_store AND TARGET tsbench_zstd AND TARGET tsbench_alp_auto)
  function(tsbench_direct_control id plugin)
    set(target "tsbench_direct_${plugin}")
    add_executable(${target} native/worker/worker_main.cpp)
    target_compile_definitions(${target} PRIVATE TSBENCH_LINKED_ENTRY=1)
    target_link_libraries(${target} PRIVATE tsbench_plugin_loader ${plugin})
    target_link_options(${target} PRIVATE "LINKER:-z,now")
    set_target_properties(${target} PROPERTIES CXX_EXTENSIONS NO BUILD_RPATH_USE_ORIGIN YES
      BUILD_RPATH "$ORIGIN" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/codecs/${id}")
  endfunction()
  tsbench_direct_control(raw-store tsbench_raw_store)
  tsbench_direct_control(zstd tsbench_zstd)
  tsbench_direct_control(alp-auto tsbench_alp_auto)
  add_test(NAME tsbench.control.direct COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/direct_control.py" $<TARGET_FILE:tsbench_cpu_worker>
    --evidence "${CMAKE_CURRENT_BINARY_DIR}/direct-control.json"
    --method raw-store $<TARGET_FILE:tsbench_direct_tsbench_raw_store> $<TARGET_FILE:tsbench_raw_store>
    --method zstd $<TARGET_FILE:tsbench_direct_tsbench_zstd> $<TARGET_FILE:tsbench_zstd> $<TARGET_FILE:lzbench_native>
    --method alp-auto $<TARGET_FILE:tsbench_direct_tsbench_alp_auto> $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>)
  set_tests_properties(tsbench.control.direct PROPERTIES TIMEOUT 90 LABELS "direct-control")

  add_executable(tsbench_frame_batch_dlopen native/measurement/frame_batches.cpp)
  target_link_libraries(tsbench_frame_batch_dlopen PRIVATE tsbench_plugin_loader)
  set_target_properties(tsbench_frame_batch_dlopen PROPERTIES CXX_EXTENSIONS NO)
  function(tsbench_linked_frame_batch id plugin)
    set(target "tsbench_frame_batch_${plugin}")
    add_executable(${target} native/measurement/frame_batches.cpp)
    target_compile_definitions(${target} PRIVATE TSBENCH_BATCH_LINKED=1)
    target_link_libraries(${target} PRIVATE tsbench_plugin_loader ${plugin})
    target_link_options(${target} PRIVATE "LINKER:-z,now")
    set_target_properties(${target} PROPERTIES CXX_EXTENSIONS NO BUILD_RPATH_USE_ORIGIN YES
      BUILD_RPATH "$ORIGIN" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/codecs/${id}")
  endfunction()
  tsbench_linked_frame_batch(raw-store tsbench_raw_store)
  tsbench_linked_frame_batch(zstd tsbench_zstd)
  tsbench_linked_frame_batch(alp-auto tsbench_alp_auto)
  add_test(NAME tsbench.control.frame-batches COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/frame_batches.py" $<TARGET_FILE:tsbench_frame_batch_dlopen>
    --evidence "${CMAKE_CURRENT_BINARY_DIR}/frame-batches"
    --method raw-store $<TARGET_FILE:tsbench_frame_batch_tsbench_raw_store> $<TARGET_FILE:tsbench_raw_store>
    --method zstd $<TARGET_FILE:tsbench_frame_batch_tsbench_zstd> $<TARGET_FILE:tsbench_zstd> $<TARGET_FILE:lzbench_native>
    --method alp-auto $<TARGET_FILE:tsbench_frame_batch_tsbench_alp_auto> $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>)
  set_tests_properties(tsbench.control.frame-batches PROPERTIES TIMEOUT 120 LABELS "direct-control")
endif()

if(TARGET lzbench_native)
  add_executable(tsbench_lzbench_contract tests/native/lzbench_contract.cpp)
  target_link_libraries(tsbench_lzbench_contract PRIVATE lzbench_native)
  get_target_property(lzbench_source_dir lzbench_native SOURCE_DIR)
  target_include_directories(tsbench_lzbench_contract PRIVATE "${lzbench_source_dir}/vendor/lzbench/lz/zstd/lib"
    "${lzbench_source_dir}/vendor/lzbench/lz/xz/src/liblzma/api")
  set_target_properties(tsbench_lzbench_contract PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO)
  # The frozen worker is EXCLUDE_FROM_ALL in the source subproject. Build it
  # only for this direct diagnostic, not for the production worker.
  add_dependencies(tsbench_lzbench_contract feature_worker)
  add_test(NAME tsbench.control.lzbench COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/lzbench_native_probe.py"
    $<TARGET_FILE:tsbench_lzbench_contract> $<TARGET_FILE:feature_worker> $<TARGET_FILE:lzbench_native>
    --evidence "${CMAKE_CURRENT_BINARY_DIR}/lzbench-native-probe")
  set_tests_properties(tsbench.control.lzbench PROPERTIES TIMEOUT 90 LABELS "direct-control")
endif()

if(TARGET tsbench_gorilla_tv)
  add_executable(tsbench_gorilla_work_control tests/native/gorilla_work_control.c)
  set_target_properties(tsbench_gorilla_work_control PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES
    ENABLE_EXPORTS YES BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN")
  target_compile_definitions(tsbench_gorilla_work_control PRIVATE _GNU_SOURCE)
  target_compile_options(tsbench_gorilla_work_control PRIVATE -fno-builtin-memcpy)
  target_link_libraries(tsbench_gorilla_work_control PRIVATE gorilla_c ${CMAKE_DL_LIBS})
  add_test(NAME tsbench.worker.gorilla-tv.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/gorilla_tv_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_gorilla_tv> $<TARGET_FILE:gorilla_c>
    $<TARGET_FILE:tsbench_gorilla_work_control>
    "${CMAKE_CURRENT_BINARY_DIR}/gorilla-tv-control")
  set_tests_properties(tsbench.worker.gorilla-tv.recovery PROPERTIES TIMEOUT 45 LABELS "direct-control")
endif()

if(TARGET tsbench_pcodec_source_auto AND TARGET tsbench_pcodec_c_native_auto)
  add_test(NAME tsbench.worker.pcodec.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/pcodec_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_pcodec_source_auto>
    $<TARGET_FILE:tsbench_pcodec_c_native_auto> $<TARGET_FILE:pcodec_c>
    "${CMAKE_CURRENT_BINARY_DIR}/pcodec-control.json")
  set_tests_properties(tsbench.worker.pcodec.recovery PROPERTIES TIMEOUT 45 LABELS "direct-control")
endif()

if(TARGET tsbench_titchy_batch)
  add_test(NAME tsbench.worker.titchy.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/titchy_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_titchy_batch> $<TARGET_FILE:titchy_c>
    "${CMAKE_CURRENT_BINARY_DIR}/titchy-control.json")
  set_tests_properties(tsbench.worker.titchy.recovery PROPERTIES TIMEOUT 45 LABELS "direct-control")
endif()

if(TARGET tsbench_zfp_reversible)
  add_executable(tsbench_zfp_omp_control tests/native/zfp_omp_control.cpp)
  target_link_libraries(tsbench_zfp_omp_control PRIVATE zfp_native_c ${CMAKE_DL_LIBS})
  target_compile_features(tsbench_zfp_omp_control PRIVATE cxx_std_17)
  set_target_properties(tsbench_zfp_omp_control PROPERTIES ENABLE_EXPORTS YES CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
  add_test(NAME tsbench.worker.zfp.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/zfp_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_zfp_reversible> $<TARGET_FILE:zfp_native_c>
    $<TARGET_FILE:tsbench_zfp_omp_control> "${CMAKE_CURRENT_BINARY_DIR}/zfp-control.json")
  set_tests_properties(tsbench.worker.zfp.recovery PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_gorilla_t_derived AND TARGET tsbench_gorilla_v_derived AND TARGET gorilla_c)
  add_test(NAME tsbench.worker.gorilla-derived.differential COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/gorilla_roles.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_gorilla_t_derived>
    $<TARGET_FILE:tsbench_gorilla_v_derived> $<TARGET_FILE:gorilla_c>
    "${CMAKE_CURRENT_BINARY_DIR}/gorilla-role-control")
  set_tests_properties(tsbench.worker.gorilla-derived.differential PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_alp_auto)
  add_test(NAME tsbench.worker.alp-auto.branches COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/alp_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>
    "${CMAKE_CURRENT_BINARY_DIR}/alp-native-control")
  set_tests_properties(tsbench.worker.alp-auto.branches PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_alp_auto AND TARGET tsbench_zstd AND TARGET tsbench_gorilla_tv)
  add_test(NAME tsbench.worker.method-boundaries COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/method_boundaries.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>
    $<TARGET_FILE:tsbench_zstd> $<TARGET_FILE:lzbench_native>
    $<TARGET_FILE:tsbench_gorilla_tv> $<TARGET_FILE:gorilla_c>
    "${CMAKE_CURRENT_BINARY_DIR}/method-boundaries")
  set_tests_properties(tsbench.worker.method-boundaries PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_selfstar_batch)
  add_test(NAME tsbench.worker.selfstar-batch.ordered COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/selfstar_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_selfstar_batch> $<TARGET_FILE:selfstar_c>
    "${CMAKE_CURRENT_BINARY_DIR}/selfstar-control.json")
  set_tests_properties(tsbench.worker.selfstar-batch.ordered PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_huff0_reference)
  add_executable(tsbench_huff0_control tests/native/huff0_control.cpp)
  target_link_libraries(tsbench_huff0_control PRIVATE reference ${CMAKE_DL_LIBS})
  target_compile_features(tsbench_huff0_control PRIVATE cxx_std_17)
  target_compile_definitions(tsbench_huff0_control PRIVATE TSBENCH_ENTROPY_DYNAMIC_BMI2=$<BOOL:${ENTROPY_DYNAMIC_BMI2}>)
  set_target_properties(tsbench_huff0_control PROPERTIES ENABLE_EXPORTS YES CXX_EXTENSIONS NO
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/codecs/huff0-reference")
  add_test(NAME tsbench.worker.huff0.profiles COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/huff0_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_huff0_reference> $<TARGET_FILE:reference>
    $<TARGET_FILE:tsbench_huff0_control> "${CMAKE_CURRENT_BINARY_DIR}/huff0-control.json")
  set_tests_properties(tsbench.worker.huff0.profiles PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_pbepla_rr)
  add_executable(tsbench_pbepla_replay_control tests/native/pbepla_replay_control.cpp)
  target_link_libraries(tsbench_pbepla_replay_control PRIVATE tba_native ${CMAKE_DL_LIBS})
  target_compile_features(tsbench_pbepla_replay_control PRIVATE cxx_std_17)
  set_target_properties(tsbench_pbepla_replay_control PROPERTIES ENABLE_EXPORTS YES CXX_EXTENSIONS NO
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/codecs/pbepla-rr")
  add_test(NAME tsbench.worker.pbepla.progressive COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/pbepla_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_pbepla_rr> $<TARGET_FILE:tba_native>
    $<TARGET_FILE:tsbench_pbepla_replay_control> "${CMAKE_CURRENT_BINARY_DIR}/pbepla-control.json")
  set_tests_properties(tsbench.worker.pbepla.progressive PROPERTIES TIMEOUT 60 LABELS "direct-control")
endif()

if(TARGET tsbench_sprintz_fire)
  add_executable(tsbench_sprintz_control tests/native/sprintz_control.cpp)
  target_link_libraries(tsbench_sprintz_control PRIVATE repaired_codec)
  target_include_directories(tsbench_sprintz_control PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/plugins/codecs/sprintz-fire")
  set_target_properties(tsbench_sprintz_control PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO
    BUILD_RPATH_USE_ORIGIN YES BUILD_RPATH "$ORIGIN" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/codecs/sprintz-fire")
  add_test(NAME tsbench.worker.sprintz-fire.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/worker_process.py"
    sprintz-fire $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_sprintz_fire> $<TARGET_FILE:repaired_codec>
    --native-control $<TARGET_FILE:tsbench_sprintz_control>
    --evidence "${CMAKE_CURRENT_BINARY_DIR}/sprintz-native-control.json")
  set_tests_properties(tsbench.worker.sprintz-fire.recovery PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 45 LABELS "direct-control")
endif()

if(TARGET tsbench_raw_store AND TARGET tsbench_zstd AND TARGET tsbench_alp_auto)
  add_executable(tsbench_m1_isolation_control EXCLUDE_FROM_ALL tests/native/smoke_isolation_control.cpp)
  target_link_libraries(tsbench_m1_isolation_control PRIVATE tsbench_plugin_loader)
  add_test(NAME tsbench.application.smoke COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/smoke_execution.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_raw_store>
    $<TARGET_FILE:tsbench_zstd> $<TARGET_FILE:lzbench_native>
    $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>)
  set_tests_properties(tsbench.application.smoke PROPERTIES TIMEOUT 45)
endif()

if(TARGET tsbench_raw_store)
  foreach(kind RANGE 1 4)
    add_library(tsbench_invalid_plugin_${kind} MODULE tests/contracts/bad_plugin.c)
    target_link_libraries(tsbench_invalid_plugin_${kind} PRIVATE tsbench_plugin_abi)
    target_compile_definitions(tsbench_invalid_plugin_${kind} PRIVATE BAD_PLUGIN=${kind})
  endforeach()
  add_executable(tsbench_plugin_runtime tests/contracts/plugin_runtime.cpp)
  target_link_libraries(tsbench_plugin_runtime PRIVATE tsbench_plugin_loader)
  add_test(NAME tsbench.abi.runtime COMMAND tsbench_plugin_runtime
    $<TARGET_FILE:tsbench_raw_store> $<TARGET_FILE:tsbench_invalid_plugin_1>
    $<TARGET_FILE:tsbench_invalid_plugin_2> $<TARGET_FILE:tsbench_invalid_plugin_3>
    $<TARGET_FILE:tsbench_invalid_plugin_4> "${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/bad_plugin.c")
  add_test(NAME tsbench.worker.raw-store.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/worker_process.py"
    raw-store $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_raw_store>)
endif()

if(TARGET tsbench_zstd)
  add_test(NAME tsbench.worker.zstd.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/worker_process.py"
    zstd $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_zstd> $<TARGET_FILE:lzbench_native>)
endif()

if(TARGET tsbench_xz_baseline)
  add_test(NAME tsbench.worker.xz-baseline.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/xz_control.py"
    $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_xz_baseline> $<TARGET_FILE:lzbench_native>
    "${CMAKE_CURRENT_BINARY_DIR}/xz-control.json")
  set_tests_properties(tsbench.worker.xz-baseline.recovery PROPERTIES TIMEOUT 45 LABELS "direct-control")
endif()

if(TARGET tsbench_alp_auto)
  add_test(NAME tsbench.worker.alp-auto.recovery COMMAND "${Python3_EXECUTABLE}" -I -B
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/isolation/worker_process.py"
    alp-auto $<TARGET_FILE:tsbench_cpu_worker> $<TARGET_FILE:tsbench_alp_auto> $<TARGET_FILE:alp_native>)
endif()
