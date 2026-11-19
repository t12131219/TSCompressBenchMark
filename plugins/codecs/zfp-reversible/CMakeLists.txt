# Frozen CPU build: optional GPU capability is not part of this identity.
set(ZN_WITH_OPENMP ON)
set(ZN_WITH_CUDA OFF)
tsbench_frozen_source(zfp-native zfp_native_c)
tsbench_codec_module(tsbench_zfp_reversible bmk_zfp_reversible adapter.cpp zfp_native_c)

# Sealed direct controls; the OpenMP observer uses the same native block hooks as CTest.
add_executable(tsbench_zfp_native_control EXCLUDE_FROM_ALL native_control.cpp)
add_executable(tsbench_zfp_sealed_omp_control EXCLUDE_FROM_ALL "${PROJECT_SOURCE_DIR}/tests/native/zfp_omp_control.cpp")
target_link_libraries(tsbench_zfp_native_control PRIVATE zfp_native_c)
target_link_libraries(tsbench_zfp_sealed_omp_control PRIVATE zfp_native_c ${CMAKE_DL_LIBS})
set_target_properties(tsbench_zfp_sealed_omp_control PROPERTIES ENABLE_EXPORTS YES)
foreach(control tsbench_zfp_native_control tsbench_zfp_sealed_omp_control)
  target_compile_features(${control} PRIVATE cxx_std_17)
  set_target_properties(${control} PROPERTIES CXX_EXTENSIONS NO BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES)
endforeach()
