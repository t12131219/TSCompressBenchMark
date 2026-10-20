# Local provenance notices

Sprintz native core: Apache-2.0, dblalock/sprintz frozen commit; modified files
are enumerated by patches/native-safety.patch. Copyright notices retained.
Huff0/FSE entropy sources: individual BSD-2-Clause notices retained. The vendored
Zstd root additionally carries BSD-3-Clause. Both notices are included here.

The lzbench program's lzbench.cpp states GPL-3.0-or-later. The frozen benchmark
wrappers have no individual header. Exact Huff0 wrapper functions are extracted
only into the research oracle tools/source_huff.cpp, not compiled into the
installed production library. Its source lineage and GPL context are retained;
this delivery makes no blanket Apache or redistribution qualification for the
whole research archive. Production src/api.cpp implements bounded envelope
operations and calls native Sprintz/Huff0 directly, without linking lzbench.

Original Catch/Eigen test trees in Source are source-only provenance assets;
production and standalone tests here do not link Catch or Eigen. Existing
per-file notices remain in the frozen source snapshot. User-authorized local
research execution does not erase upstream notices.
