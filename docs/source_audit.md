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

## Phase 4 Zstd Frame source onboarding

The second real-codec onboarding was performed on 2026-09-17 after rereading the master
plan's Zstd lifecycle and Batch-1 requirements, the edge-case standard, and the C/C++
benchmark analysis. The execution authority is Zstd 1.5.7 vendored by clean lzbench
commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`. The shared checkout was not modified.

The copied closure contains the public headers, BSD/GPL license texts, and the selected
`common`, `compress`, and `decompress` source/header files required by the single-thread
frame build. The closure omits `zstdmt_compress.c`, the x86 assembly translation unit,
dictionary builder, deprecated API, legacy decoders, programs, examples, and tests. The
registered compiler flags additionally set `DYNAMIC_BMI2=0`, `ZSTD_LEGACY_SUPPORT=0`,
and `ZSTD_DISABLE_ASM`. The relative-file closure digest is
`70ce1616c3aee76722bb3a5379a6efe425b183af0197f4d5afe9b7c2e8ae8ed3`;
the resulting SourceArtifactID is
`v2:source-artifact:sha256:893e7c7c0ef2d09d06a92e4ee6191f7f4b090718da5e88e82f23b12a8f82f237`.

The local upstream reference checkout at
`d9c0c7e2cf8a8bf9fb98d3bee546dcf8dc9ac59a` differs from the benchmark-vendored files,
so no files are mixed across the two authorities. lzbench itself calls `ZSTD_compress2`;
the project adapter uses the same vendored library through `ZSTD_compressStream2` because
the plan explicitly requires observable update/finalize behavior. The vendored Zstd
fuzzer passed 100 deterministic cases with seed 20260917 in an out-of-tree copy. Release
and ASan/UBSan ABI smoke tests passed zero, tiny, 128-KiB boundary, multi-block, independent
decode, and repeated-Finalize cases. LeakSanitizer remains unavailable under the host
ptrace policy and is not reported as covered.

## Phase 4 Snappy raw source onboarding

The third native codec was onboarded from the clean lzbench checkout at commit
`fa871e66b3543a70fd4d060f7c12719343ff4ac3`. lzbench calls `snappy::RawCompress` and
`snappy::RawUncompress` and compiles `snappy-sinksource.cc`,
`snappy-stubs-internal.cc`, and `snappy.cc`; that exact translation-unit closure and its
headers, BSD license, and raw-format description were copied unmodified. The closure
digest is `54e6576476ea5c5f654e8257ccbd247c7c7f4212d58fbae1cd44cc3d744f1128`
and the SourceArtifactID is
`v2:source-artifact:sha256:e63a21a66a2ebd8fec7b8caa2b477a157b01033ea458fa3be9eab481bb26771d`.

The Google Snappy checkout at `26aa88cbb235a35d4604d2dd5f5284566862de77`
was used only for comparison; the trees differ and no source was mixed. The lzbench tree
identifies itself as version 1.2.2 in CMake/NEWS, while the checked-in generated public
stub still reports 1.2.1. This inconsistency is retained and disclosed instead of editing
vendor files. Release and ASan/UBSan ABI smoke passed the zero, tiny, 64-KiB-boundary,
independent-decode, output-bound, and repeated-Finalize cases. The benchmark-vendored
compression fuzzer harness passed 100 fixed-seed inputs. LeakSanitizer was disabled due
to the host ptrace restriction.

The final canonical Release artifact SHA-256 is
`6908c7e336c1ac5f97591dee8380e878388959d442850cd220ee0a2d72fa93d7`; the ASan/UBSan
artifact is `865ca9052e150235a364565b86e258455da2063f9208b494d4b4ddfef3ee5da5`.
The current binary completed qualification RunSet
`runset-20260917T125917Z-a89763b0308a`, followed by 30/30 eligible FORMAL repetitions in
`runset-20260917T125955Z-fd44e35213d5` and report
`v2:report:sha256:ba6edff0215d348f08542bffbdf97cf63a5c9ad4c35e05ac40765ce8b1d57bfb`.

## Phase 4 Brotli stream source onboarding

The fourth Batch-1 native codec was onboarded from Brotli 1.2.0 in the clean lzbench
checkout at commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`. The copied closure
contains all common, decoder, encoder, and public include files plus README, changelog,
and MIT license; lzbench's CLI tool is not part of the runtime closure. Vendored files
are byte-identical to their lzbench paths. The relative-file closure digest is
`99c9b5c8815308fa57543c3188ca1bb37b42a411785d10f9ed0ecbe214e4d06a`
and SourceArtifactID is
`v2:source-artifact:sha256:fe9a7e9ee3c50bc85ed92108da5fee194a2440e81f64d60af4d6b2beedae4a66`.

