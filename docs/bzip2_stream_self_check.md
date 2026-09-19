# bzip2 1.0.8 five-layer integration self-check

Date: 2026-09-19  
Scope: spreadsheet-listed `BZ2 (Huffman Coding)`, implemented as complete bzip2 1.0.8  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and identity

- [x] Re-read the master plan, C/C++ analysis and edge-case requirements. The
  spreadsheet maps Huffman to bzip2 1.0.8, but the executable object is the complete
  BWT, MTF/RLE and Huffman pipeline. It is P1, not a P0 Huffman primitive.
- [x] Used clean lzbench commit
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`, matching its seven libbz2
  translation units and `BZ2_bzBuffToBuffCompress/Decompress` benchmark mapping.
- [x] Copied only the seven C files, two headers, LICENSE, README and CHANGES.
  All 12 vendor files remain byte-identical. Closure SHA-256:
  `eda9be9e525b9ea675c7574c46d7fa92c4a07fe493d7f6d34714614c8a650cc4`.
- [x] Preserved the bzip2 license and registered a distinct SourceArtifactID and
  AlgorithmID. No source or result is merged with `huff0`, DEFLATE or XZ.

## Layer 1 - Data

- [x] Routed buffers preserve dtype, shape, order, logical bits and exact IEEE bytes.
  No sort, cast, fill, transform or hidden preprocessing is introduced.
- [x] The formal `national_illness` VALUE input contains 966 rows and seven channels;
  canonical denominator is 432,768 bits.
- [x] The standard 49-case gate covers empty/tiny arrays, integer edges, IEEE special
  values, layouts, channel shapes and tails; all observations pass.

## Layer 2 - Contract and fairness

- [x] `bzip2-stream` is lossless T1/V0, scalar CPU, single-thread and no fallback.
  Level 1-9 is registered; default level 9 means 900,000-byte internal blocks.
- [x] Verbosity 0, API workFactor 0 (effective libbz2 value 30), normal-memory decode,
  one independent stream and no concatenation are fixed execution facts.
- [x] `block_size` is a framework boundary parameter and is not represented as the
  bzip2 internal `blockSize100k` setting. Compression level remains in ConfigID.
- [x] Small-memory decode, custom work factors, concatenated streams, query, random
  access and continuous streaming are not advertised or silently substituted.
- [x] Planning tests prove bzip2 has separate semantic, execution, resource and
  execution-path identities from all previously registered codecs.

## Layer 3 - Native lifecycle, safety and accounting

- [x] Python drives vendored C through C ABI v1. `BZ_RUN` consumes one routed object;
  `BZ_FINISH` loops to `BZ_STREAM_END`. Empty input skips invalid zero-progress
  `BZ_RUN` and is encoded by finish. Repeated update/finalize is rejected.
- [x] Output bound is `n + floor(n/100) + 600`, with explicit UINT_MAX checks. Actual
  total-out deltas, never capacity, determine FinalBits.
- [x] Fresh decoder loops until `BZ_STREAM_END`, consumes every encoded byte and emits
  exactly the descriptor length. A one-byte sentinel detects any extra decoded output.
  Truncation, trailing garbage, concatenation, header-level mismatch and CRC damage fail.
- [x] Exact output canaries, source immutability, reset/reuse and actual-size-minus-one
  failure are checked at empty, 1/2-byte and level-1/level-9 block boundaries.
- [x] Release and ASan/UBSan each pass the ABI suite and 36 seeded direct libbz2 API
  cases across levels 1-9. A deliberately failing global `BZ2_bzCompressInit` cannot
  interpose the locally bound implementation.
- [x] Python's independent `bz2.decompress` validates level 1/5/9 payloads and exact
  multi-buffer IEEE bytes. The stdlib is an oracle only, never the measured codec.
- [x] Accounting is deliberately conservative and non-overlapping: 96 prefix bits,
  6,080 descriptor metadata bits and 208,408 complete bzip2 stream bits equal
  214,584 FinalBits / 26,823 physical bytes. Internal headers, CRCs and padding are
  included in the stream bucket, not guessed as pure Huffman bits.

## Layer 4 - Measurement

- [x] Qualification RunSet: `runset-20260919T134516Z-abb3ac901fbd`, PASS and
  intentionally excluded from formal ranking.
- [x] Authoritative formal RunSet: `runset-20260919T134654Z-1ee065100f52`.
  It has 49/49 preflight PASS observations, 99 independent warmups over 501,900,965 ns,
  and 10/10 eligible formal repetitions.
- [x] Each selected PIPELINE repetition exceeds one second through independent-object
  inner iterations. Correctness, accounting and timing derive from the same repetition.
- [x] Native timing wraps only libbz2 encode/decode calls. Context lifecycle, explicit
  validation and Python container work remain outside native timing but inside the
  appropriate CORE/PIPELINE observations.
- [x] Earlier formal RunSet `runset-20260919T134534Z-1ee065100f52` is retained: two
  repetitions observed host swap activity and are `RESOURCE_PRESSURE`; its zero-summary
  report is diagnostic and is not rewritten into admission evidence.

## Layer 5 - Statistics and scope

- [x] Final report has one summary and 10 eligible raw repetitions, with no exclusions.
  ReportID: `v2:report:sha256:3774b510cc5a9e80627c801d5eabbdfed0845811cc821f482ba16d1828507e4c`.
- [x] SizeRatio is 0.49584072759538598 and CompressionFactor is 2.0167766469075048.
  PIPELINE encode/decode are about 15.28/37.04 MB/s; native API encode/decode are
  about 19.04/42.90 MB/s. Native values are not described as lzbench-equivalent.
- [x] Report: `runs/runset-20260919T134654Z-1ee065100f52/report/report.html`.
  Raw evidence, summaries, coverage, comparison keys and report inputs are append-only.
- [x] Formal evidence covers only the default level-9 VALUE task on
  `national_illness`; it is not a performance claim for all datasets or levels.

## Build identities

- Release: `fbbd165f6c6daf626fa8d30c8d6a5fb7f08f6aa6d9fdc26465af080c5ab48519`.
- ASan/UBSan: `e7bf137e9b410d664830482833f0e8d262192686cff1462b0c3470c27aad65f7`.
- Frozen formal support artifact: `2846865fd44bf65f78d765aaa33f7b9c096ccf2ac784908af560c92ce23e82cc`.
- Full suite: 714 PASS; Ruff: PASS; registry: 22 codecs, one alias, 87 source artifacts.

LeakSanitizer remains disabled under the host ptrace policy. GCC's upstream
coroutine-style fallthrough warning and intentionally unused diagnostic/allocator
values are disabled by three named flags so vendor bytes remain unchanged; all other
warnings remain errors.

## Reproduce

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py bzip2-stream --profile all
conda run -n CompressBench14 python adapters/bzip2_stream/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/bzip2-stream-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/bzip2-stream-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/bzip2-stream-formal.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume
```
