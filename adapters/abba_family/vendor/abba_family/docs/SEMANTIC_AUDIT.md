# Source-language, numerical and state audit

Inputs and intermediate arithmetic use IEEE binary64. Scalar translations keep
upstream operation order in segmentation, length/increment normalization,
quantization, and reconstruction; `-ffp-contract=off`, no fast-math. Per-coordinate
strided reductions and the image contiguous NumPy pairwise reduction are separate
helpers. Differential tolerance applies to numeric stages, not to labels,
symbols, quantized integer decisions or segmentation boundaries. NumPy 1.24.3
indirect introsort, including the exact heap fallback tie decisions, is retained
as a structured BSD translation using safe index addressing.

Python unbounded integers are not used for unbounded C++ allocation or shifting.
Counts/offsets use size_t after bounds checks; serialized fields use explicit
unsigned little-endian widths. Signed quantizers use explicit range calculations,
round-to-even and NumPy-compatible int64 overflow conversion at the 64-bit upper
boundary. Native tests cover all widths 1..64; source differential includes
1/2/7/8/9/15/16/17/31/32/33/48/53/54/63/64. Widths >64 throw in the frozen NumPy
pipeline and are rejected early natively. Malicious frame widths/lengths are
checked before narrowing; no shift by the machine width is used.

Segmentation compares source squared error to tolerance (ABBA norm2 squares its
input tolerance); it is not a pointwise error bound. The source ABBA sqrt then
square error sequence is retained. The learned codebook can alter duration.
Nonpositive final ABBA/QABBA intervals append no samples, matching source
arange semantics without performing source division by zero. fABBA cumulative
length rounding is upward at half boundaries; ABBA/QABBA use ties-to-even.

ABBA finite-scaling KMeans uses local MT19937 with NumPy RandomState-compatible
uniform sampling, kmeans++ trials, restarts, convergence and frequency remapping.
The retained CKmeans sort comparator now captures the call's data pointer;
RAII replaces manual arrays. Source kernel inputs/results are differential
checked, including all three DP methods. Unseeded execution has property tests;
no single stochastic labeling is asserted equal to an independent random run.

fABBA Python and Cython differ in diagnostic splist group sizes and PCA starting
coordinates. Explicit source_backend preserves both. Source PCA degeneracy
falls back to norm on a singleton or identical observations. All five sort modes,
custom alphabets, parallel partitions/shared endpoints, missing policies and
image helpers are compared against the complete upstream classes. List/string
return styles are normalized to JSON lists; the API accepts string inverse
inputs as well. Arbitrary wrapper objects/pickle format are not claimed compatible.
The source Model dictionary and symbol/center representation are exercised in
both directions. No Python object is needed by the native runtime.

QABBA source remaps symbols by frequency without reordering centers. The rewrite
preserves that behavior, so fit symbols can differ from transform(training input).
Quantizer parameters and quantized centers are stored in the AFS1 model, fixing
the source representation's lack of persisted affine quantizer state. Native
model/format is explicitly different. The source theoretical center/initial/
quantizer storage estimates are exposed separately from actual container bytes.
All ten source entropy modes are tested; pinned C codec versions match the
reference Python dependencies. Package Huffman/LZW streams are actually
reversible; source accounting-only streams are not presented as an upstream
self-contained binary format.

QABBA original starts are captured before missing filling; a leading missing
sample does not produce a finite recoverable source object and is rejected by
the native fit. QABBA fill names are case sensitive, fABBA case insensitive. An
IEEE finite-extrema signal can overflow arithmetic or hang upstream: this is a
documented safety rejection and source diagnostic, not an ordinary parity PASS.
Dataset_Verify IEEE fixtures are audited separately from finite, representable
constant/periodic/random/slow profiles. Signed zero input bits are preserved by
native parsing; reconstruction is lossy and does not promise signed-zero identity.

No global fitted model, RNG or symbol dictionary survives a request. Explicit
JSON model tokens define reuse; new fit returns a replacement token. Concurrent
requests, partition workers, multi-series shared models and modified/empty
symbols are tested. fABBA permits empty inverses; ABBA/QABBA reject them as the
source does. Models need not retain training symbols when a new sequence is
provided explicitly. No unsupported stream/reset/seek/finalize is simulated.

The C11 API owns temporaries until success and performs a final memmove only
after checking capacity. Capacity failures report the exact required size,
produced=0 and unchanged output. Inputs can overlap output; distinct size
counters cannot overlap input/output. Guard pages verify zero safe overread;
unaligned, overlapping and exact/short capacities are tested. Persistent C++
allocation failures are injected at all reached sites for 24 request profiles,
including all symbol codecs, image fit, model fit and frame decode. C++ RAII
also releases zlib state if output allocation throws. ASan/UBSan/LSan and TSan
provide independent checks of these paths.
