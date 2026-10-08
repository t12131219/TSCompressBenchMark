# Stream VByte adapter contract

## Source and object identity

`streamvbyte-u32` consumes the old lzbench uint32 Stream VByte C API unchanged
except for the replayed unaligned-access safety patch. Scalar encode and SSE4.1
decode/scalar tail are compiled explicitly; missing SSE4.1 is unsupported. The
source lock contains file-content SHA-256 hashes, unlike the full-source audit's
path/size inventory. Source URL, commits, license and patch are in
`registry/sources/streamvbyte-lzbench.artifact.json`. Native binding, Python wrapper,
ABI headers, compile recipe and compiled vendor source are pinned by build evidence.

`delta-zigzag-streamvbyte64` is a separate P2 object. It is not an upstream
64-bit Stream VByte implementation. Its manifest declares A: checked int64 Delta
and ZigZag; B: low/high uint32 limbs; C: native SVB; D: descriptor/framing.
The reviewed `STREAMVBYTE_PIPELINE_CTYPES_V1` executor calls separate native
forward/inverse A, B and C APIs. The older complete native composition remains
an independent byte-equivalence reference. The registry binds the exact stage
specification and executor identity; unknown executors still return
`INCOMPARABLE / PREPROCESS_EXECUTOR_NOT_REGISTERED`. A separate Python validator
checks unbounded-integer Delta/ZigZag, low/high limbs, scalar SVB decoding,
each native inverse and D's descriptors/framing. Reversible Delta is classified
as `LOSSLESS_LAYOUT`, following the ODT, with original unit/epoch preserved.

`stage_a/b/c` default to true and can be switched independently. Disabled A
preserves original int64 bits as uint64 with zero seed; disabled B preserves
little-endian bytes as u32 limbs; disabled C writes explicit u32 count plus raw
limbs. These paths are configured representations, not error-driven fallback.
`stage_d` is required for this self-contained P2 object: false creates a retained
schema rejection. Standalone native component experiments use the stage APIs
without claiming the complete P2 format. All stream switches are carried in the
checked descriptor; fresh decoders use it rather than their parameter defaults.

## Input and lifecycle

The native ABI accepts a single little-endian rank-one vector with explicit
count, dtype, bytes and strides. The Python adapter accepts uint32 VALUE or int64
TIMESTAMP according to its identity, validates logical geometry and rejects
validity buffers. A strided Python vector is gathered without a dtype conversion
inside the measured encode call. Misaligned contiguous vectors are copied by
the native shim into aligned staging. The normal framework physical adapter is
still negotiated and recorded separately. Output-bound computation inspects
count/descriptor metadata and does not read vector values.

Maximum original count is 16,777,216. VALUE is UTS only. One update must be
followed by one mandatory zero-byte finalize. Repeated update/finalize and
finalize before update fail. Reset mode 0 starts an independent object; other
modes fail. Fresh decoder contexts need no prior encode call, dataset registry,
model or input. Incremental streaming, query, random access and hidden chunking
are not registered. Capacity failure and checked-delta rejection leave output
and its used length unchanged; retries after these failures can succeed.

The native bound is `prefix + 4 + ceil(words/4) + 4*words`, where uint32 uses
`words=N, prefix=0`, and P2 uses `words=2*max(N-1,0), prefix=20`. Python adds its
descriptor prefix and JSON length. The returned used bytes are the actual size;
unused capacity is never a compressed byte count. Disabled A uses `words=2*N`;
disabled C omits control bytes from the bound. Both encoding and decoding
use bounded internal scratch allocations; decode validates exact control/data
length before calling the upstream SIMD decoder. Declared external overread is
zero. Sixteen bytes of zero padding exist only in staging, not in the stream.

## Stream and accounting

Python prefix: magic `TSCBSVB1` (8 bytes), JSON length (4), SHA-256 of JSON (32),
canonical JSON descriptor, then native bytes. The descriptor freezes algorithm,
track, original count, buffer role/name, dtype, shape, logical bits, original time
unit/epoch, value units and codec stages. Descriptor length is limited to 4096
on both encode and decode; oversized input metadata rejects before output.
Count and encoded geometry are checked before allocating output.
The digest protects the descriptor; it is not a checksum of SVB data bytes.

