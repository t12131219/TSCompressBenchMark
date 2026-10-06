# TRISTAN independent C++17 rewrite

REWRITE_DONE / FULL_PARITY10/10 / G0–G6PASS on Linux x86_64.
Real per-object dictionary learning, all five sparse backends, complete charged
frame and independent decoder. No Python is needed by the native library/CLI.

Build with an explicitly installed audited MKL2023.1:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTRISTAN_MKL_ROOT=/home/fzg/anaconda3
cmake --build build -j2
ctest --test-dir build --output-on-failure
build/tristan_cli backend
```

Public API: include/tristan.hpp. CLI usage: `tristan_cli encode input.bin rows
channels length atoms nonzeros solver seed alpha output.frame` and
`tristan_cli decode output.frame decoded.bin`. Diagnostic raw arrays require
little-endian IEEE754 binary64. Solver IDs0OMP,1LARS,2Lasso-LARS,3Lasso-CD,4threshold.
Decode output is standardized channel/window/position; embedded means/scales
permit caller inverse normalization. Source drops incomplete tails/rejects
constants/nonfinite normalization; it provides no strict absolute error bound.

Read contract.md, dataset_validation_report.md, native_capability_validation_report.md,
validation_report.md, build_reproducibility.md and TOOLCHAIN_MANIFEST.json.
The package includes source/tests/evidence/fixtures; external MKL is not bundled.
Full source-oracle revalidation additionally requires the frozen workspace source
and locked Python oracle environment. Diagnostic trace tools are not dependencies
of production encoding or decoding. No framework adapter/registry/benchmark
integration, ranking, ARM validation, or internal parallel speedup is claimed.

Upstream CORAD https://github.com/eXascaleInfolab/CORAD,
commit083824eb3e0b3ad72a00d4f585bc77b5adb5c1be. Original source snapshot metadata
retains its historical G1 status; current gate evidence is PORT_MANIFEST.yaml.
Numerical translation retains scikit-learn BSD-3-Clause copyright and license.
CORAD-derived orchestration/protocol retain NOASSERTION; local-only workflow
override is reproduction/USER_DECISIONS.md. No upstream license grant is invented,
and this local package has not been externally published.
