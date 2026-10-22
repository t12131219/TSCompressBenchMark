# SPDX-License-Identifier: Apache-2.0
# Preserve the upstream AVX-512 reduction's fused multiply/add semantics.
# The translated codec and scalar numerical baseline retain contraction=off.
set(cf_kernel_file "${CF_BLAS_SOURCE_DIR}/kernel/CMakeLists.txt")
file(READ "${cf_kernel_file}" cf_kernel_text)
# Upgrade an earlier overlay produced under OpenBLAS's old CMP0054 policy.
string(REPLACE "if(TARGET_CORE STREQUAL \"SKYLAKEX\" OR TARGET_CORE STREQUAL \"COOPERLAKE\")"
 "if(\"cf\${TSUFFIX}\" STREQUAL \"cf_SKYLAKEX\" OR \"cf\${TSUFFIX}\" STREQUAL \"cf_COOPERLAKE\")" cf_kernel_text "${cf_kernel_text}")
file(WRITE "${cf_kernel_file}" "${cf_kernel_text}")
set(cf_fma_marker "# CAMEO native AVX512 FMA parity")
if(NOT cf_kernel_text MATCHES "${cf_fma_marker}")
 set(cf_anchor "    add_library(kernel\${TSUFFIX} OBJECT \${OPENBLAS_SRC})")
 string(FIND "${cf_kernel_text}" "${cf_anchor}" cf_found)
 if(cf_found EQUAL -1)
  message(FATAL_ERROR "Frozen OpenBLAS kernel recipe differs")
 endif()
 set(cf_replacement "${cf_anchor}\n${cf_fma_marker}\n    if(\"cf\${TSUFFIX}\" STREQUAL \"cf_SKYLAKEX\" OR \"cf\${TSUFFIX}\" STREQUAL \"cf_COOPERLAKE\")\n      target_compile_options(kernel\${TSUFFIX} PRIVATE $<$<COMPILE_LANGUAGE:C>:-ffp-contract=fast>)\n    endif()")
 string(REPLACE "${cf_anchor}" "${cf_replacement}" cf_kernel_text "${cf_kernel_text}")
 file(WRITE "${cf_kernel_file}" "${cf_kernel_text}")
endif()
