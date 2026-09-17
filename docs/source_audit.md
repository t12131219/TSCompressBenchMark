# Open Source and Benchmark Source Audit

## Scope and machine record

The repeatable audit is implemented by `tools/audit_sources.py`; its current machine
record is `registry/sources/source_catalog.json`. It read the existing 221 logical
entries and scanned the 72 configured repository records under the shared, read-only
`Source_Code` tree. Generated/build directories and VCS internals were excluded, while
vendored paths were counted separately.

Current result:

- 221 logical algorithm or benchmark entries.
- 72 repository records, of which 71 are available and clean.
- 145,830 files scanned after the documented exclusions.
- 44 repositories contain benchmark/performance evidence; 40 contain test evidence;
  60 expose a license/notice file within the audit depth.
- The catalog records commit, shallow/dirty state, origin, submodules, language counts,
  build entry points, license/readme evidence, and bounded benchmark/test path evidence.

This inventory is evidence, not codec qualification. A folder, function, or upstream
benchmark result does not become an AlgorithmID or PASS result automatically.

## Behavior reviewed for framework decisions

TerseTS provides a useful narrow C ABI and a Python binding with explicit native memory
ownership. Its Python wrapper also converts non-contiguous or non-float64 NumPy input by
calling `ascontiguousarray(..., dtype=float64)`. This project therefore puts dtype and
layout decisions before adapters; such a conversion must become a visible compatibility
operation and can never disappear inside core timing.

Sprintz distinguishes row/column layouts and 8/16-bit integer data, removes timestamps
from its value benchmark, and documents 32-bit padding for some integer backends. The
new data layer preserves T and V separately, records physical layout, and keeps semantic
raw bits independent from later padding. Float-to-integer quantization will be a lossy
preprocess in Layer 2, not a loader action.

lzbench demonstrates a large codec function table, output-bound handling, chunk loops,
round-trip byte comparison, and minimum-time execution. Its upstream aggregation and
byte-only semantics are not imported: the V2 runner will retain raw repetitions and
apply dataset, accounting, correctness, and comparison contracts itself.

ALP/FastLanes provides useful special-value tests, kernel-level measurements, metadata
structures, and end-to-end benchmark separation. Its internal iteration counts and
intermediate size metrics are implementation evidence, not the V2 repetition or
FinalBits contract.

The engineering plan additionally records reviewed behavior for zfp, Serf, NeaTS,
ClickHouse, Prometheus, TimescaleDB, Apache TsFile, LZ4, and Zstd. Those records are kept
as onboarding evidence and will be revalidated against the actual translation-unit
closure when each adapter is implemented.

## Acquisition decision

No new network repository was acquired during Layer 1. The local source collection
already contains 22 explicit TSBench entries and enough benchmark/test evidence to
design the control plane. Future acquisitions must be isolated, licensed, commit-pinned,
hashed, and added to a source lock before use. No algorithm source has been copied into
this project because Layer 1 does not need an algorithm build closure.

## Layer 2 repeat audit and classification

The source audit was rerun on 2026-09-12 before Layer 2 implementation. Ignoring only
the generation timestamp, the regenerated catalog was semantically identical to the
frozen catalog: 221 logical entries, 72 repository records, 71 available and clean
repositories, and 145,830 scanned files. The shared source tree was not modified.

Layer 2 adds versioned classification rules rather than treating spreadsheet rows as
ready codecs. Every source row is assigned a track/role and candidate ObjectLevel set;
all algorithm candidates remain `PENDING_SOURCE_ONBOARDING_REVIEW`, while the 22 TSBench
rows are `REFERENCE_ONLY_NO_ALGORITHM_ID`. This preserves ambiguity where a row may name
a primitive, pipeline, system feature, or several implementations. A concrete
AlgorithmID is created only by a complete reviewed codec manifest.

The repeat review checked the implementation evidence used by the negotiation design:
TerseTS performs a hidden contiguous float64 conversion in its Python wrapper; lzbench
contains useful codec tables, chunk/output-bound handling, round-trip checks, and timing
loops but different aggregation semantics; Sprintz exposes row/column and padding
assumptions; LZ4 and Zstd expose explicit bound/finalization contracts; Prometheus XOR2
uses joint timestamp/value control bits. These behaviors informed contracts and tests;
none of their benchmark results or fairness decisions were copied.

## Layer 3 repeat audit and execution evidence

The audit was rerun on 2026-09-15 immediately before and after the Execution &
Validation implementation. It again found 221 logical entries, 72 repository records,
71 available clean repositories, and 145,830 files after generated/build exclusions.
The language census included C, C++, Python, Java, Go, Rust, Zig, CUDA, Cython, shell,
JavaScript/TypeScript, Kotlin, and MATLAB/Objective-C. No shared source checkout changed
and no algorithm source was copied for Batch 0.

The Layer 3 implementation additionally re-read the concrete upstream execution paths
that motivate its lifecycle contract:

- `lzbench/bench/lzbench.cpp` has minimum-duration loops, selectable fastest/average/
  median aggregation, and one final `memcmp` check. V2 retains the useful loop and
  round-trip evidence but does not import fastest-time reporting or its byte-only
  correctness policy.
- `lz4/lib/lz4frame.h` and its frame tests make output-bound, empty-final, footer,
  checksum, and `compressEnd` capacity explicit; the tests also place a canary directly
  after the destination capacity. Those behaviors map to the framework's bound-minus-one,
  Finalize, checksum/accounting, and canary cases.
- `zstd/lib/zstd.h` requires repeated `ZSTD_e_end` calls until zero to prove the frame is
  fully flushed. The Python execution protocol therefore separates `compress_update`
  from `finalize`; a future Zstd adapter must implement its internal finalize loop rather
  than returning early.
- The 22 TSBench entries remain acquisition/reference candidates, not qualified codecs.
The existing 72-repository corpus is sufficient for the current layer, so no unpinned
network acquisition was performed.

## Layer 4 repeat audit and benchmark-behavior review

The source audit was rerun before the Performance Evaluation implementation. Ignoring
only `generated_at_utc`, the regenerated catalog is byte-for-byte semantically identical:
221 logical entries, 72 repository records, 71 available clean repositories, and
145,830 scanned files. No shared checkout changed and no algorithm source was copied;
the performance control plane needs lifecycle oracles, not a new codec build closure.

The Layer 4 implementation rechecked the relevant benchmark paths instead of copying
their loops. `lzbench` provides useful minimum-duration and selectable aggregation
behavior, but V2 retains all raw repetitions and never defaults to fastest-only.
NeaTS separates query selection from timed access and verifies returned values; V2 turns
that into a seeded common query-workload identity. FastLanes contains repeated-access
benchmarks, but fixed/repeated chunk choices are not accepted as random-access evidence.
The ODT resource contract was consulted for the missing field details: encode/decode CPU
time, equivalent cores, core-seconds/GB, baseline/incremental memory, faults, context
switches, I/O, counter multiplex eligibility, energy availability, and explicit
iteration semantics.

## Layer 5 repeat audit and statistics/reporting review

The full source audit was rerun before final Layer 5 verification and remained
semantically identical after excluding its generation timestamp: 221 logical entries,
72 repository records, 71 available clean repositories, and 145,830 scanned files. The
shared source tree was not modified and no codec source was copied for this layer.

The statistics design rechecked upstream benchmark/report behavior without inheriting
its fairness decisions. `lzbench` can select fastest/average/median summaries, but V2
keeps all raw repetitions and uses robust statistics rather than fastest-only results.
ALP/FastLanes CSV reporters and publication scripts demonstrate useful separation of raw
measurements and presentation, but their table-specific aggregation is not a normative
contract here. NeaTS CSV export is implementation evidence only. The ODT Layer 19/21
rules control per-dataset-first aggregation, micro formulas, Coverage, comparison keys,
bootstrap intervals, Pareto views, and two-level raw/summary storage.

## Phase 4 LZ4 Frame source onboarding

The first real-codec onboarding was performed on 2026-09-17 after rereading the master
plan, the expanded edge-case standard, and the C/C++ benchmark analysis. It selected
LZ4 Frame because the plan names it as the first Batch-1 codec and because lzbench
contains a complete vendored LZ4 1.10.0 source and frame test suite. This changes the
earlier layer-specific statement that no codec source had yet been copied; no shared
checkout was modified.

The authoritative source is the clean local lzbench checkout at commit
`fa871e66b3543a70fd4d060f7c12719343ff4ac3`. Only the reviewed build closure was copied:
`lz4.c`, `lz4frame.c`, `lz4hc.c`, `xxhash.c`, their public/private headers, and the LZ4
and library license files. The copied closure digest is
`9309d7d873783fe3450b055151c7d0937e5f04fa32e0d255c131bdd6b661379d`.
The immutable registry identity is
`v2:source-artifact:sha256:68693355ce70e7eb3c672bb55303b7d380d420e3ec0626a4cef0588556f62679`.
Unrelated lzbench codecs, CLI programs, examples, generated outputs, and tests were not
vendored. The selected files were also compared with the existing local upstream LZ4
checkout at commit `0774d055...`; the benchmark-vendored closure remains the execution
authority.

lzbench's codec table invokes the raw LZ4 block API, while its vendored tree contains the
complete LZ4 frame implementation. The adapter deliberately uses the latter because the
normative plan requires a finalized, self-contained LZ4 frame as the first real codec.
That distinction is a recorded limitation rather than an implicit substitution. The
vendored `frametest` passed its deterministic basic and 100-case fuzz run. Release and
ASan/UBSan C-ABI smoke tests passed the required zero, tiny, boundary, and repeated-
Finalize cases. LeakSanitizer was disabled because the host's ptrace policy prevents it;
the limitation remains explicit in the onboarding record.
