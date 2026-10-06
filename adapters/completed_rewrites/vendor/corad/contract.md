# CORAD contract v1 — preimplementation freeze

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
tolerances, bounds and byte layout are frozen below. No canonical C++ is permitted
before G2 passes. This freeze does not claim FULL_PARITY or REWRITE_DONE.

## Input, runtime and numerical semantics

C++17 batch exception API; stateless encode/decode/bound plus Pearson stage API.
Input read-only aligned contiguous IEEE754 binary64 row-major [rows,channels],
no timestamp, safe overread0. Output standardized [channel,window,position].
Rows>=length, rows<=1048576, channels1..256, length1..4096, atoms1..4096,
nonzeros1..atoms. Finite alpha>=0, finite threshold (not restricted to [-1,1]);
seed/requested_n_iter u32. Defaults length40,atoms200,nonzeros4,alpha1,seed0,
requested_n_iter150,threshold0.8 (source err0.4 maps to1-err/2).
Mean/std use all rows including discarded tails, ddof0. Reject constant whole
columns, NaN/Inf/nonfinite normalization and standard deviation underflow.
Window-constant columns remain valid: Pearson undefined entries are NaN.
Signed zero need not preserve its bit pattern. No strict approximation-error
bound exists; numerical parity is distinct from standardized approximation loss.

Per-object training uses standardized channels1:min(8,D), channel0 if D=1;
channel-major/window-major order, thin gesdd SVD sign-flipped initialization,
max_iter10 ignoring requested_n_iter, Lasso-LARS fitting, ordered dictionary
updates, NumPy legacy MT19937/choice/cached polar Box-Muller. All5 sparse solvers
run per-channel on all windows before correlation selection; transform alpha1
independent of learning alpha. Source defaults/tolerances/early stops/zero support
are preserved. Reuse the verified TRISTAN numerical implementation as a pinned
vendored C++ dependency, with hashes/provenance and original notices; production
must not depend on the sibling checkout, Python or a test oracle.

Reference Python3.11.5/NumPy1.24.3/SciPy1.11.1/sklearn1.3.0/pandas2.0.3,
MKL2023.1 (native BLAS/LAPACK reused, thread-local1). Nearest-even,gradual
underflow,FMA_OFF,no fast-math. Unsupported FP environment rejected.
Validated target Linux x86_64; no ARM MKL claim. No internal threading/GPU/
custom SIMD/incremental streaming/seek in selected source wrappers; independently
called objects must be deterministic and thread-safe.

Pearson follows pandas2.0.3 algos.nancorr Welford updates in original row order:
dx=x-meanx,dy=y-meany,means+=(1/n)*delta,ssq+=(value-newmean)*delta,
cov+=(x-newmeanx)*dy; divisor=sqrt(ssq_x*ssq_y), cov/divisor or NaN if zero.
No artificial clipping or diagonal override. Lower triangle mirrored.
Row sums use Python sequential sum starting0. Stable descending sums rank
channel IDs initially ascending. Window-constant channels cause every row sum
to be NaN and preserve original channel order. Among already atom-coded channels
with correlation>=threshold and different ID, choose maximum correlation,
lowest channel ID on exact ties. References only target atom-coded rows in the
same window, never other references; atom-coded target IDs may be greater than
referencing IDs. Decoder must reconstruct all atom rows before copying references.

Frozen per-element |new-ref|<=atol+rtol*|ref| with both atol=rtol:
preprocessing1e-12; Pearson1e-12 with identical NaN masks; dictionary1e-7;
coefficients/reconstruction1e-6. Shapes,tails,ranking,reference IDs and exact
nonzero support MUST match. Do not relax thresholds/drop failed cases.

## CORAD frame v1 and accounting

Little-endian integers/binary64, header104 bytes:
magic8 CORAD001; u32 version1/header104/flags0/solver0..4 at offsets8/12/16/20;
rows u64 at24; channels/length/atoms/nonzeros/seed/requested_n_iter u32 at32..52;
alpha f64 at56; windows u64 at64; payload bytes u64 at72; reserved0 u64 at80;
IEEE CRC32 at88 computed over whole frame with bytes88..91 zero; reserved0 u32
at92; threshold f64 at96. Payload D pairs(f64 mean,scale), A*L f64 dictionary,
then D*W channel-major rows. Each row begins u32 tag: UINT32_MAX means reference
followed by u32 target channel; otherwise tag=count<=A, followed by count
pairs(u32 atom,f64 finite nonzero coef) with strictly increasing atom IDs<A.
All dictionary/means finite,scales finite positive. Reject unknown framing,
reserved/flags/config,CRC mismatch,truncation/trailing bytes,duplicate/nonfinite
coefficients,self/out-of-range references and reference-to-reference edges.
Forward atom references are legal. Independent decoder requires only frame.

FinalBits=8*physical_bytes,external bits0. Components: header104,
normalization16D,dictionary8AL,row tags4DW,atom IDs4nnz,coefficients8nnz,
reference targets4R. Pearson/ranking are encoder workspace,not decoder state.
Worst capacity=104+16D+8AL+DW*max(8,4+12A), checked arithmetic. Caller-buffer
compress requires full bound before work; bound-1 errors without writes;
actual bytes_written is frame length. Input/output overlap rejected.

Default limits input/output256MiB,workspace1GiB; lower caller limits respected,
checked before allocation. Conservative workspace includes normalization,
training/SVD/solver copies,Pearson W*D*D,ranking/references and trace snapshots.
Error(code,message): InvalidArgument,OutputTooSmall,CorruptStream,ResourceLimit,
NumericalFailure,Unsupported. Allocation failures translate to ResourceLimit.
No hidden external dictionary,partial caller-buffer writes or unbounded parser.

Required: all15 frozen dataset cases,source boundary/threshold/tie/NaN/forward
reference oracles,all5 backends,independent decode/capacity/malformed/fuzz,
GCC/Clang,ASan/UBSan/LSan,TSan handles,static analysis,determinism,independent
reproducible builds,standalone qualification and isolated release consumption.
