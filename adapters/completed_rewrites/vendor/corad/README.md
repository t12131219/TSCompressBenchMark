# CORAD independent native rewrite

REWRITE_DONE,FULL_PARITY12/12,G0–G6PASS; validated Linux x86_64.
Actual per-object dictionary learning,all5 sparse solvers,Pearson correlation,
stable ranking/reference choice and independent complete-state decoder.
Production is C99/C++17 plus declared external MKL2023.1,no Python dependency.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTRISTAN_MKL_ROOT=/home/fzg/anaconda3
cmake --build build -j2
ctest --test-dir build --output-on-failure
build/corad_cli backend
```

API include/corad.hpp. Encode CLI: `corad_cli encode input.bin rows channels
length atoms nonzeros solver seed alpha threshold output.frame`; decode:
`corad_cli decode output.frame decoded.bin`. Solver0OMP,1LARS,2Lasso-LARS,
3Lasso-CD,4threshold. Diagnostic arrays use little-endian IEEE754 binary64;
output standardized channel/window/position. Embedded means/scales support
caller inverse normalization. Dropped tails/constants/nonfinite input and lack
of strict approximation bound preserve source semantics; threshold is heuristic.
Correlations with undefined variance retain NaN; references copy atom-coded
values in the same window,including forward channel IDs. All decoder state is
embedded and charged to FinalBits. Contract and reports explain exact limits.

Pinned numerical C++ is vendored from completed TRISTAN; independent consumers
need no sibling checkout. Native CPython3.11.5 stable-sort specialization handles
NaN/ties with original comparison order and no Python object/runtime API.
Source-oracle revalidation requires frozen workspace source and locked Python
oracle only for tests; ordinary build/encode/decode/ctest are fully native.
Performance is QUALIFICATION only; no framework adapter/registry/benchmark,
ranking,internal parallel speedup,ARM validation or external publishing.

Upstream https://github.com/eXascaleInfolab/CORAD,
commit083824eb3e0b3ad72a00d4f585bc77b5adb5c1be. Original frozen source manifest
retains historical G1 metadata; current completion is PORT_MANIFEST.yaml.
CORAD-derived code NOASSERTION,scikit-learn/Pandas notices BSD-3-Clause,
CPython sorting PSF-2.0. Notices/provenance and local-only user workflow override
retained; no upstream license grant invented. See reproduction/USER_DECISIONS.md.
