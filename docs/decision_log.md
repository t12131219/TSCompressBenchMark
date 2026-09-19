# Engineering Decision Log

## D001 Dataset identity excludes local paths

DatasetID hashes the source content digest, byte count, format, parser policy, logical
semantics, expected structure, split policy, and canonical policy. Display names,
absolute locations, and the local relative file path do not define identity. This lets
the same bytes and semantics retain an ID after relocation while any content or semantic
change produces a new ID.

## D002 CSV parsing is schema directed

Layer 1 uses Python's strict CSV parser and per-column NumPy buffers. Dates accept only
manifest-listed formats and naive source times are interpreted as UTC only because each
manifest states that policy. Numeric values are parsed directly into declared dtypes;
there is no Pandas inference, sorting, missing-value repair, or homogeneous matrix cast.

## D003 PEMS has no synthesized timestamp

The four NPZ archives contain only a `data` array. In the absence of provenance for a
sampling interval or epoch, their timestamp origin is `NONE`. Their `[time, sensor,
feature]` shapes remain native three-dimensional arrays.

## D004 National illness remains heterogeneous

The percentage columns use little-endian float64 buffers; the age, total, provider, and
target count columns use little-endian int64 buffers. The canonical physical view is a
structure-of-arrays column set, preventing NumPy from silently promoting every field to
float64.

## D005 Weather header corruption is provenance

The raw UTF-8 header already contains replacement characters. Its exact bytes and hash
are frozen in the manifest; normalized display labels are separate metadata and never
rewrite the raw file or DatasetID source content. The one duplicate timestamp is allowed
and preserved, not deduplicated.

## D006 Canonical binary is sequential and C readable

`tscb-canonical-v1` uses fixed little-endian file and buffer headers, canonical JSON
metadata, ordered raw buffers, per-buffer hashes, and one whole-file hash. It does not
embed Python objects, pickle, NumPy private ABI, or local paths. The matching C header is
`native/include/tscb_canonical_v1.h`. The standalone inspector in
`native/tools/inspect_canonical_v1.c` walks metadata and every declared buffer without
NumPy or Python.

## D007 Source inventory is not codec qualification

The 221 spreadsheet-derived logical entries are classified by deterministic rules, but
they do not automatically receive AlgorithmIDs. TSBench rows remain reference-only;
algorithm candidates remain pending until source/API/build/license and object-level
ambiguity are reviewed. Shared repositories retain SourceArtifactIDs independently from
the multiple logical algorithms or pipeline stages that may use them.

## D008 Negotiation and validation are framework decisions

Codec manifests declare facts. The framework alone assigns the four capability states,
constructs explicit adapter operations, validates post-adapter logical content, routes
lossy transformations, and decides task status. An adapter cannot turn a mismatch into
PASS, hide a copy, sort data, or remove an unsupported task.

## D009 Adapter and algorithmic preprocessing are distinct

Compatibility adapters only satisfy declared physical/API requirements and expose their
copy/allocation/padding/timing evidence. Delta, quantization, model training, and other
algorithm stages use a separate ordered A/B/C/D preprocess plan and validator. Loss
budgets and timing cannot move silently between these two contracts.

## D010 Configuration and task identities retain the full task universe

ConfigID hashes expanded codec defaults plus framework parameters such as the benchmark
seed. Cartesian sweep points that violate a closed parameter schema remain records with
SCHEMA_ERROR. TaskID then binds DatasetID, AlgorithmID, ConfigID, Track, and ProfileID;
deterministic task JSONL includes unsupported and lossy-routed tasks instead of deleting
them before execution.

## D011 Comparability narrows hierarchically

SemanticComparabilityKey defines the compression task. ExecutionComparabilityKey embeds
that semantic key and adds timing, adapter boundary, ISA/device/thread/fallback, layout,
alignment, tail, allocation/cache/GC/JIT facts. ResourceProfileKey embeds the execution
key and adds resource attribution and sampling. Unknown facts are explicit values and
are never removed to manufacture a direct comparison.

## D012 Execution uses an explicit update/finalize protocol

