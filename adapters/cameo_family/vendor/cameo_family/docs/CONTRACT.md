# CAMEO family contract — revision 4 (repaired-v1, optimized source closure), 2026-10-21

Scope: CAMEO/SIP, VW, PIP, TP, SWAB, Sim-Piece, PMC, SWING, DFT and
**DWT(DCT-II)** in one standalone family. CAMEO and SIP name the same algorithm;
`dwt-dct-ii` is the stable ASCII slug; its display name is `DWT(DCT-II)`.
The upstream class remains `DWTCompressor` for source traceability.
Actual upstream transform is orthonormal DCT-II, not a wavelet transform.

Primary CAMEO source: damslab/reproducibility commit
3fad358974c895cb639782995218bde42324d1ae, edbt2026-CAMEO subtree,
Apache-2.0 root license. cmcuza/cameo commit
97d146b4d06662107fe6ac5aaf7b24f55a45d862 is discovery/comparison evidence;
it has no repository license and is not translated. PMC, SWING and Sim-Piece
follow the TerseTS dependency explicitly linked by both CAMEO repositories,
frozen cmcuza/TerseTS 64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0,
Apache-2.0 plus embedded dependency notices. The reproduction repository's
ModelarDB/Parquet benchmark system is a different P3 implementation, not the
selected TerseTS numerical P2 objects. Its jar is not used or redistributed.

Route: TRANSLATED Python/Cython/Zig algorithms; pocketfft is a separately
identified NATIVE_REUSE BSD component. Python SWAB least-squares uses frozen
OpenBLAS 0.3.21 ILP64 DGELSD, built offline from its BSD licensed source archive.
Its translated C LAPACK avoids Python, GFortran and Quadmath in production.
Linux x86_64 retains all 20 upstream DYNAMIC_OLDER kernel names; AArch64 uses
ARMV8. The numerical dependency is native reuse, not a claimed C++ rewrite of
all BLAS routines. Its qualification boundary is the codec's m-by-2 DGELSD
operation and exposed Python-SWAB path, including actual/requested dispatch.
The public codec has no ISA selector; forced OPENBLAS_CORETYPE tests are explicit
dependency diagnostics. Assembly and system runtimes remain an explicit native
boundary; instrumentable C/C++ closure is covered in baseline sanitizer builds.
No prior Benchmark vendor is an input.
Compatibility: SEMANTIC stages and reconstructions against the explicitly
modified repaired-v1 reference for repaired branches; original-source evidence
is historical and separately scoped. The user authorized appropriate repairs
to the previously reported failures. No unmodified-source FULL_PARITY is claimed.
TerseTS raw streams also require CROSS_DECODE (little-endian usize64 source architecture). A new CF01
frame includes the entire payload, algorithm, original and restored counts,
format version and checksum. Independent decode requires only the frame.
Physical FinalBits is the whole frame length times eight, never the source's
point/coefficients-only estimate. No source pickle compatibility is promised.

Values: ordered one-dimensional finite binary64, regular integer sample
positions. Caller input is immutable; the Cython working signal mutations are
returned as explicit diagnostics. Fit calls are independent. Decompression uses
retained points and their values, sparse Fourier complex coefficients or DCT
coefficients, or the complete TerseTS-compatible raw representation. SWAB's
original-data-dependent endpoint values are included in the frame. No hidden
original signal, Python object or last-encoder state may be consulted.

