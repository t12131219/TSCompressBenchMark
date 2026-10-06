# fABBA canonical C++ rewrite

This standalone C++17 package implements the deterministic
`stable-norm2-scl1-v1` fABBA profile. It provides a C++ API, versioned C11 ABI,
self-describing CRC-protected container, source differential tests, malformed
input tests, and physical FinalBits accounting.

The pipeline translates adaptive polygonal segmentation, population-standard
deviation scaling, stable 2-norm sorting, greedy aggregation, raw-piece center
means, nearest-even length quantization, and linear reconstruction. The public
C++ API includes bounded partitioned parallel compression with caller-selected
thread count and execution statistics. It rejects NaN/Inf and excludes
alternate sorting, multivariate/image paths, and alternate alphabets. See
`contract.md` for exact semantics.

## Build and test

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DFABBA_SOURCE_ROOT=/absolute/path/to/Compression_Rewrite/Source/fabba/upstream \
  -DFABBA_DATASETS_ROOT=/absolute/path/to/datasets
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

The package is rewrite-only. It does not add an adapter, registry entry, or
benchmark configuration, and `REWRITE_DONE` does not mean benchmark-ready.
