# fABBA algorithm contract

## Identity and profile

- AlgorithmID: `fabba`
- ObjectLevel: `P2_PIPELINE`
- RewriteConclusion: `PARTIAL_REWRITE`
- PortMethod: `TRANSLATED`
- CompatibilityTarget: `SEMANTIC`
- Upstream commit: `4066a5fc778f50f4bee1c41d8f3ab3ee4a3ff6ad`

`ABBA_fABBA_compression_stage` is a duplicate stage reference and receives no
second AlgorithmID. The profile is `stable-norm2-scl1-v1`: binary64 univariate
input, `tol=0.1`, `alpha=0.1`, `sorting=2-norm`, `scl=1`, `max_len=unlimited`,
and `alphabet_set=0`. `tol`, `alpha`, `scl`, and `max_len` remain explicit
container parameters. NaN, infinity, empty, singleton, multivariate, image,
alternate sorting, and alternate alphabet paths are outside this profile.

The public C++ `parallel_compress` stage implements upstream partitioned
compression. `partition` controls the number of equal contiguous work units;
`threads` bounds concurrently launched workers and is clamped to the work-unit
count. As upstream does, partitions consume `floor(N/partition)` samples and
discard the remainder. `ParallelExecutionInfo` reports requested/used
partitions and threads plus consumed/discarded sample counts. Results are
returned in input partition order. The v1 container pipeline stays unpartitioned
because the upstream partition stage does not define a self-contained joined
reconstruction format; partitioned capability is exposed directly at its
upstream stage boundary.

## Segmentation

For candidate endpoints `start,end`, let `increment=x[end]-x[start]` and let
`error` be the squared binary64 residual from their straight line. Accept when

```text
error <= tol * (end - start - 1) + DBL_EPSILON
and end - start - 1 < max_len.
```

On rejection, emit the last accepted `[length,increment,error]` and restart at
`end-1`. Positive integer lengths sum to `sample_count-1`.

## Digitization

Compute population standard deviations for raw `[length,increment]` pieces.
Each zero standard deviation is replaced by one. This prevents the upstream
division-by-zero/NaN path for constant piece dimensions. Scale to
`[scl*length/std_length, increment/std_increment]`. Sort by Euclidean norm with
the original piece index as an explicit stable tie-break. This removes the
platform-dependent tie behavior of upstream default `numpy.argsort`. Stable
tie ordering and zero-standard-deviation substitution are the two intentional
semantic stabilizations in the profile.

Visit unassigned pieces in sorted order. Each becomes a starting point and the
next cluster ID. Assign every later unassigned piece whose squared Euclidean
distance from that starting point is at most `alpha^2`; stop once its norm minus
the starting norm is greater than `alpha`. Cluster centers are arithmetic means
of the original, unscaled pieces. Symbols equal cluster IDs, so the upstream
alphabet order does not alter numeric labels.

## Inverse and error contract

Expand symbols through the codebook. Quantize lengths sequentially using Python
nearest-even `round`: carry each correction into the next length, replace an
intermediate zero by one and subtract one from the next length, then round the
last length. Reconstruct each segment by linear interpolation from the previous
endpoint, excluding duplicate joins.

Piece lengths, labels, symbols, starting-point indices, reconstructed count, and
container decoding are exact. Other stage values and reconstructed samples use
`abs <= 1e-10 + 1e-12*abs(reference)`. Dataset RMSE and maximum absolute error
must match the oracle under the same tolerance. This is source-relative lossy
equivalence, not a universal value-domain bound.

## Self-describing container v1

All fields are little-endian. The fixed 72-byte header is:

```text
offset size field
0      4    magic "FABB"
4      2    version = 1
6      2    profile flags = 1
8      8    original sample count
16     4    symbol/piece count
20     4    center count
24     8    segmentation tolerance
32     8    aggregation alpha
40     8    max_len, UINT64_MAX means unlimited
48     8    scl
56     8    first input value
64     4    sorting ID = 2 (stable 2-norm)
68     4    alphabet set ID = 0
```

The header is followed by `center_count` pairs of binary64 length/increment
centers, `piece_count` uint16 symbols, and CRC-32 over all preceding bytes.
Decoder validation covers magic, version/profile, exact size, fixed IDs,
parameters, counts, symbols, finite centers, quantized lengths, output length,
and checksum.

`SerializedBits = 8 * physical_container_bytes`, external side information is
zero, and header + codebook + symbol stream + checksum equals `FinalBits`.