Numerical: the translated core/canonical baseline uses FE_TONEAREST, binary64,
no fast-math and no FMA contraction. Native SkylakeX/Cooperlake C reduction
kernels explicitly retain upstream contraction=fast; the small-matrix reduction
relies on fused rounding. This is a declared native optimization, qualified
against the same forced source kernels, not a canonical-core flag change. Aggregate
CAMEO paths intentionally preserve source long-double intermediates and its
generated C++ long-double sqrt/fabs overloads. The original revision incorrectly
characterized these calls as narrowing to double; inspection of generated C++
and executed differential evidence corrected that interpretation. Linux x86_64
uses 16-byte storage / 64-bit mantissa long double; AArch64 has 113 mantissa
bits. Encoder decisions can differ across architectures at numerical ties
(including libm hypot and least-squares residual ordering). Source stage parity
is signed against the frozen x86_64 oracle, with a matching execution environment
for forced kernels. Cross-architecture qualification executes both encoders and
independent decoders and compares recovery of the same physical frame; it does
not assert cross-architecture encoder stage or frame byte identity. Decisions/masks/indices are exact when source behavior is defined;
floating stages use 1e-10 + 1e-10*abs(reference). Degenerate source ties,
nonfinite ACF, invalid memory accesses and native safety restrictions are audited
separately; tolerance cannot excuse a different stable decision.

CAMEO/VW/PIP/TP stop by upstream mean absolute per-lag Pearson-correlation
error, not by sample pointwise error. CAMEO supports hops, LPC, FGC workers,
aggregate means kappa and source ratio stopping. VW/PIP/TP preserve aggregate
paths. SWAB supports Cython sliding-window and bottom-up paths; Python
segmentation wrapper's different NumPy least-squares bottom-up is separately
inventoried. DFT retains int(n*fraction) largest-magnitude coefficients with
NumPy 1.24.3 indirect argsort tie behavior. DWT(DCT-II) uses an FFT of the even extension for its orthonormal DCT-II/III;
Config.canonical_dct / C flag16 / CLI transform=scalar forces the independent
O(N^2) definition. Default is O(N log N), with no N^2 work bound on that fast path.
DWT(DCT-II) zeros the last
int(n*fraction) DCT coefficients; **zero zeros all coefficients** because
upstream uses `[-0:]`. Fraction slicing outside [0,1] follows Python slice
semantics and must be checked. TerseTS PMC means PMC-Mean (not midrange),
SWING means connected SwingFilter, Sim-Piece includes quantization, common
intercept/slope merging and index grouping. Error bounds are cast to float32
by TerseTS; its 1e-7 margin is retained. Sim-Piece rejects zero error for n>=2.

Source defects are not silently repaired into source-parity successes: TP can
free uninitialized heap storage on early exit; SWAB has odd-tail unsafe reads;
PIP's loop tests node value rather than cache and can dereference null endpoint
neighbors; prefix scans assume at least eight aggregates. C++ must prevent
invalid memory access, record any safety repair and distinguish unmodified
source execution from patched/control or specification evidence. Source hangs
and crashes are diagnostics, never expected outputs generated by the port.

Limits are explicit resource safeguards: at most 131072 input/restored values,
64MiB frame; at most 64 workers; nlags/hops/kappa positive and bounded by the
actual series; planned inner work <=100 million steps. Nonfinite restored
samples/coefficients, arithmetic overflow and invalid representations reject.
For ACF sources the defined scan domain starts at eight aggregate observations;
N=0/1/2 native boundary handling is explicitly an extension/safe refusal.

Public independent API: C++17 typed config/stage/encode/decode functions and a
C11 capacity API, JSON-lines and binary file CLI. No Benchmark ABI/registry.
For valid size counters, failure is atomic: produced=0, output unchanged.
Invalid/misaligned/overlapping counters or overflowing pointer ranges are
rejected before any write, including counter writes. Counters must be distinct,
aligned and nonoverlapping with buffers/config; byte output may overlap input after an internal
copy; no padding/alignment assumptions. Size query computes exact required
capacity; ownership stays with caller. No source continuous-stream/reset/flush/
random-access/GPU/ISA-specific path exists. Retain actual source internal
parallel prefix scans, initial impact evaluation and FGC lookahead with direct
forced-worker validation and concurrency/race checks.

Oracle: actual unmodified frozen Cython modules built under CPython3.11,
Cython3.0.12, NumPy1.24.3, SciPy1.11.1; actual unmodified Zig0.15.2 TerseTS
library. Build overlay selects compression modules to avoid unrelated anomaly
modules; no algorithm changes. Cython0.29.37 failed because long-double libc
functions are absent; log retained. Golden/source outputs come only from these
executions. Python is validation-only, never a production runtime dependency.

