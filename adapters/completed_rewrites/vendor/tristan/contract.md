# TRISTAN contract v1 — preimplementation freeze

Source P2 batch pipeline: column-wise zscore (ddof=0), ordered tricklets,
DictionaryLearning fit, sparse coding, optional CORAD correlation references,
and dictionary reconstruction. Binary64 numeric arrays; channel/window/position
layout is explicit. Input is finite; constant whole columns become NaN in source
normalization and are rejected, not imputed. Source drops incomplete windows.

DictionaryLearning uses alpha/n_components with max_iter=10, ignoring n_iter.
All five public SparseCoder transform algorithms are REQUIRED_PARITY: omp, lars,
lasso_lars, lasso_cd and threshold. Dictionary initialization/training and source
RNG/numerical backend must be preserved; fixed test dictionaries alone do not
replace required native dictionary training. Installed reference dependency
versions are locked as the present oracle; they are not claimed as paper versions.

CORAD ranks correlation row sums descending with Python stable ties, then
chooses the maximum threshold-qualified reference among already atom-coded
channels. Decoder copies that channel/window reconstruction directly. The ts
argument is unused in the selected reconstruction function; fresh source decoding
has been executed with ts=None. Neither original time series nor a source oracle
may be a hidden production dependency.

The reported calculate_RMSE is standardized mean square error, not square root
RMSE. err maps to correlation threshold 1-err/2; it does not enforce a global
absolute reconstruction-error bound. Dictionary, preprocessing state, shape,
indices, coefficients, references, tails policy, framing and integrity fields
must all be accounted for in FinalBits. The legacy script omits the dictionary
from its compressed payload ratio; no such free model is allowed in native frames.

Target: SEMANTIC for the complete selected pipeline and all backends.
Source pickle/JSON fixtures are trusted test artifacts; native production must
use a bounded independent frame and never unpickle untrusted input. Numerical
tolerances, bounds and byte layout are frozen below. This freeze does not claim
FULL_PARITY or REWRITE_DONE.

## Identity, input and lifetime

AlgorithmID tristan; ImplementationID canonical_cpp; TRANSLATED, P2_PIPELINE.
Source commit 083824eb3e0b3ad72a00d4f585bc77b5adb5c1be. Local-only workflow
override in USER_DECISIONS.md; attribution and NOASSERTION retained.
Read-only contiguous row-major IEEE754 binary64 [rows,channels], alignment8,
no safe overread and no timestamp. Each batch call starts fresh state and RNG.
Output is [channel,window,position]; optional inverse normalization restores only
represented rows. No incremental streaming, append/finalize or hidden reset API.

Rows must contain at least one full window; channels>=1. Require finite inputs,
finite positive population standard deviations and finite standardized values.
Reject constants and nonfinite normalization (including underflow/overflow).
Signed zero is numeric, not bitwise preserved. Mean/std use ALL rows, including
discarded tails. Windows=floor(rows/length); discarded_tail=rows%length.
Defaults length40, atoms200, nonzero4, learning alpha1, seed0, requested_n_iter150.
Positive length/atoms/nonzero; nonzero<=atoms; finite alpha>=0; seed and n_iter u32.

## Dictionary and solver semantics

Per-object in-band training uses channels1:min(8,D), or channel0 when D=1,
channel-major/window-major order. This preserves the source adaptive track;
there is no offline tuning with validation/TEST cases. Training time is reported
separately; dictionary and preprocessing metadata are charged.
Thin SciPy gesdd SVD, U-column max-absolute sign flip, S*Vt initialization,
truncation/zero-padding to atoms. Fit lasso_lars, max_iter10, tol1e-8,
solver max_iter1000. Update A=code.T*code, B=training.T*code in atom order;
Akk>1e-6 uses dictionary += (B[:,k]-A[k]*dictionary)/Akk, else resample a
training row and add Gaussian noise0.01*(std or1), clear that code column.
Normalize each atom by max(l2norm,1). Stop when cost decrease<1e-8*cost.
PRNG NumPy legacy RandomState MT19937, masked-rejection choice and cached polar
Box-Muller normals; no global mutable RNG or wall-clock seeds.