The local Google Brotli checkout at
`4508218e7fef90fa4273286f7a415065946f2c43` is comparison evidence only; its tree is
not mixed into the lzbench closure. lzbench calls the one-shot encoder. To implement the
plan's explicit lifecycle, the adapter uses the same vendored library through one
PROCESS update and FINISH calls until the encoder reports completion. The independent
decoder receives its exact capacity from the versioned TSCB descriptor because an RFC
7932 stream has no uncompressed-length field.

Release and ASan/UBSan ABI smoke passed zero, tiny, 64-KiB-boundary, independent-decode,
native-timing, output-bound, and repeated-Finalize cases. A separate direct public API
harness passed 100 deterministic inputs with seed 20260917 under both builds. The final
Release artifact is `36f6cea7fd8207e23e3a527191f6fdce631d38f9994afbdfd2c9ca8ebe08da35`;
the ASan/UBSan artifact is
`e872be83f1f7c3943ec463aaa3ef6dbb033e1088617b73d18c9faaeb4191b0f6`.
Qualification RunSet `runset-20260918T051810Z-33dd0667685e` and 10/10 eligible FORMAL
repetitions in `runset-20260918T051826Z-a1980b4fbecf` passed. The report is
`v2:report:sha256:dea5f26860e87d25d50151ab2a7dfda27f381be2f4a5c8559391a1b85289b38c`.
LeakSanitizer remains unavailable under the host ptrace policy.

## Phase 4 DEFLATE zlib source onboarding

Spreadsheet Value-Compress row 4 lists DEFLATE. The master plan maps it to madler/zlib;
the analysis confirms zlib/libdeflate availability in lzbench. This integration chooses
zlib 1.3.2 at clean benchmark commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`.
All 48 files of `lz/zlib` were copied byte-identically, retaining the Zlib license.
The actual build uses the 15 zlib translation units from lzbench's Makefile, plus the
project C ABI shim. SourceArtifactID:
`v2:source-artifact:sha256:488e8ce467a7dba0196f8ba1ece20ba03be7167eefa3ab09c79bb914219c5518`.

Closure digest: `90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0`.
Definition: SHA256 over sorted relative POSIX path UTF-8 bytes + NUL + complete file
bytes for each file, concatenated; count and digest are regression-tested. The upstream
checkout `e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca` is clean and identifies as
1.3.2.1. It differs in version/build documentation, gzip write guard and invalid inflate
tree-code handling, among other files. It is comparison-only; no files were mixed.

lzbench's `bench/lz_codecs.cpp` uses compress2/uncompress, meaning RFC1950 zlib and
RFC1951 DEFLATE with Adler32. The project uses the same implementation through explicit
Z_NO_FLUSH and Z_FINISH to expose mandatory Finalize and then a fresh exact-consumption
inflate context. This lifecycle/native timing is not lzbench-equivalent. Defaults,
format, mandatory checksum, limits and excluded variants are recorded in the manifest,
onboarding card and D025.

Both canonical builds passed ABI smoke and 100 deterministic benchmark API cases
(seed 20260918). Release `.so`:
`c4c61655f2513661a8e6766025b45a1790ddc2ed8837b18ce2974a0c3d19aeb7`.
ASan/UBSan `.so`: `c77375acebdc092c8b11de12712f2602f0d6cd0aa951bc2274525850cb1e1494`.
Qualification RunSet `runset-20260918T061832Z-d8ca7a21abd6` passed; FORMAL RunSet
`runset-20260918T061850Z-6e262c4d405a` passed all 49 boundary cases and 10/10 eligible
repetitions. Report ID:
`v2:report:sha256:3a046c2d9c5ecaca505a4f9db5cec1ea298b5443431e5836c997c9a604b5f636`.
Complete layer gates and reproduction commands are in `docs/deflate_zlib_self_check.md`
and `adapters/deflate_zlib/README.md`. Shared source repos remain clean; LeakSanitizer
is disabled under the host ptrace policy, not reported as tested.

The final ELF build binds internal functions using `-Wl,-Bsymbolic-functions` and
passes ABI smoke with a competing globally preloaded deflateInit2_. Without binding,
the same test reproduced a codec-create failure. `ldd` confirms no system libz runtime
dependency. Earlier pre-binding runs are retained but superseded by the final evidence.

## Phase 4 XZ LZMA2 source onboarding

Original spreadsheet Value-Compress!B9 lists LZMA / xz with lzbench as reference.
`xz-stream` copies the 341-file liblzma/common/CMake/tests/license/format closure of
xz 5.8.3 from clean benchmark commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`.
Every copied file was compared byte-for-byte. Closure digest:
`ef43c1771d2d12fdb35b9d53a15394f81da23770f97891d78f1e97e3504d3574`.
Definition: sorted relative POSIX path UTF-8 bytes + NUL + full file bytes.
SourceArtifactID:
`v2:source-artifact:sha256:e51531a640977f677d6fe69f3350582773ef4c090a5e2c194c083b10b6255988`.