G2 plan: stage masks/working signal/points/coefficients/raw interchange and
reconstruction; three natural data families humidity/hepc/mintemp, fixed
original-order chunks; all shared 4KiB main float64 objects from Dataset_Verify;
short/constant/tie/boundary/nonfinite/invalid cases; LPC/FGC/aggregate/CR, workers
1/2/3 and each alternate path; C API exact and short capacities, overlap,
immutability/canaries, malformed checksummed frames, persistent allocation
failures; sanitizers, race checks, fuzz, GCC/Clang, a second executed platform
where tools permit, installed consumers, standalone timing, bit-reproducible
independent builds and indexed offline release recovery. All REQUIRED_PARITY
rows must pass before REWRITE_DONE; source defects/repairs remain explicit.


## Revision and qualification record

Revision 1 is retained in `history/CONTRACT-v1.md` (SHA-256
`1d16b0449a0f62832f4ea1d417c3ecf83053e0022f6a68fccf8517824514ca99`). Revision 2 corrects the
generated-C++ overload interpretation and records the concrete dependency/API
closure. It does not reduce the frozen REQUIRED_PARITY target or retroactively
turn source undefined behavior into success. At revision 2 the whole-family
status was BLOCKED for optimization/dependency/platform qualification. That
historical assessment is retained in `history/CONTRACT-v2.md`; current evidence
is in `VALIDATION_REPORT.md` and the matching external release audit.

The frozen TP first-turn branch accesses selected_tp[-1] and has no unique
original result. Revision 3 defines tp-first-span-v1 below. The older safety
CONTROL still refuses that branch and remains separately labelled.

Revision 3 used only the O(N²) canonical DCT-II, limited to 10^8 terms, and
retained fast transformation, complete numerical dispatch and a second
architecture as required blockers. Revision 4 implements the O(N log N) fast
path, retains the forced scalar definition, builds the full source numerical
closure, and qualifies all 20 actual x86_64 kernels. AArch64/QEMU executes API,
safety and cross-architecture recovery within the platform scope defined above.
The required capability set has not been reduced. Current qualification depends
on the executed evidence and matching release audit, not this contract text.


## Accepted repair target, revision 3

The user requested appropriate repairs to the reported original failures.
`cameo-family-repaired-v1` is a modified-reference target, not a retroactive
claim that the frozen original source had defined behavior. Revision 2 is kept
in `history/CONTRACT-v2.md`. Original-source inventory/classifications remain
intact; repaired support and tests are separately attached to the matrix.

TP policy `tp-first-span-v1`: if the first interior turn i is separated from
the origin by more than one sample, interpolate the current interval [0,i],
using its actual endpoint values. Normalize its accumulated absolute fit error
by i-0, the length of this first interval. Never read a predecessor before 0.
Subsequent intervals retain original defined formulas, including the previous
interval denominator and existing source stopping/working-copy behavior; this
repair does not redesign the TP objective or fix every numerical quirk.
No change is made for a first turn at 1, where the original branch was defined.

VW uses sizeof(long double) for long-double arrays; PIP stops on importance
cache rather than signal value; TP early exit frees only the allocated heap
struct before its values exist; SWAB clamps the array index before reading its
odd/global tail. The same six-file cumulative patch builds an isolated
reference at oracle-repaired; frozen originals/oracle-runtime and old
oracle-control are untouched. Source/cameo-family/repaired-v1 retains all six
modified files, REPAIR_MANIFEST hashes them, and PATCHES/0002-repaired-v1-
cumulative.patch is applied after LF normalization in a disposable copy.

C++ default encoding now uses this repair target, with analyze diagnostic
`tp-first-span-v1` when that TP branch is used. The C/C++ API/algorithm IDs and
CF01 representation are unchanged: existing independent decoders remain valid
because no reconstruction rule or representation changed. Encoder semantics
and implementation identity did change and cannot inherit old parity evidence.