The adapter protocol exposes output bound, update, finalize, accounting, decode, and
close as separate operations. Output capacity is runtime memory, while only used bytes
after finalize enter the ledger. Batch-0 frames include a real footer and checksum so a
missing Finalize is observable rather than a zero-cost no-op. Repeated Finalize behavior
is exercised in the boundary suite.

## D013 JSONL is the recoverable raw-run authority

`run_components.jsonl` is append-only and contains the complete nested RunRecord. The
flat `runs.csv` is an atomically rebuilt projection under the same run-store lock. This
means a crash cannot require deleting or rewriting raw evidence: an idempotent retry can
recover the CSV projection from JSONL, while a duplicate RunID with different content is
rejected.

## D014 Layer 3 qualification and Layer 4 measurement share one lifecycle

Layer 3 performs boundary/safety preflight. Layer 4 then wraps the same update, finalize,
accounting, independent decode, and correctness lifecycle with warmup, minimum-duration,
timing, and resource collectors. A separate speed-only loop is forbidden. Statistical
aggregation remains a Layer 5 responsibility and cannot be inferred from qualification
or warmup observations.

## D015 Formal and qualification measurement profiles are explicit

`FORMAL` is the publishable measurement mode and enforces the contract minimums:
warmup count/time, ten repetitions, and one-to-three seconds of selected-scope work in
each repetition. `QUALIFICATION` exists for short framework and adapter checks, records
the same evidence shape, and cannot make a third-party run leaderboard-eligible. The
distinction is frozen into ProfileID and therefore into TaskID/comparability evidence.

## D016 Unavailable resource and workload evidence is null with a reason

The initial synchronized collector implements Linux PROCESS evidence with getrusage and
`/proc`. A request for process-tree cgroup, device, system E2E, perf, or energy data is
not silently relabeled as PROCESS and never becomes numeric zero. Requested/actual
scope, availability, reason, and null measurement fields are retained. Query and
streaming observations are similarly capability-gated; false capability never produces
synthetic latency.

## D017 Layer 5 is a deterministic read-only derivation

Statistics consumes `task_plan.jsonl` as the frozen coverage denominator and
`run_components.jsonl` as the authoritative repetition evidence. Both files are hashed
before analysis. Eligibility is analysis-specific and every rejection gets reason codes;
there is no adapter callback and no correctness reclassification in reporting.

Per-dataset summaries require the same ConfigID, ExecutionPathHash, ProfileID, and schema.
Only complete FORMAL PASS groups enter aggregation. Corpus metrics are a second derived
layer using explicit micro and geometric-mean formulas. Direct comparison tightens from
Semantic to Execution to Resource keys; Pareto and dense metric ranks stay within the
appropriate key and Coverage is published separately without a weighted total score.

## D018 The first native codec is a pinned lzbench LZ4 Frame closure

Phase 4 starts with LZ4 Frame as required by the engineering plan and the spreadsheet-
to-benchmark analysis. The source authority is lzbench commit
`fa871e66b3543a70fd4d060f7c12719343ff4ac3`; only the reviewed LZ4 1.10.0 translation-
unit closure and license notices are copied into the project. Files are kept unmodified,
while project-specific behavior lives in a separate stable C ABI shim. The local
upstream LZ4 checkout is comparison evidence, not a second execution authority.

## D019 Output bounds are conservative capacities, not expected sizes

The first real codec exposed an oracle-specific assumption in the original boundary
validator: it required `bound - 1` to fail. Native compression bounds such as
`LZ4F_compressBound` are conservative, so valid data can fit below them. The corrected
contract requires the declared bound to succeed safely and account only actual written
bytes. A `bound - 1` attempt may either fail with a stable capacity error or succeed if
it independently finalizes, stays within capacity, round-trips, and passes canary
checks. A genuinely under-reported bound still fails the normal bound-capacity case.

## D020 LZ4 uses one self-contained frame inside a versioned descriptor container

Each independently measured object serializes the routed canonical buffers into a
versioned TSCB descriptor prefix followed by one complete LZ4 frame. The container
records buffer order, dtype, shape, and byte lengths, allowing independent decode
without Python objects or out-of-band metadata. `LZ4F_compressEnd` is mandatory;
physical size and structural accounting are computed from actual finalized bytes, not
capacity. Python FFI and container work are included in the declared PIPELINE boundary.
The adapter currently makes no streaming, query, or random-access claim.