Clean upstream `9fc6f5cd8774ebef8d4e030f7081fb6984c0dc3f` also reports 5.8.3
but differs in index/stream-buffer decoder/API/hardware files; it is comparison only.
Identical lzma2_encoder.c does not imply whole-tree equality. The shared catalog
scan covers 72 repository entries (71 available, all clean), 221 logical entries
and 145,830 non-generated files, retained in
`build/source-audits/xz-onboarding-20260918.json`.

Static PIC liblzma disables MT, CLI, specialized CRC dispatch/SIMD matching/copies
and unrelated filters/checks. Complete dependency commands and archive hash are
persisted. Single-call encode completes the stream; mandatory zero-byte Finalize
acknowledges completion. Decoder flags 0 require one exact stream. lzbench's MT
APIs and CONCATENATED | IGNORE_CHECK decoder are not adopted. No data check matches
its encode setting, but structural CRCs/index are fully charged. Native timing is
auxiliary, not lzbench-equivalent.

Both profiles pass ABI smoke, 100 seeded direct vendor API cases and six upstream
library CTests; six disabled-feature CTests SKIP per profile, not counted as PASS.
Logs: `build/adapters/xz_stream/<profile>/native-tests.log`; CLI suites excluded.
LeakSanitizer is disabled under ptrace; ASan/UBSan stay enabled.
Release: `8676b8a44671f5f80a8e8828f55cadb26cb21d9cba6d39a4ae83b6e03e5822c8`.
Sanitizer: `492a6d6947e54ab598203577974c6f72afe6cb22ca2e3a0cee2bf89645e2124a`.
Local ELF binding passes a competing global encoder-symbol test, with no system
liblzma dependency.

Final qualification `runset-20260918T064148Z-cbb750a373ef` has task PASS; formal
`runset-20260918T064155Z-610165c750cb` has 49/49 boundary PASS and 10/10 eligible
repetitions. Report:
`v2:report:sha256:049f6e8ecd3d53b640c8253fa2e6744119b28dbefd7dda900ce03861e804644e`.
Earlier schema-rejected sweeps remain diagnostics, not admission evidence. D026,
the onboarding card and `docs/xz_stream_self_check.md` record gates/limitations.
Formal coverage is default VALUE national_illness, not every preset/dataset.
Shared source repositories remain clean and were never patched.

## Phase 4 LZ77 spreadsheet source mapping audit

Read-only original spreadsheet inspection confirms Value-Compress!B2=LZ77,
C2=madler/zlib, D2=RFC1951; DEFLATE row 4 references the same source and format.
Workbook SHA256: `012cc79f9855f839100fcc3e81449e8dc1dd80d7c175b2b90d1b8d1e07f3be23`.
The analysis maps LZ77 through zlib. Reviewed lzbench's zlib benchmark calls,
deflate.c longest_match/deflate_slow and trees.c _tr_flush_block: actual output is
complete DEFLATE, not a standalone pure LZ77 stream. yalz77/misa77 were not substituted.

The 48-file benchmark zlib 1.3.2 closure remains byte-identical; no copy or patch.
Existing source admission card, build identities and Zlib notices are reused.
Closure digest: `90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0`.
New complete source scan: 72 repository entries, 71 available/clean, 221 logical
entries, 145,830 non-generated files, saved as
`build/source-audits/lz77-onboarding-20260918.json`. Source checkouts remain clean.
Release/ASan/UBSan ABI and 100-case direct API tests were re-run; full log:
`build/source-audits/lz77-native-tests-20260918.log`. These are project harnesses,
not an upstream-suite claim; LeakSanitizer remains disabled under ptrace.

`registry/codecs/aliases/lz77.json` records the explicit logical source mapping,
not a new AlgorithmID. The canonical registry retains ten codecs and 78 source
artifacts; the additional alias is disclosed separately. Run snapshots pin alias
evidence and both-name selection cannot duplicate tasks. Qualification
`runset-20260918T071801Z-e75543ec7c05` passed. Authoritative independent formal
`runset-20260918T071932Z-77ba2d8dc5fd` passed 49/49 VALUE boundary observations and
10/10 eligible repetitions; fifth-layer report:
`v2:report:sha256:90091d86f74c4df417c8e9e8290386de8b2f52c63ab70606f902dc60dcd880c2`.
Complete scope/limitations and layer gates are in D027 and `docs/lz77_self_check.md`.
Pure LZ77 remains unqualified as a standalone codec; these results are the
spreadsheet's zlib DEFLATE implementation only.

