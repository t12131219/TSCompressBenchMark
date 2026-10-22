# Source-to-port mapping

Frozen primary: damslab/reproducibility 3fad358974c895cb639782995218bde42324d1ae, edbt2026-CAMEO. Frozen linked numerical core: cmcuza/TerseTS 64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0. All file hashes, languages, roles and license notices are in Source/cameo-family/SOURCE_MANIFEST.json.

| Port | Frozen source / retained stages |
|---|---|
| src/acf.cpp ACF | compression/lpc/inc_acf.pyx, math_utils.pyx; hpc/hp_acf_agg_model.pyx, hp_math_lib.pyx: eight-chunk prefix scan, sums/dot products, Pearson ACF, incremental single/interpolated updates and aggregate means |
| src/acf.cpp CAMEO | lpc/cameo.pyx, hpc/hp_agg_cameo.pyx, fgc/fg_cameo.pyx, fgc/fg_agg_cameo.pyx: initial impacts, hop lookahead, LPC/FGC/aggregate/ratio stopping, source mutation and failure trial |
| src/acf.cpp Heap/TP/VW/PIP | lpc/heap.pyx, pip_heap.pyx, vw.pyx, pip.pyx, tp.pyx and hpc counterparts: exact heap ties, neighbor links, importance, safe guards |
| src/swab.cpp | lpc/swab.pyx, heap_swab.pyx; segmentation_compressor.py: Cython sliding/bottom-up and Python heap bottom-up. Numerical lstsq kernel is src/linear_algebra.cpp |
| src/frequency.cpp | frequency_compressors.py DFTCompressor and DWTCompressor: FFT magnitude sorting, orthonormal DCT-II, Python slicing and inverse |
| vendor/pocketfft | unmodified TerseTS lib/pocketfft C source/header, BSD-3-Clause, native reuse |
| src/raw.cpp | TerseTS src methods and bindings for PoorMansCompressionMean, connected SwingFilter and SimPiece: float32 bounds, f80 means, swinging feasible lines, intercept/slope merging, quantization, index grouping and raw decode |
| src/numpy_sort.cpp | NumPy1.24.3 indirect quicksort/heapsort, frozen dependencies/numpy-quicksort.cpp and numpy-heapsort.h. A reusable standalone translation from ABBA-family was reused; no ABBA/fABBA/QABBA algorithm, tests or prior qualification was reused |
| vendor/openblas, cmake/source_lapack.cmake | source-built OpenBLAS0.3.21 C LAPACK ILP64 DGELSD for Python SWAB, full native dispatch; explicit native AVX512 FMA overlay in cmake/openblas_native_fma.cmake |
| vendor/linear-algebra | historical NumPy1.24.3 OpenBLAS/GFortran/Quadmath oracle assets; not linked or installed in default production |
| src/api.cpp | new standalone typed API, C capacity API, complete CF01 representation/CRC and independent inverse; no Benchmark ABI/registry |
| tools/cli.cpp | new bounded JSON-lines/file driver; unmodified nlohmann/json3.11.3 utility header, MIT, CLI/test only |

The CAMEO repositories point to TerseTS for PMC/SWING/SimPiece; this package selects those numerical P2 cores. The reproduction repository's ModelarDB.jar/Parquet P3 benchmark system is reference-only and neither ported nor redistributed. Unrelated SZ/anomaly systems and frozen unused wrapper files are not claimed as rewritten algorithms.

Production code is C++17 plus separately identified source-built C/native numerical dependencies. Python/Cython/Zig are reference-validation tools only. Oracle-build overlay selects the compression closure, avoiding unrelated anomaly dependencies; it changes no original algorithm body. Control patches and diagnostic wrappers have separate source/evidence identities.

User-authorized repaired-v1: six modified Cython files are separately frozen in Source/cameo-family/repaired-v1; see REPAIR_MANIFEST.json and cumulative patch0002. The C++ TP first-span and PIP termination follow this target. Original sources and old CONTROL are unchanged; all new reference outputs carry modified-reference scope.