## D021 Zstd uses the benchmark-vendored single-thread frame implementation

The second native codec uses Zstd 1.5.7 from the same pinned lzbench commit as the
benchmark evidence. Its `common`, `compress`, and `decompress` closure is copied
unmodified; dictionary builder, deprecated/legacy implementations, CLI, examples, and
the multithread compression translation unit are excluded. The registered build also
disables assembly and BMI2 runtime dispatch, so `actual_isa=SCALAR`, single-thread, and
no-dictionary claims match the loaded binary rather than only the experiment request.
The separate local `facebook/zstd` checkout differs from the lzbench vendored tree and
is comparison evidence only.

The adapter pledges the source size, performs one `ZSTD_e_continue` update, and loops
`ZSTD_e_end` until zero. A nonzero return is never treated as a completed frame.
Dictionary, context reuse, multithreading, streaming workload, query, and random access
remain separate unregistered modes rather than implicit features.

## D022 Comparability labels describe contracts, not codec brands

The first LZ4/Zstd formal comparison showed that algorithm-named values such as
`ONE_LZ4_FRAME` and `LZ4_INTERNAL_BLOCK_TAIL` split otherwise identical semantic and
execution groups. These fields now use the algorithm-neutral contracts
`ONE_SELF_CONTAINED_FRAME_PER_ROUTED_OBJECT`,
`SELF_CONTAINED_TSCB_DESCRIPTOR_PLUS_CODEC_FRAME`, and
`CODEC_INTERNAL_EXACT_TAIL`. AlgorithmID, ConfigID, SourceArtifactID, binary hash, and
ExecutionPathHash continue to distinguish implementations. A regression test requires
the two common byte-frame profiles to share Semantic, Execution, and Resource keys while
retaining different execution paths.

## D023 Snappy raw remains distinct from self-contained codec frames

The third Batch-1 native codec uses the Snappy translation-unit closure compiled by the
pinned lzbench benchmark and the same `RawCompress`/`RawUncompress` API that lzbench calls.
Snappy raw begins with a uint32 varint decoded length and then literal/copy commands; it
has no frame envelope, footer, checksum, dictionary, or finalize bytes. The project still
requires a one-shot Finalize call, which succeeds with zero written bytes and rejects a
second call, so lifecycle evidence remains explicit.

The TSCB descriptor prefix makes a routed object independently reconstructible but does
not relabel the embedded format as a Snappy frame. `snappy-raw` therefore has its own
decodability and block semantics and does not share Semantic/Execution/Resource keys with
LZ4/Zstd frame profiles. Algorithm identity alone is not used to create this separation;
the different physical and lifecycle contract is.

## D024 Brotli uses an RFC 7932 stream with observable FINISH

The fourth Batch-1 codec uses the complete Brotli 1.2.0 common/encoder/decoder closure
vendored by the pinned lzbench commit. lzbench benchmarks `BrotliEncoderCompress` and
`BrotliDecoderDecompress`; the project uses the same implementation through
`BrotliEncoderCompressStream` so PROCESS and every FINISH call satisfy the mandatory
update/finalize lifecycle and native API timing contract. Finalize loops until
`BrotliEncoderIsFinished`; a non-finished call is never accepted as a complete stream.

The registered object is a versioned TSCB descriptor followed by one RFC 7932 stream at
quality 5, lgwin 22, generic mode, single thread, with Brotli's built-in static dictionary
and no external dictionary or checksum. Brotli stream bytes are counted exactly as the
routed data bucket, while descriptor and prefix bits remain metadata/container bits.
Because the stream, dictionary, and finalize contracts differ, Brotli has separate
Semantic, Execution, and Resource keys from both LZ4/Zstd frames and Snappy raw.

## D025 DEFLATE keeps the benchmark's zlib envelope and exposes Z_FINISH