Native P0 bytes: four-byte count, control bytes, encoded data bytes. Native P2
bytes: magic `TSCBS641` (8), original count (4), first signed int64 seed (8), then
the four-byte SVB word count, control bytes and data. Empty P2 uses a zero seed.
Delta subtraction and inverse addition are checked int64 operations; ZigZag
uses unsigned arithmetic. Disabled A or empty input uses a zero seed placeholder.
No timestamp scaling, sorting, wraparound or error-driven raw fallback is present.

Ledger charges 12 prefix bytes to container, 32 digest bytes to checksum and
the JSON plus native count/identity bytes to metadata. P0 control/data bytes are
VALUE bits. P2 nonempty enabled-A seed/control/data bytes are TIMESTAMP bits; its metadata is the
8-byte magic and two four-byte counts. Every physical byte is charged once;
padding and external side information are zero. Disabled/empty seed bytes are
metadata. Stage contributions are exclusive: A contributes the active seed,
B contributes zero final bytes, C contributes its entire backend stream and
D contributes the remaining framing/descriptor. Intermediate A/B representations
are never added to FinalBits. Accounting is available only
after finalize and verifies the descriptor against the completed encode object.

## Timing, resources and telemetry

CORE covers Python descriptor/framing, FFI, checked transforms where present,
native prevalidation, physical gather/staging and zero-byte finalize. PIPELINE
also includes negotiated preparation and reverse-adapter work. Native timing
is optional/default-on and measures only `svb_encode` / `svb_decode` using
`CLOCK_MONOTONIC`; it excludes descriptors, FFI, staging and the P2 transforms.
Thus native timing is an auxiliary API measurement, not P2 end-to-end latency.
Timing enable/disable cannot change the stream; queries do not clear totals.
Decode calls accumulate. Reset clears totals while preserving enablement.
Failures before the upstream call add no native interval. A failed/backward
clock or counter overflow makes timing unavailable, without suppressing codec work.

Optional `stage_timing` is independent of `native_timing`. Stage wall intervals
cover each Python FFI call and native staging/work; D covers construction or
validation of framing. Python intermediate-array allocation, input gather,
descriptor construction and final destination commit fall outside individual
stage intervals but remain in CORE/PIPELINE. Disabled-stage work remains in
CORE/PIPELINE and its separate timing is null. These stage intervals are auxiliary
observations, not a partition of total pipeline time. Formal records accumulate
all inner iterations; missing intervals invalidate a complete stage total.
Layer 4 summaries and Layer 5 `pipeline_stages.csv` expose normalized statistics.
Native auxiliary rates use actual C input/output word bytes (default P2:
`8*max(N-1,0)`); semantic rates and RawBits keep original `8*N` bytes.
When C is disabled, native API timing is unavailable because no SVB API runs.

`diagnostics.adapter_telemetry` describes negotiated framework copies.
P0 `diagnostics.codec_telemetry` describes internal copies separately. Its native
allocation sizes are derived from the pinned shim's fixed successful code path,
not sampled allocator peak/RSS. It includes native input/output copy sizes,
16-byte staging padding, strided gather when used and Python decode payload
copy. It excludes general Python/allocator overhead. Formal telemetry is a
sample from the last inner iteration, labeled with its index; it must not be
treated as summed bytes across the repetition. RSS and resource totals remain
the independent process measurements. P2 telemetry records each stage's input
and output representation sizes, switches, final contributions and native
padding. These sizes are not measured peak allocation or RSS. Stage timing totals
are stored separately from the last-object telemetry sample.

Qualification timings are retained with eligibility false. FORMAL requires at
least three warmups and 0.5 seconds, at least ten repetitions, at least one second
of selected timing per repetition, single-thread execution, pinned available CPU,
same-repetition correctness, exact ledger and five-layer report evidence. P0/P2
and synthetic/observational domains must remain distinct when interpreting results.
