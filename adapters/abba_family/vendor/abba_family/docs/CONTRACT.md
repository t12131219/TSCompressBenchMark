# Frozen implementation contract — 2026-10-20, before C++ implementation

The source is the three GitHub repositories explicitly selected by the user,
acquired on 2026-10-20. Source/<id>/SOURCE_MANIFEST.json fixes the actual commits.
Older Benchmark vendor implementations are not implementation inputs. This is a
fresh TRANSLATED SOURCE_REWRITE of the Python/Cython pipelines. The ABBA CKmeans
C++ kernel is retained as a separately identified NATIVE_REUSE component, not
misrepresented as newly translated code. The entire object is a P2_PIPELINE.

## Comparison and loss contract

SEMANTIC comparison covers segmentation boundaries and [length, increment, error],
digitization decisions and codebook, symbol assignment, model updates, center
quantization, integer-grid length quantization and reconstructed samples.
Integer decisions must agree exactly in deterministic upstream executions;
numerical stages use abs <= 1e-10 + 1e-10*abs(reference), with tie/boundary cases
examined separately rather than accepting different decisions through tolerance.
No global pointwise absolute or relative error guarantee is invented: the
upstream tolerance controls stages, not a strict original-sample error bound.
No public self-contained upstream binary format exists. Our new, versioned
little-endian container must include every required codebook, first value,
quantization scale/zero point, shape and entropy model; CRC protects corruption.
Independent decode may not consult the original input, fitted Python objects or
Benchmark. Physical FinalBits include the entire container and padding.
Source theoretical storage estimates are exposed separately, never substituted
for the actual serialized byte count.

## Source capability inventory and required target

ABBA: one-shot univariate binary64, compression norms 1/2, separate tolerances,
max_len, CKmeans for scl=0/infinity including upstream sklearn fallback, finite
scl KMeans, incremental clustering (weighted/unweighted, symmetric/asymmetric),
seeded clustering, public stage operations, symbols/codebook inverse and model
persistence through a package-owned format. Random unseeded upstream execution
requires algorithm-level rather than one-run symbol identity. Visualization,
patch averaging using the original signal, and plotting utilities are auxiliary
analysis objects, not compressed representation decode. CKmeans linear/loglinear/
quadratic kernel methods remain available separately as upstream native primitives.

fABBA: univariate/row/column convenience; all five sorting modes lexi/1-norm/
2-norm/norm/pca; alpha/tol/scl/max_len; missing-data fills; fitted model; custom
alphabet and the two predefined alphabets; list/string symbol representations;
partition/partition_rate and bounded workers with shared endpoints; stage and
inverse operations; model export/import; image helpers (flatten, normalization,
shape restoration). JABBA/XABBA and the different historical QABBA classes in this
repository are separate algorithm objects and are inventoried, not substituted
for the user-selected inEXASCALE QABBA.

QABBA: one/multiple series sharing a fitted codebook; fit/transform/inverse/
reconstruct; agg norm/pca, kmeans and sampled f-kmeans; random_state/sample_rate/
max_iter/scale_length/n_symbols/alpha/max_len; signed center quantization and
bitwidths; NaN filling; custom alphabet; bounded parallel per-series work; aliases
fastQABBA/fastQABBA_len/fastQABBA_inc are the same class at this commit. All source
symbol layer modes none/fixed/huffman/huffman1/lzw/zlib/gzip/bz2/lzma/zstd have
source-relative accounting; actual reversible native representations must not
be confused with upstream accounting-only payloads. Quantizers and fitted
transform model are serialized in full. Source compress/decompress lacking
quantizer metadata and any source defects are explicitly recorded, not hidden.

Cython offers compiled scalar loops; no explicit ISA-specific codec or GPU path
exists for these selected classes. A compiled C++ scalar implementation replaces
those kernels, with direct Python/Cython checks where applicable. Concurrent
independent handles and actual source internal partition/batch parallel paths
require dedicated tests. Streaming/seek/reset/finalize APIs are absent upstream;
independent fit calls replace previous fitted models.

## Public API, resources and safety

