# ABBA canonical C++ rewrite

This package implements the deterministic `ckmeans-scl0-norm2-v1` ABBA default
profile and the upstream alternate clustering paths. It is a standalone C++17
lossy pipeline with a versioned C11 ABI and a self-describing container. It does
not contain a TSDataCompressBenchMark adapter, registry entry or benchmark
configuration.

The supported pipeline is adaptive squared-L2 segmentation, `scl=0` CKmeans
digitization, population-ordered symbols, ties-to-even length quantization and
linear reconstruction. The retained upstream CKmeans kernel is audited for
input validation, initialized storage and reentrant sorting. The public C++ API
also supports deterministic finite-positive KMeans, `scl=inf` length-only
CKmeans, norm 1/2, and incremental weighted/symmetric clustering. The stable C
ABI v1 continues to expose the default profile; the unrelated patched
reconstruction helper remains outside this AlgorithmID.

## Build and test

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

To enable the frozen source oracle and dataset differential tests:

```bash
cmake -S . -B build \
  -DABBA_SOURCE_ROOT=/absolute/path/to/Compression_Rewrite/Source/abba/upstream \
  -DABBA_DATASETS_ROOT=/absolute/path/to/datasets
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

Public interfaces are `include/abba.hpp` and `include/abba_c.h`. The C ABI
exports only five `abba_*_v1` symbols. A null output buffer performs an exact
size query; the caller then supplies the reported byte/sample capacity.

See `contract.md` for the semantic and container contract. The full gate
record is in `PORT_MANIFEST.yaml` and `validation/`.