Spreadsheet-listed CPU DEFLATE is implemented using zlib 1.3.2 vendored by the pinned
lzbench checkout, rather than mixing upstream or libdeflate sources. lzbench uses
compress2/uncompress, which produce/consume RFC1950 zlib streams containing RFC1951
DEFLATE; this is neither raw DEFLATE nor gzip. The registered `deflate-zlib` defaults
are level 6, windowBits 15, memLevel 8, default strategy, no preset dictionary, one
CPU thread and mandatory Adler32. Nondefault registered levels/windows have separate
ConfigIDs; raw/gzip/dictionary/strategy variants are unregistered.

The C shim uses Z_NO_FLUSH followed by Z_FINISH until Z_STREAM_END, making update and
Finalize observable and timed. The decoder creates fresh inflate state and requires
exact decoded length plus complete input consumption. The TSCB descriptor supplies
decoded allocation length independently of encoder state. Prefix and zlib header are
container bits, descriptor JSON is metadata, Adler32 is checksum, and all physical
DEFLATE bytes are routed payload bits. Different envelope/decodability/lifecycle
contracts keep its Semantic/Execution/Resource groups separate from the other formats.
Native timing is API-only and explicitly not lzbench-equivalent; pipeline includes the
Python container, lifecycle and accounting. The local upstream comparison is 1.3.2.1
and remains comparison evidence, not an implicit baseline upgrade.

The ELF build uses `-Wl,-Bsymbolic-functions` to bind internal zlib calls to the
vendored library, not a competing globally loaded implementation. A deliberately
failing deflateInit2_ loaded with LD_PRELOAD reproduced the original binding risk;
the final build passes the same ABI smoke under that interference. `ldd` shows only
libc/loader dependencies, not a system libz dependency. Earlier runs are retained but
the admission evidence refers to the final symbol-bound build.

## D026 XZ uses a bounded single-call stream and charges its index

Spreadsheet Value-Compress!B9 lists LZMA / xz. `xz-stream` uses lzbench's unmodified
xz 5.8.3 closure, preset 6 by default (0-9 registered), one scalar CPU thread and
LZMA_CHECK_NONE. Mandatory structural CRC32 remains charged. Internal LZMA2 history
is not an external dictionary; serialized properties remain metadata.

lzbench uses MT stream APIs and CONCATENATED | IGNORE_CHECK decoder flags. These
choices do not satisfy the registered strict single-thread object contract and are
not copied. lzma_easy_buffer_encode has the documented lzma_stream_buffer_bound
contract and completes all block/index/footer work in the call. Mandatory project
Finalize acknowledges completion with zero bytes and no new native API timing;
repetition is rejected. This is not streaming support. Fresh-context decoder flags
0 require exact consumed/produced lengths. Python independently validates the
registered zero/one-block LZMA2 format before allocation.

TSCB/XZ envelope, descriptor/block metadata, index, structural checksums, block
alignment and payload have exact non-overlapping buckets. Internal header/index
padding stays in its field; index presence does not imply random access/query.
Different format/lifecycle contracts retain separate comparison keys. Native timing
includes intrinsic encode allocation/finish, but is not lzbench-equivalent. Static
PIC liblzma with local ELF binding passes a globally competing symbol test.

Initial diagnostic runs rejected an inherited DEFLATE window_bits sweep despite
the CLI envelope's PASS. Admission is based on raw task eligibility and report
coverage, not exit alone. The sweep was corrected, config regression tests added,
and all ten final repetitions checked. Rejected runsets remain append-only.

## D027 LZ77's zlib mapping is not a second independent codec

Original spreadsheet Value-Compress rows 2 (LZ77) and 4 (DEFLATE) both reference
madler/zlib and RFC1951. The analysis explicitly implements LZ77 through zlib.
Source review finds dictionary matching in deflate.c and Huffman block output in
trees.c; the benchmark entry calls compress2/uncompress. There is no independently
serialized pure LZ77 object specified by this mapping.

The plan requires distinguishing logical asset names from executable primitives,
codecs and pipelines. Shared checkout alone is not enough to justify a new codec:
here the entire selected executable contract is identical, not a distinct use of
the same repository. `lz77` therefore resolves to `deflate-zlib`, with the same
AlgorithmID, SourceArtifactID, ConfigIDs and execution/comparison keys. A separate
closed/pinned audit record carries logical-name evidence and CodecAliasID. Canonical
registry enumeration/counts/rankings remain unchanged. Both names in a config
produce one canonical task, and alias evidence is frozen and checked on resume.