Own C++17 JSON value types expose configuration, stages, symbols, codebooks, fitted models,
encode/decode and accounting. JSON is a native C++ dependency, never a Python runtime.
A package C11 ABI exposes capacity-checked JSON requests/results for all operations; failures set produced=0 and do not modify caller output. Callers
retain ownership. No overread/overwrite or alignment assumption is permitted.
Stage/model APIs reject invalid IDs, nonfinite derived state and invalid shape.
Input maximum is 1,048,576 samples across at most 4096 series, codebooks <=65535,
quantizer widths 1..64, physical frame <=256MiB and reconstruction <=4,194,304
samples. Resource rejection is documented separately from semantic source domain.
Malformed frame validation precedes expensive allocation and checks all lengths,
counts, CRC, flags, model ranges, symbol indices, padding and exact consumption.
Default FP environment: binary64 nearest, no fast-math, FP contraction off.

## Frozen verification plan

Direct unmodified classes in tools/oracle.py, exact upstream CKmeans Python
binding, upstream tests, golden and randomized cross-language stage comparisons;
three UCR datasets ECG5000/Chinatown/Coffee first twelve rows, source and binary64
hashes; additional zero/constant/short/extreme/tie cases, parameter boundaries,
missing fills, model reuse, alphabet, partition and batch threads. Decode source
symbols in C++ and C++ symbols in Python; self-contained cold binary decode.
C ABI capacity N/N-1, canaries, immutability, overlap/nonalignment, invalid args,
malformed/truncated/checksum-valid mutations, OOM; ASan/UBSan/LSan, TSan on threaded
paths, fuzz; GCC/Clang and second architecture when tools available. Full evidence
identity, SBOM, standalone installation consumer, offline source/patch/build replay
and package-outside indexed recovery audit precede G6. Until required paths pass,
no REWRITE_DONE or FULL_PARITY may be claimed.

Implementation audit extension: quantizer widths 33..64 are included, with direct
NumPy int64 boundary-cast comparisons. Widths beyond the source storage integer
size are rejected explicitly; this extends the initial planned width range.

## Audited clarifications (2026-10-20)

Direct Python/Cython execution exposed observable fABBA `splist` differences.
`source_backend=python|cython` preserves both, in native C++: Python norm1/norm2/
lexi counts remain 1; Cython counts actual members and PCA diagnostics store
centered coordinates. QABBA's PCA diagnostics are not given fABBA semantics.

Native JSON symbol results normalize list/string representation to lists;
inverse accepts strings too. Source ABBA/QABBA reject empty symbol inverses;
fABBA returns [start]. ABBA/QABBA grid alignment can leave a nonpositive final
interval; source reconstruction appends no samples for it. The rewrite preserves
that behavior without division by zero. An explicit codebook model can omit its
training symbols when the inverse request supplies its own symbols. QABBA fill
names are case sensitive, whereas fABBA names are case insensitive.

QABBA stores original start values before missing-value filling. A missing first
value therefore does not yield a finite recoverable source object; native fit
rejects that state. All-missing mean/median and finite inputs whose derived
arithmetic overflows are rejected explicitly. Source hangs/undefined/nonfinite
results are recorded as diagnostics, never counted as successful parity. Source
widths >64 fail NumPy integer conversion in the frozen runtime; native rejects
them before executing. Wide-bit cast behavior at 63/64 is tested exactly.

Per-object codebook fitting is part of encoding, including on UCR TEST rows, and
is fully serialized; no corpus model or parameters are tuned on TEST. A separate
TRAIN-first-row model / TEST transform suite verifies codebook reuse. Natural
inputs and shared synthetic profiles are frozen and hashed separately. IEEE
extrema fixtures that overflow the algorithm arithmetic are qualification
rejections, not transformed into ordinary signals.

Persistent OOM is tested. The bundled JSON dependency has a no-allocation
destructor for the bounded-depth request domain and handles null partially
initialized values during cleanup. JSON object/array construction in core code
avoids GCC 11's nested-initializer-list exception cleanup defect; Clang is the
independent control. The retained CKmeans kernel uses local sort state, RAII
storage and initialized auxiliary statistics; numerical labels/centers remain
differentially checked against the unpatched upstream kernel.
