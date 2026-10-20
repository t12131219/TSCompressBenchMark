# Chimp family frozen research release binding

The active implementation is `chimp-family-cpp-scalar-v1`, consumed unchanged from
`chimp-family-research-20261017.tar.gz` (SHA-256 in `FROZEN_SOURCES.json`).
`vendor/chimp_family` contains separate regular files, never hardlinks to the
independent workspace. `reference` is the frozen original Java oracle closure.
Only the native binding in `native/` belongs to Bench. All builds verify the lock.

| Key | dtype | History / operation |
| --- | --- | --- |
| chimp | f64 | Chimp |
| chimp32 | f32 | Chimp32 |
| chimp128 | f64 | ChimpN, fixed 128 |
| chimpn | f64 | ChimpN, configurable power-of-two 1..65536 |
| chimp128-no-index | f64 | ChimpNNoIndex, fixed 128 |
| chimpn32 | f32 | ChimpN32, configurable power-of-two 1..65536 |
| pmc-mr | f32 | PMC-MR |
| swing-filter | f32 | Swing |
| swing-filter-disjoint | f32 | Disjoint Swing |
| swing-filter-disjoint-quantized | f32 | Quantized Disjoint Swing |

No f32/f64 conversion is implicit. The old chimp/chimp128 f32 routes must migrate
to chimp32/chimpn32. Fixed Chimp128 and ChimpN(history=128) produce identical frames.
FPC and quantized.filter2 are compiled parts of the frozen core but not registered.

## Build / verify

```bash
PYTHONPATH=benchmark/src python3 -m tsbench build chimp chimp32 chimp128 chimpn chimp128-no-index chimpn32 pmc-mr swing-filter swing-filter-disjoint swing-filter-disjoint-quantized
cmake -S adapters/chimp_family/vendor/chimp_family -B build/chimp-family-integration/reference -DCMAKE_BUILD_TYPE=Release
cmake --build build/chimp-family-integration/reference --parallel 2
ctest --test-dir build/chimp-family-integration/reference --output-on-failure
PYTHONPATH=benchmark/src python3 -m pytest benchmark/tests/test_chimp_family.py
```

Runtime is C++17, scalar, single thread, no fast math, FP contraction disabled.
There is no Python/Java codec fallback. Java is qualification-only. Core uses
physical contiguous bytes and owns both output vectors; input word/Point staging,
independent per-block objects, serialization, reconstruction and strict checks
are inside operations. Owned products survive context destruction until release.
Bound and domain admission do not precompute compression. Native API additionally
copies complete outputs into caller storage; finalize emits zero bytes once.

## Frame, limits and quality

Lossless input is <=1048576 values, block_size=1..1048576 (default 1000). Every
block, including the single empty block, is a complete CFP1 frame from the frozen
API. Native core returns a concatenation delimited by each CFP1 payload length;
no raw fallback, new kernel format or private decoder state is used. Canonical
positive qNaN (f64 7ff8000000000000 / f32 7fc00000) is the reserved EOF; other NaN
payloads, infinity, subnormals and signed zero retain source bits.

Filters use finite f32, implicit timestamps 0..N-1 per column, <=1048576 total
values. PMC accepts empty; Swing requires >=2; Disjoint and Quantized >=1.
Quantized epsilon must be positive; others permit zero. Epsilon is converted to
finite f32 and reported as such; positive underflow is rejected. Default
quality_mode=strict_abs calls the frozen strict encoder: actual reconstruction
must be finite with maxABS<=f32(epsilon), otherwise no output. This is an input
verification/rejection policy, not a universal source bound proof. Compatible
mode preserves known source error violations and nonfinite singleton output and
is admitted only for empirical_quality. All accepted outputs still undergo
Bench's task quality predicate. Relative quality tasks are not qualified. No
real timestamp stream or sparse grid is consumed by this Bench profile.

Object / C1 matrices use independent columns. Lossy native_core requires rank1
or one column; lossless core is a physical scalar stream, including C/F layout.
C1 input CFI1: 16-byte header (magic4, width1, method1, columns u16LE, rows u64LE)
then SOA data. Complete CFS1 output has the same header with CFS1 magic, then
per column u64LE byte length + complete CFP1 block stream. Width, method, fixed
history, frame CRC/counts, grid, all lengths and trailing bytes are validated.
Decode is transactional; caller output remains unchanged on failure. All CFP1
metadata/CRC, EOF/padding, block bytes, CFS1 header and column lengths are charged.
There is no hidden model, dictionary, timestamp payload or uncharged index.
External task shape/order is checked; CFP1 contains every codec decoding setting.

## Qualification and research scope

The standalone status is RESEARCH_REWRITE_VALIDATED, never FULL_PARITY or a new
formal V3 gate signature. Its known Swing/Quantized defects remain unchanged.
License facts and CHIMP-LOCAL-RESEARCH-20261017 are retained in the frozen package;
local experimental scope expires 2026-11-17 and grants no redistribution rights.
See `docs/chimp_integration/README.md` for separate Bench evidence and limitations.
Old sources and working-tree shim were saved in
`docs/chimp_integration/legacy-chimp-before-family.tar.gz` before removal. Old
performance records remain tied to their original identities.
