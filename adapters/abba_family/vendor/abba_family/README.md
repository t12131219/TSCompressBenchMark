# ABBA / fABBA / QABBA — standalone C++17 rewrite

The three explicitly requested GitHub repositories were acquired directly and
frozen under `../../Source/{abba,fabba,qabba}` on 2026-10-20. This package supplies
new C++ translations, the separately retained and patched ABBA CKmeans native
kernel, a C11 capacity API, a CLI, and a self-contained binary container. Python
is used only for reference tests. See `validation/porting_report.md` for the
actual release status, deviations, provenance and gate evidence.

Build without network access (Linux, CMake >=3.16, C/C++17 compiler, make, pthread):

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j3
ctest --test-dir build --output-on-failure
cmake --install build --prefix "$PWD/install"
```

zlib 1.2.13, Zstandard 1.5.6, bzip2 1.0.8 and liblzma 5.2.5 are built from bundled
sources. No external codec library, Python or Benchmark runtime is needed to
execute the library. Shared-library consumers link `-labba_family`; static
consumers also link `af_ckmeans`, `af_byte_zlib`, `af_byte_zstd`, `af_byte_bz2`,
`af_lzma` and pthread. Use this package's bundled JSON header consistently across
C++ translation units. The C11 ABI avoids any JSON C++ ABI dependency.

JSON-lines example:

```sh
printf '%s\n' '{"algorithm":"fabba","values":[0,1,3,1,2],"config":{"tol":0.1,"alpha":0.5}}' | build/abba_family_cli
```

`algorithm` is `abba`, `fabba` or `qabba`. Operations are `fit` (default),
`compress`, `digitize`, `quantize`, `inverse`, `transform` (QABBA), `symbol_stats`,
`image_fit`, `image_inverse`, `native_ckmeans`, `encode` and `decode`.
`input_bits` and `argsort` are verification primitives. Models are ordinary,
versioned JSON values; no hidden process state survives a call. To reuse a model,
pass `model` to `inverse` or QABBA `transform`; `symbols` and `starts` can override
stored sequences and starts. A new fit creates an independent replacement model.
Inverse accepts edited sequences (fABBA also accepts empty sequences); the reconstructed duration can change.
Symbols are normalized to lists at the public value boundary; string input is
also accepted for single-character alphabets. Plotting and original-signal patch
averaging are outside the compressed representation object.

The fABBA `source_backend` configuration selects `python` (default) or `cython`
diagnostic semantics. Both execute entirely in C++; this preserves the upstream
backend differences in `splist` counts and PCA coordinates. `fill` names the
upstream fit/compress `fillm` argument for fABBA (constructor `fillna` is not used
by its source fit method). `alphabet` is the fABBA alphabet_set argument; QABBA
also accepts its alphabet in config. Set `operation:image_fit` for image helpers,
or `image:true` for a self-contained image frame. `adjust` defaults to true.

Binary file operations:

```sh
build/abba_family_cli encode-file request.json data.afs
build/abba_family_cli decode-file data.afs reconstructed.json
```

A new decoder process needs only the frame. Container format and physical bit
accounting are in `docs/FORMAT.md`. The upstream implementations expose symbols
and codebooks, not a common self-contained binary format; the compatibility
target is SEMANTIC. Source theoretical storage estimates and physical FinalBits
are separate outputs. No pointwise error guarantee is inferred from tolerance.

`include/abba_family.hpp` documents the native API; `include/abba_family_c.h`
documents the C11 API. `af_execute_v1` has no hidden handles; no reset/finalize
operation exists upstream. Every request is complete and independent. Capacity
queries return the exact serialized result size after executing the request;
unseeded ABBA queries can have different learned results on a later execution,
so allocate an adequate caller buffer or use the C++ owned-result API for those.
Failures set produced=0 and preserve output. Input/output may overlap; the two
size counters must be distinct writable objects disjoint from input/output.
Caller buffers require zero overread padding. JSON text is bounded to 16MiB,
depth 64; larger binary frames use the C++/file decoder API directly.

Limits: 1,048,576 input values / 4096 series; 65535 centers; 4,194,304 restored
values; quantizer widths 1..64; 256MiB frame. Segmentation/aggregation work is
limited to 100 million inner iterations, KMeans to 100 million planned distance
iterations, CKmeans to 8 million DP cells, and LZW to 4,194,304 dictionary values.
Derived nonfinite states and overflowing reconstruction are rejected. These are
explicit resource/safety restrictions, rather than promises about arbitrary
Python integer sizes or unbounded source runtime. FE_TONEAREST binary64, no
fast-math and contraction off are the numerical contract.

Oracle setup (CPython 3.11, pip; all wheels already included, no network):

```sh
python3 tools/bootstrap_oracle.py
python3 tools/build_oracles.py
python3 tools/build_cython_oracles.py
python3 tools/verify_stages.py --report stages-replayed.json
python3 tools/verify_capabilities.py --report capabilities-replayed.json
AF_SOURCE_BACKEND=cython python3 tools/verify_stages.py --report cython-replayed.json
```

Further entry points: `verify_extended.py`, `verify_dataset_containers.py`,
`verify_reuse_sort.py`, `verify_extra_boundaries.py`, `run_benchmark.py` and
`tools/release_audit.py`. Sanitizers use `AF_SANITIZE=ON` / `AF_TSAN=ON`; libFuzzer
uses Clang with `AF_SANITIZE=ON, AF_FUZZ=ON`. Some sandboxes cannot run LSan/TSan;
the saved host runs provide actual results, not suppressed failures.

Source licenses: ABBA/QABBA MIT, fABBA BSD-3-Clause. The embedded CKmeans declares
CRAN Ckmeans ancestry; historical CRAN 3.4.6 and current DESCRIPTION both specify
LGPL >=3. Its source and modifications, and LGPL/GPL texts, are provided. Treat
the combined library as containing this LGPL component; preserve notices and
provide source/relinking rights when redistributing. Dependency-specific notices
and full file hashes are in `LICENSES`, `docs/SBOM.json` and source manifests.
