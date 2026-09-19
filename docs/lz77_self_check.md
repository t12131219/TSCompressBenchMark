# LZ77 spreadsheet mapping five-layer self-check

Date: 2026-09-18  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`  
Selectable name: `lz77` -> canonical native codec `deflate-zlib`

## Admission decision and source review

This is an audited logical-name mapping, NOT a newly admitted pure LZ77 codec.
Original spreadsheet `Value-Compress!B2` names LZ77, C2 points to madler/zlib and
D2 cites RFC1951. DEFLATE row 4 points to the same repository and RFC. Spreadsheet
SHA256: `012cc79f9855f839100fcc3e81449e8dc1dd80d7c175b2b90d1b8d1e07f3be23`.
The workbook was read only, not modified or exported.

The master plan appendix and analysis section 2.1 map LZ77 to zlib. Sections 3.2,
7.2 and 7.3 require identifying the actual executable object before assigning
independent algorithm status. Source review confirms:

- lzbench `bench/lz_codecs.cpp` uses compress2/uncompress for its zlib entry.
- zlib `deflate.c` longest_match/deflate_slow performs dictionary matching;
  `trees.c` _tr_flush_block outputs stored/fixed/dynamic Huffman DEFLATE blocks.
- Neither this source mapping nor RFC1951 specifies a separately serialized pure
  LZ77 token stream. Extracting only the match finder would produce a P0 primitive,
  not the tested P1 self-contained zlib codec. No such primitive is qualified here.
- yalz77/misa77 in lzbench are not silently substituted for the spreadsheet's source.

- [x] Re-scanned all shared source assets: 72 repository entries, 71 available and
  clean, 221 logical entries, 145,830 non-generated files. Evidence:
  `build/source-audits/lz77-onboarding-20260918.json`.
- [x] Reused existing unmodified 48-file zlib 1.3.2 closure from clean lzbench
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`; all files were compared byte-for-byte.
  No duplicate vendor tree or shared-source changes.
- [x] Closure SHA256:
  `90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0`.
  Sorted relative POSIX path UTF-8 bytes + NUL + complete file bytes.
- [x] Source admission/build/license contracts reuse
  `registry/onboarding/deflate-zlib.json`; the new mapping contract is separately
  closed and pinned in `registry/codecs/aliases/lz77.json` and its v2 schema.
- [x] Upstream comparison remains the clean madler/zlib 1.3.2.1 reference from
  DEFLATE admission, never mixed into the benchmark 1.3.2 runtime closure.

## Layer 1 - Data

- [x] national_illness preserves 966 rows, seven heterogeneous channels, dtype/order
  and canonical denominator 432,768 bits. No cast/sorting/filling/preprocessing added.
- [x] TIMESTAMP and VALUE boundary tests both pass through the selectable mapping.
  Final VALUE preflight has 49/49 PASS, including empty/tiny, IEEE payloads, integer
  extremes, timestamp order/duplicates/epochs, physical layouts and tails.

## Layer 2 - Identity, constraints and fairness

- [x] `lz77` resolves to the SAME manifest, AlgorithmID, SourceArtifactID, defaults,
  parameters and comparison contracts as `deflate-zlib`. Alias evidence has a
  separate CodecAliasID, not a second ranked AlgorithmID.
- [x] Actual P1 stream is TSCB descriptors + RFC1950/RFC1951 zlib DEFLATE with
  mandatory Adler32, default level 6/windowBits 15/memLevel 8/default strategy,
  one scalar CPU thread, no external dictionary/fallback.
- [x] Both names in either order create one canonical task/configuration, one codec
  snapshot and ten repetitions, not two algorithms. Canonical registry enumeration
  excludes aliases; CLI list/verify discloses them separately.
- [x] Runs freeze alias evidence in codec_alias_snapshot.json. Resume verifies the
  frozen evidence; schema, identity, collisions, chains, unknown fields and missing
  audit evidence are rejected. Regression tests check changed-evidence resume failure.
- [x] Raw/gzip/dictionary/query/streaming/multithread variants remain unregistered.