## LZSS original source admission (2026-09-18)

Value-Compress row 3 and the master plan identify alexkazik/lzss 0.9.1, clean
commit 512b9163d8a936003c925e24f7f682eeaeda8307. Reviewed generic/dynamic APIs,
compress/decompress, MSB bit IO, safe slice writers, build generator, Criterion
benchmark and original tests. lzbench's LZSSE2/4/8 entries are different formats;
the C/C++ analysis's old independent matching-LZSS claim has been corrected.
Existing unfinished LZSSE2 files were preserved, not used to claim LZSS admission.

New full scan: 72 repositories, 71 available/clean, 221 logical entries, 145,830
non-generated files; build/source-audits/lzss-onboarding-20260918.json. Only the
needed 34-file original library/test/bench/license/reference and void closure was
copied, with no shared-source writes or vendor patches. Closure digest:
82cb61ecc9d31fd48a31624fd2b45f310fcf641d5fcd8e2dcca11d361feced2c.
All original copied files were re-compared byte-for-byte after final measurement.
void 1.0.2 was acquired from static.crates.io; archive SHA256 matches original
Cargo.lock: 6a02e4885ed3bc0f2de90ea6dd45ebcbb66dacffe03547fadbb0eeae2770887d.
Its MIT declaration is retained; missing license text leaves redistribution under
review. Local execution is allowed. Runtime/builds are offline after acquisition.

Original Rust safe/std/alloc EI10/EJ4/C32 source is statically linked behind common
C ABI and Python framework. Release upstream suites (including ignored tests),
doctests, ASan library/in-place tests and two 39-case ABI fixtures pass. Retained
log: build/source-audits/lzss-native-tests-20260918.log. Rust source/FFI are ASan;
C++ ABI is ASan/UBSan; std is not instrumented, LSan disabled. API-only auxiliary
timing was self-corrected before final measurement; old runsets remain retained.

Final qualification runset-20260918T074915Z-9c95a77d4d12 and authoritative formal
runset-20260918T074940Z-f8855e7299f1 complete Layers 1-5. Formal has 49/49 boundary
observations, 10/10 eligible PASS repetitions, nine warmups totaling 527,203,621 ns,
and every selected range >=1 second. FinalBits 258,168 = 32,271 actual bytes,
with no hidden side information. Registry: 11 codecs, 79 sources, one alias.
Machine audit: build/source-audits/lzss-final-audit-20260918.json. ReportID:
v2:report:sha256:fa7d1c5f244fec21f90a767f0e53bda9a071df70f3bc286196a3829745e96954.
See D028 and docs/lzss_raw_self_check.md for exact native timing, fairness keys,
limitations and reproduce commands. Formal coverage is VALUE national_illness only.


## LZSSE8 source admission (2026-09-18)

Renewed full scan: 72 repository entries, 71 available/clean, 221 logical entries,
145,830 non-generated files. Evidence: `build/source-audits/lzsse8-onboarding-20260918.json`.
Source authority is clean lzbench `fa871e66b3543a70fd4d060f7c12719343ff4ac3`;
five original LZSSE8/license/README/platform files, BSD-2-Clause notices preserved
including Brian Marshall's platform notice. Full path+NUL+bytes closure and safety
patch hashes are frozen in `registry/sources/lzsse8-raw-lzbench.artifact.json`.

The malloc-before-null-check defect and unaligned scalar integer accesses are fixed
only in generated build copies. Guard/canary tests pass 180 exact-buffer cases and
2048 hostile streams per release/sanitizer profile. An additional 44 cases compare
encode bytes and decode against unmodified original source. Forced first/second
allocation failures and null free pass both profiles. There is no dedicated local
upstream LZSSE test suite; these evidence names deliberately distinguish project
qualification from direct original-source compatibility checks. LSan is disabled;
ASan/UBSan instrument the actual codec and shim without suppressing alignment checks.

Source/card/build records, `tools/qualify_lzsse8.py`, all needed tests and configs
are in the canonical project, not only the Codex worktree. This explicit user
variant exception does not expand the original 221-entry spreadsheet source catalog.


Final LZSSE8 evidence: 360 regression PASS, Ruff PASS, 49/49 preflight gates,
10/10 eligible formal repetitions. Authoritative run `runset-20260918T083617Z-3f7abca84f5d`;
qualified report `v2:report:sha256:cea882cea1a0ad956a543d8f5062d62ea9ba38d3baee77661356cf720f655414`. Accounting: 260176
bits/32522 bytes including charged descriptors/raw flag.
Self-check: `docs/lzsse8_raw_self_check.md`; machine audit:
`build/source-audits/lzsse8-final-audit-20260918.json`. Earlier raw runs are retained.
