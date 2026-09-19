# Michael Dipperstein C LZSS five-layer self-check

Date: 2026-09-19  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`  
Algorithm: `lzss-dipperstein-c`

## Admission boundary

This is an explicitly requested independent native C variant from
MichaelDipperstein/lzss commit `65b6882ff1cc225f9c6fcd947def7b1adb21d578`, with
bitfile commit `2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0`. It does not replace the
spreadsheet-selected alexkazik Rust `lzss-raw`, does not inherit its results, and is
not ranked as the same implementation. GRUB remains decode-only reference material:
its grouped flag-byte stream is not this token-flag bitstream.

- [x] Twelve required upstream API/implementation/license files are retained byte
  identical. Closure SHA256 (relative path + NUL + bytes):
  `ce81296d3b2269d8ee2adf2d6964f156b31d013a6742e2c7c21486785d91fb9a`.
- [x] LGPL-3.0-or-later notices are retained; local execution is `RUN_ALLOWED` and
  redistribution remains subject to that license.
- [x] Fixed identity: 12-bit offset, 4-bit adjusted length, minimum match 3,
  4096-byte space-filled window, binary-tree matcher, scalar, one thread.
- [x] Bit I/O is MSB-first, while numeric offset serialization on the qualified
  little-endian host is low byte then high nibble. The independent decoder tests this
  exact 8+4+4 representation rather than assuming a big-endian 16-bit token.

## Source safety correction

ASan/UBSan found real out-of-bounds sentinel accesses in upstream `tree.c`: deleting
the last root indexed `NULL_INDEX`, and reinsertion then read it as `treeRoot`.
`0001-binary-tree-sentinel-bounds.patch` is applied only to an out-of-tree build copy;
vendored source stays unchanged. The patch guards null children, handles root removal,
and initializes an empty tree insertion. Patched and unmodified release builds produced
identical bytes for 48 retained cases.

The upstream empty-input compressor creates a bitfile object and returns before its
normal cleanup. The ABI maps zero bytes to the canonical empty stream without entering
that code. Empty decode is handled symmetrically because zero-length `fmemopen`
behavior differed in sanitizer. Nonempty inputs use original `EncodeLZSS`/
`DecodeLZSS`; FILE streams are always closed independently.

Release and fully instrumented C codec/bitfile/tree/ABI builds pass 48 boundary
roundtrips, canaries, `bound-1`, reset/finalize and hostile stream rejection. Log:
`build/source-audits/lzss-dipperstein-native-tests-20260919.log`, SHA256
`c50e10cf9ede3151bec789ea824b4a5c26102366e3411e752ff0c56e36710686`.

## Layer 1 - Data preparation

- [x] Existing deterministic dataset manifests/loaders are reused without casting,
  sorting, filling or hidden preprocessing.
- [x] Formal VALUE input is `national_illness`: 966 rows, all seven channels and
  432,768 canonical raw bits. Timestamp bytes are not encoded in VALUE.
- [x] Dataset, canonical-content and actual routed-input hashes are frozen in every
  task and RunRecord.

## Layer 2 - Identity, capability and fairness

- [x] Separate AlgorithmID, SourceArtifactID, AdapterID, unique container magic and
  parameter schema are registered. SourceArtifactID:
  `v2:source-artifact:sha256:4c20671bce63b0af5096ff01677e538f12c25d15d74075b8790e8c758ac256a9`.
- [x] `lzss-raw` and all prior Rust RunSets remain untouched. Registry and planning
  tests require distinct algorithm/source identities and comparison keys.
- [x] Python owns negotiation, Track routing, standard enforcement, validation,
  accounting and reporting. Rust and C variants share only implementation-neutral
  descriptor/session machinery, preparing a later C-only migration without aliasing.
- [x] Static upstream work buffers make the codec single-thread only. Continuous
  streaming, random access, query, alternate matcher/widths and validity are rejected.

## Layer 3 - Execution, correctness and accounting

- [x] Per repetition: new handle, exact bound, compress, mandatory zero-byte Finalize,
  physical-stream accounting, strict grammar precheck, independent native decode,
  common bit-exact validation and teardown.
- [x] Independent Python 12/4 decoder, golden vector, IEEE special values, window/tail
  boundaries, deterministic re-encode, input immutability and canaries pass.
- [x] Strict native/Python inspection rejects truncated tokens, surplus/concatenated
  bytes, decoded-length overshoot and nonzero tail padding before upstream EOF-tolerant
  decode can accept them.
- [x] Bound is `n + ceil(n/8)`. FinalBits charge the 12-byte prefix, canonical
  descriptors, token bits and 0..7 physical padding bits. Dictionary/model/index/
  checksum/external side information are zero.

Qualification RunSet `runset-20260919T124711Z-8182c1271aa8` is PASS and intentionally
has zero eligible performance runs. Qualification report:
`v2:report:sha256:d7abf367fd0ee03ca83a805120c8ef9678867799623df1ca14f4ba7d6e498efb`.

## Layers 4 and 5 - Formal evidence

- [x] Authoritative RunSet: `runset-20260919T124809Z-5baf782c45ac`.
- [x] 49/49 boundary observations and 10/10 complete eligible PASS repetitions.
- [x] Same-repetition correctness, accounting, process resources, PIPELINE and
  auxiliary original-API timing are retained. Finalize emits zero bytes.
- [x] One summary: 257,448 FinalBits / 32,181 bytes, SizeRatio
  0.5948868678, CompressionFactor 1.6809918896. Median selected PIPELINE throughput is
  about 0.545 MB/s encode and 2.002 MB/s decode on this host.
- [x] ReportID:
  `v2:report:sha256:30be9fd11232753991d15c9c17e4c06203254a62e375288f1beaacdf878ca922`.

Earlier RunSets from before the shared module was moved out of `lzss_raw.py` remain
append-only but are superseded; their supporting-component hash does not identify the
final C-only-friendly structure.

These values describe one included VALUE task, not a universal LZSS performance claim.
They must not be merged with Rust `lzss-raw` rankings.

Final build hashes are
`64639cd65686096f31d46137ae2b70f8ab028e3f673152866e4e53e92f24d8e5`
(release) and
`288d655eac391629bda6c46f65e72684226efd1079e4f79c989d0cabb26c7491`
(sanitizer). Full regression: 695 PASS; Ruff: PASS; registry verification: 21 codecs,
86 source artifacts. Machine summary:
`build/source-audits/lzss-dipperstein-final-audit-20260919.json`.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py lzss-dipperstein-c --profile all
conda run -n CompressBench14 python tools/qualify_lzss_dipperstein.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzss-dipperstein-c-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzss-dipperstein-c-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/lzss-dipperstein-c-formal.toml --output-root runs \
  --run-set-id runset-20260919T124809Z-5baf782c45ac --resume
```