## Layer 3 - Lifecycle, safety, correctness and accounting

- [x] Real native zlib source is driven by Python, not Python stdlib compression:
  configured deflateBound -> Z_NO_FLUSH -> Z_FINISH until STREAM_END -> accounting
  -> fresh exact-consumption inflate -> close. Finalize bytes/time remain charged.
- [x] Existing IEEE exactness, independent decode, immutable input, canaries,
  determinism, corruption/truncation/trailing/concat rejection and capacity tests
  apply to the same source and artifact, not an untested copied adapter.
- [x] Physical ledger: 112 container + 6,080 metadata + 32 Adler32 checksum +
  209,920 routed VALUE = 216,144 bits = 27,018 bytes. All DEFLATE/Huffman bytes and
  intrinsic bit padding are charged; capacity is not the encoded size.
- [x] Release and ASan/UBSan ABI smoke, competing global deflate symbol test and
  100 seeded direct compress2/uncompress cases per profile pass. These are project
  harnesses, not a claim that the complete upstream suite was run. Retained log:
  `build/source-audits/lz77-native-tests-20260918.log`.
- [x] Source and binary identities match the existing admission card. Release:
  `c4c61655f2513661a8e6766025b45a1790ddc2ed8837b18ce2974a0c3d19aeb7`.
  ASan/UBSan: `c77375acebdc092c8b11de12712f2602f0d6cd0aa951bc2274525850cb1e1494`.
  LeakSanitizer remains disabled under ptrace; ASan/UBSan remain enabled.

## Layer 4 - Raw measurement audit

- [x] Qualification: `runset-20260918T071801Z-e75543ec7c05`, actual task PASS.
- [x] Final formal: `runset-20260918T071932Z-77ba2d8dc5fd`, ten distinct eligible
  repetitions, correctness/resource evidence from the same repetitions, no failures.
  Executed after this task's regression/native tests ended.
- [x] Warmup: 166 independent objects, 501,854,756 ns; both minima satisfied.
- [x] Selected PIPELINE duration: 1,000,092,239 to 1,002,542,734 ns, every repeat
  >=1 second. Positive native API durations are inside CORE and PIPELINE durations.
- [x] Explicit lifecycle, Python container and accounting stay in pipeline timing.
  Native CLOCK_MONOTONIC API-only timing is auxiliary, not lzbench-equivalent.
  Initial formal `runset-20260918T071809Z-77ba2d8dc5fd` is retained; the later
  independently scheduled run above is authoritative.

## Layer 5 - Report and interpretation

- [x] One canonical dataset summary, ten eligible repetitions, no exclusions.
  SizeRatio about 0.49944543; CompressionFactor about 2.00222074.
- [x] PIPELINE encode/decode about 20.79/149.86 MB/s; auxiliary NATIVE about
  28.26/298.90 MB/s. These include the real DEFLATE pipeline, not isolated LZ77.
- [x] Report ID:
  `v2:report:sha256:90091d86f74c4df417c8e9e8290386de8b2f52c63ab70606f902dc60dcd880c2`.
  Report: `runs/runset-20260918T071932Z-77ba2d8dc5fd/report/report.html`.
- [x] Combined native/Python support hash remains
  `45e9c1ceeb2a2dd6badb84fcc6c802bc01d67b355ff63aca9ead9839366e66ca`.
  CodecAliasID: `v2:codec-alias:sha256:54b3d934dd5bc4964ba4f4f2892d4d2e16096d5aa8168e6636672783a4d65e37`.
- [x] All mapping/config/schema/test/docs/run/report artifacts are in the canonical
  project. Existing DEFLATE, XZ and unrelated in-progress files are preserved.

Formal performance coverage is default VALUE national_illness only. TIMESTAMP
boundary coverage is not a formal speed claim. Pure LZ77 standalone admission is
NOT completed: it requires an explicit independent format/source choice and object
contract, rather than relabeling these DEFLATE measurements.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py deflate-zlib --profile all
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs list
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz77-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz77-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/lz77-formal.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume
```
