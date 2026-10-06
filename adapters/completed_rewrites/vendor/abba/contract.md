# ABBA algorithm contract

## Identity and supported profile

- AlgorithmID: `abba`
- ImplementationID: `abba-canonical-cpp`
- ObjectLevel: `P2_PIPELINE`
- RewriteConclusion: `PARTIAL_REWRITE`
- PortMethod: `TRANSLATED`
- CompatibilityTarget: `SEMANTIC`
- Upstream: `nla-group/ABBA` commit
  `614d56841cd2f1c2925cea4d2c2648a7b2ac791d`

The default canonical profile is `ckmeans-scl0-norm2-v1`. It translates the
Python adaptive segmentation, digitization orchestration, inverse
digitization, ties-to-even length quantization and linear reconstruction. It
retains and audits the upstream CKmeans 1D dynamic-programming kernel.

The default fixes `scl=0`, `norm=2`, `c_method=kmeans`, `seed=true` and the
CKmeans `linear` method. The C++ API also supports finite-positive `scl` through
a deterministic sklearn-compatible KMeans implementation, `scl=inf` through
length-only CKmeans, `norm=1/2`, and incremental clustering with the upstream
`weighted` and `symmetric` controls. Compression tolerance, digitization
tolerance, `min_k`, `max_k`, `max_len`, `scl`, `norm`, clustering method,
weighting and symmetry are explicit encoder controls.

The v1 container stores the realized centers and symbols, so decoding does not
depend on the encoder-side clustering method. Alternate clustering is exposed
by the public C++ API; the stable C ABI v1 retains its original default profile.

## Input and segmentation

Input is one contiguous univariate series of at least two finite IEEE-754
binary64 values. NaN, infinity, empty and singleton inputs are rejected.

Starting with `start=0` and `end=1`, a candidate segment has increment
`x[end]-x[start]` and squared L2 residual from the straight line through both
endpoints. It is accepted when

```text
error <= compression_tol^2 * (end - start - 1) + DBL_EPSILON
and end - start - 1 < max_len.
```

On rejection, the last accepted `[length, increment, error]` is emitted and
the next segment begins at `end-1`. Segment lengths are positive integers and
sum to `sample_count-1`.

## Digitization

For `M` pieces and `N=1+sum(length)`, the variance bound is

```text
(6 * (N-M) / (N*M)) * (digitization_tol^2 / 0.2^2).
```

Increments are divided by their population standard deviation; a standard
deviation at or below binary64 epsilon is replaced by one. CKmeans chooses the
first `K` in `[min_k,max_k]`, capped by the number of unique increments, whose
maximum population cluster variance is strictly below the bound; otherwise it
uses the capped maximum. The increment center is the CKmeans mean rescaled to
the input domain. The length center is the arithmetic mean of member lengths.

For the default path, clusters are renamed by descending population. Equal populations are ordered
by the first occurrence of their original CKmeans label. Symbols are unsigned
16-bit codebook indexes. This freezes the upstream `Counter.most_common()`
tie-break and avoids the version-dependent sklearn path.

Finite-positive KMeans uses NumPy RandomState-compatible MT19937 sampling,
k-means++ local trials, ten restarts and Lloyd iteration. Incremental clustering
uses the frozen source's norm, weighted and symmetric assignment rules. All
alternate paths use deterministic cluster renaming and container materialization.

## Inverse and lossy correctness

Each symbol expands to its `[mean_length, mean_increment]` center. Lengths are
quantized in sequence using Python `round()` semantics (nearest, ties to even).
Rounding correction is carried into the next piece; a zero current length is
changed to one and one is subtracted from the next piece. The final length is
rounded ties-to-even. Invalid nonpositive or nonfinite final lengths are
rejected. The first input value is then followed by per-piece linear
interpolation, excluding duplicate join endpoints.

The formal semantic error contract is source-relative and stage-specific:

- piece lengths, raw labels, remapped symbols and reconstructed length are exact;
- piece increments/errors, codebook centers, quantized pieces and reconstructed
  samples match the frozen oracle with `abs <= 1e-10 + 1e-12*abs(reference)`;
- every accepted source and rewrite segment satisfies the segmentation
  inequality above within the same binary64 comparison;
- for every dataset series, rewrite RMSE and maximum absolute error against the
  original equal the oracle metrics within `1e-10 + 1e-12*abs(reference)`;
- all stored centers and reconstructed samples are finite.

This contract preserves upstream loss, rather than asserting a universal
value-domain error ceiling that upstream ABBA does not provide.

## Self-describing container v1

All integers and binary64 bit patterns are little-endian. The fixed 64-byte
header is:

```text
offset  size  field
0       4     magic "ABBA"
4       2     version = 1
6       2     profile flags = 1
8       8     original sample count
16      4     symbol/piece count
20      4     center count
24      8     compression tolerance
32      8     digitization tolerance
40      8     max_len, UINT64_MAX means unlimited
48      4     min_k
52      4     max_k
56      8     first input value
```

It is followed by `center_count` pairs of binary64 length/increment centers,
`piece_count` uint16 symbols and a four-byte CRC-32 over every preceding byte.
The decoder validates magic, version/profile, exact size, counts, parameters,
symbols, finite values, quantized lengths, reconstructed count and CRC before
returning output.

`SerializedBits = 8 * physical_container_bytes` and
`ExternalSideInformationBits = 0`. Header, codebook, symbol stream and checksum
bytes are individually reported and must sum to `FinalBits`. The first value,
configuration and original length are therefore charged, not external side
information.