OMP/LARS use requested nonzeros. Other solvers use source transform_alpha1,
independent of learning alpha. OMP preserves epsilon early stops. LARS preserves
first-index argmax, 15-decimal covariance rounding, float32 epsilon stopping,
binary64 epsilon pivot floor, interpolation, sign changes and active-set drops.
Cyclic Lasso-CD: max_iter1000, tol1e-4, dual-gap stopping. Threshold:
sign(dot)*max(abs(dot)-1,0). Exact nonzero coefficients ordered by atom index;
scalar ordered reconstruction sum matches the upstream decoder. Empty rows
decode to zeros. Source standardized MSE may be NaN for one window/constant
reconstruction; report undefined rather than invent a strict error bound.

## Numerical and runtime freeze

Reference Python3.11.5/NumPy1.24.3/SciPy1.11.1/sklearn1.3.0/pandas2.0.3,
MKL2023.1. Module hashes, runtime dispatch, RNG and boundary evidence:
validation/g2_source/audit.json. Native C++ may reuse audited MKL BLAS/LAPACK,
but must implement training/RNG/solvers/orchestration/framing, without Python.
Canonical binary64, nearest-even, gradual underflow, FMA_OFF, no fast-math.
Reject an unsupported FP environment. BLAS thread count1, local per calling
thread. MKL internal dispatch is reused and observed, not claimed as translated
custom SIMD. Selected upstream pipeline exposes no joblib thread-count option,
GPU, custom ISA kernel or incremental streaming API. Independent handles have
no mutable codec state in common. Native library version/path/hash is recorded.
Supported validation platform Linux x86_64; ARM is a future numerical backend,
not a claim about the x86 MKL runtime. Optimizations require prior correctness.

Frozen per-element |new-ref|<=atol+rtol*|ref|, with both atol and rtol:
preprocessing1e-12; dictionary1e-7; coefficients/reconstruction1e-6.
Shape, tails, training selection, solver and exact-nonzero support indices must
match. Keep all 15 dataset cases and source boundaries. Failure cannot change
tolerances or drop cases. Required checks: independent decoding, malformed,
capacity/canaries, GCC/Clang, ASan/UBSan, determinism, static analysis, fuzz,
reproducible independent builds and isolated package consumption.

## Frame v1 and accounting

Little-endian integers and IEEE754 binary64 bits; byte-aligned. Header96 bytes:

| Offset | Type | Field |
| --- | --- | --- |
| 0 | byte[8] | TRISTAN1 |
| 8 | u32 | version1 |
| 12 | u32 | header bytes96 |
| 16 | u32 | flags0 |
| 20 | u32 | omp0,lars1,lasso_lars2,lasso_cd3,threshold4 |
| 24 | u64 | original rows |
| 32 | u32 | channels |
| 36 | u32 | length |
| 40 | u32 | atoms |
| 44 | u32 | nonzeros |
| 48 | u32 | seed |
| 52 | u32 | requested_n_iter |
| 56 | f64 | learning alpha |
| 64 | u64 | windows |
| 72 | u64 | payload bytes |
| 80 | u64 | reserved0 |
| 88 | u32 | IEEE CRC32 whole frame with this field zero |
| 92 | u32 | reserved0 |

Payload: D pairs(f64 mean,f64 scale), atom-major dictionary A*L f64,
then D*W channel-major sparse rows: u32 count and count pairs(u32 atom,f64 coef).
Count<=A, strictly increasing indices<A, finite nonzero coefficients, finite
dictionary, finite means and positive finite scales. Reject unknown version,
flags, reserved, bad checksum, invalid dimensions/config, truncation/trailing
bytes. Decoder needs no input, Python/pickle or external model.
FinalBits=8*physical_bytes, external bits0. Components (bytes): header96,
normalization16D, dictionary8AL, counts4DW, indices4nnz, coefficients8nnz.
Worst capacity=96+16D+8AL+DW*(4+12A), checked arithmetic. Caller-buffer compress
requires full bound before training; bound-1 deterministically fails with no
output writes. Actual bytes_written is frame length, not bound.

## API and resource limits

C++17 exception API, Error(code,message); no C ABI or framework adapter.
Stateless train/encode/decode, bound and accounting functions. Input caller-owned;
returned vectors own memory. Errors InvalidArgument, OutputTooSmall,
CorruptStream, ResourceLimit, NumericalFailure, Unsupported. No partial writes.
Limits checked before allocation: rows<=1048576, channels<=256, length<=4096,
atoms<=4096; defaults input/output/frame256MiB, workspace1GiB. Caller can lower
limits. Solver max1000; bound degenerate retries. Reject oversized shapes before
allocating; loops and memory bounded even for attacker-controlled frames.