No new vendor tree, shim or baseline upgrade is needed. The existing native source
was compared and revalidated, then the selectable mapping passed Layers 1-5 with
new raw evidence. Reports retain the real DEFLATE identity. Isolated matching
would be P0; an independently decodable pure LZ77 stream would require separate
source/format admission. Neither is falsely marked qualified by this change.

## D028 Spreadsheet LZSS retains the original Rust wire format, not LZSSE

The master plan and Value-Compress row 3 identify alexkazik/lzss. Local source
review finds pure Rust 0.9.1, not a C/C++ library. The analysis's independent
lzbench LZSS claim is unsupported: its registered LZSSE2/4/8 entries use different
formats. Benchmark-first sourcing is a preference, not authority to substitute
another implementation. The spreadsheet source's own Criterion benchmark informs
EI10/EJ4 parameters; its timing/summary loop is not imported. Python drives original
source through C ABI, as allowed by plan section 4, without prematurely rewriting it.

The fixed generic safe/std/alloc stack API is a separate P1 byte-view variant.
Its versioned descriptor container includes all shape/dtype/length/channel metadata;
the initial 0x20 dictionary window is fixed public format knowledge, not side data.
BitWriter.flush runs inside compression, and mandatory zero-byte Finalize records
completion. Native auxiliary timing surrounds original source API calls inside
the bridge, excluding bridge preparation/error handling, explicit validation and
Python work. Initial bridge-inclusive measurements remain retained and superseded.

Original EOF-tolerant decoding alone is insufficient: independent Python/native
validators require complete tokens, exact output length and at most seven zero
tail bits. They supplement, not replace, the original decoder. Token and padding
bits are charged separately with one final rounding. No checksum does not imply
general corruption detection; common benchmark correctness still validates all bits.

Offline builds preserve original library/generator/tests and pinned void 1.0.2.
Rust codec/FFI ASan and C++ ASan/UBSan are real; prebuilt std is uninstrumented and
LSan disabled. void's declared MIT archive lacks license text, so local running is
allowed but redistribution requires review. Alternate parameters/family members,
query/continuous streaming and future C/C++ rewrites remain unqualified. The final
five-layer evidence and admitted coverage are recorded in docs/lzss_raw_self_check.md.


## D029 LZSSE8 is an explicitly requested separate SSE codec

The user explicitly requested LZSSE8 on 2026-09-18. This is a scoped exception
to the spreadsheet-only selection rule: spreadsheet LZSS still means alexkazik/lzss,
not this format. LZSSE8 Optimal Parse from lzbench commit
`fa871e66b3543a70fd4d060f7c12719343ff4ac3`, level12, single-thread SSE4.1, receives
its own AlgorithmID/source/adapter and all three comparison keys. Fast and the
existing unfinished LZSSE2 are not admitted by this work.

Only five needed source/license/reference files are copied. Vendor bytes remain
unchanged; a hashed patch is applied out of tree for allocation failure, unaligned
integer access and pointer-safe buffer thresholds. Neither codec logic nor its
wire format is rewritten. Direct original-source comparisons are distinct from
project safety tests; no absent upstream test suite is claimed as passed.

The raw-length equality mode is intrinsic to LZSSE8, not a hidden alternate codec.
The unique container includes dtype/shape/length/channel descriptors and an explicit
raw-storage flag, all charged. Structural validation proves length/offset/tail and
SIMD load/store bounds before calling the native decoder. No checksum is invented.

Python retains standard enforcement, Track routing, eligibility and all five layers.
Native timing includes actual compression/decompression APIs (even empty inputs),
but not state lifecycle or structural prevalidation. CORE includes wrapper/FFI/container
work, and zero-byte Finalize is required without adding native API time. SSE4.1 is
now explicitly mapped to the runtime CPU flag; unavailable ISA is not scalar fallback.
The supplied qualification/formal configs fix CPU0 on this host; this affinity is
machine-specific and must be reviewed on another host. Formal evidence must follow
the completed regression/sanitizer sessions and satisfy every raw repetition gate.
