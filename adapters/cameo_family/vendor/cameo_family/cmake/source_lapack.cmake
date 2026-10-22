# SPDX-License-Identifier: Apache-2.0
# Offline, source-built ILP64 numerical dependency. No Python or Fortran runtime.
include(ExternalProject)
set(CF_LAPACK_LIBRARY "" CACHE FILEPATH "Explicit ILP64 archive; empty builds frozen source")
set(CF_DGELSD_SYMBOL "dgelsd_" CACHE STRING "Numerical entry point")
if(NOT CF_LAPACK_LIBRARY)
 if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
  set(cf_blas_target PRESCOTT)
  set(cf_blas_dynamic ON)
  set(cf_blas_other_types ON)
 elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  set(cf_blas_target ARMV8)
  set(cf_blas_dynamic OFF)
  set(cf_blas_other_types OFF)
 else()
  message(FATAL_ERROR "Unqualified numerical architecture: ${CMAKE_SYSTEM_PROCESSOR}")
 endif()
 option(CF_NUMERIC_DYNAMIC "Keep OpenBLAS native dispatch; OFF forces the platform baseline" ${cf_blas_dynamic})
 set(cf_blas_dynamic ${CF_NUMERIC_DYNAMIC})
 set(cf_blas_other_types ${CF_NUMERIC_DYNAMIC})
 set(cf_lapack_flags "-ffp-contract=off -ffile-prefix-map=${CMAKE_BINARY_DIR}=cf-build")
 if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  string(APPEND cf_lapack_flags " -DUSE64BITINT")
 endif()
 if(CF_ASAN)
  string(APPEND cf_lapack_flags " -fsanitize=address,undefined -fno-omit-frame-pointer")
 elseif(CF_TSAN)
  string(APPEND cf_lapack_flags " -fsanitize=thread -fno-omit-frame-pointer")
 endif()
 set(cf_toolchain_args)
 if(CMAKE_CROSSCOMPILING)
  list(APPEND cf_toolchain_args "-DCMAKE_TOOLCHAIN_FILE=${CMAKE_TOOLCHAIN_FILE}")
 endif()
 ExternalProject_Add(cf_lapack_source
  URL "${CMAKE_CURRENT_SOURCE_DIR}/vendor/openblas/OpenBLAS-0.3.21.tar.gz"
  URL_HASH SHA256=f36ba3d7a60e7c8bcc54cd9aaa9b1223dd42eaf02c811791c37e8ca707c241ca
  PREFIX "${CMAKE_CURRENT_BINARY_DIR}/numeric"
  PATCH_COMMAND ${CMAKE_COMMAND} -DCF_BLAS_PATCH_REV=3 -DCF_BLAS_SOURCE_DIR=<SOURCE_DIR> -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/openblas_native_fma.cmake"
  CMAKE_ARGS ${cf_toolchain_args}
   "-DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}" "-DCMAKE_ASM_COMPILER=${CMAKE_C_COMPILER}"
   -DCMAKE_Fortran_COMPILER=NOTFOUND -DNOFORTRAN=ON
   -DCMAKE_BUILD_TYPE=Release "-DCMAKE_C_FLAGS=${cf_lapack_flags}"
   -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF
   -DBUILD_TESTING=OFF -DC_LAPACK=ON -DINTERFACE64=ON
   "-DBUILD_SINGLE=${cf_blas_other_types}" -DBUILD_DOUBLE=ON "-DBUILD_COMPLEX=${cf_blas_other_types}" "-DBUILD_COMPLEX16=${cf_blas_other_types}"
   -DNO_LAPACKE=ON -DUSE_THREAD=OFF -DUSE_LOCKING=ON -DNUM_THREADS=2
   "-DTARGET=${cf_blas_target}" "-DDYNAMIC_ARCH=${cf_blas_dynamic}" -DDYNAMIC_OLDER=ON
  BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> --parallel 4
  INSTALL_COMMAND ""
  BUILD_BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/numeric/src/cf_lapack_source-build/lib/libopenblas_64.a")
 ExternalProject_Add_StepDependencies(cf_lapack_source patch "${CMAKE_CURRENT_SOURCE_DIR}/cmake/openblas_native_fma.cmake")
 set(CF_LAPACK_LIBRARY "${CMAKE_CURRENT_BINARY_DIR}/numeric/src/cf_lapack_source-build/lib/libopenblas_64.a")
endif()
add_library(cf_lapack STATIC IMPORTED GLOBAL)
set_target_properties(cf_lapack PROPERTIES IMPORTED_LOCATION "${CF_LAPACK_LIBRARY}"
 INTERFACE_LINK_LIBRARIES "m;pthread")
if(TARGET cf_lapack_source)
 add_dependencies(cf_lapack cf_lapack_source)
endif()
