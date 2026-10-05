# Native Streaming Profiles Self-Check

Scope: LZ4 Frame, Zstandard Frame, Brotli, bzip2 and xz/LZMA2 native streaming profiles.

- [x] Each adapter uses a persistent upstream encoder context across routed blocks and a
  fresh upstream decoder context for the matching stream.
- [x] `stream_start -> stream_push* -> stream_finalize -> stream_decompress -> accounting -> close`
  is enforced by the shared Python lifecycle and the C ABI stream symbols.
- [x] Block-major buffer ordering, canonical descriptor metadata, exact reconstruction,
  caller-paced output bounds, state telemetry, and zero checkpoint/buffer accounting are shared.
- [x] Empty, tiny, block-boundary, heterogeneous-buffer, truncated and trailing stream cases
  are covered by `tests/adapters/test_native_streaming_codecs.py`.
- [x] All five qualification and all five formal runs passed under `CompressBench14`.

The profiles remain CPU scalar, single-thread, no external dictionary, and make no SIMD/MT
claim. Streaming is a separate comparison key from one-shot execution and introduces no new
AlgorithmID.

Qualification RunSets: `runset-20260923T092959Z-e6b8df277967`,
`runset-20260923T093015Z-3263575c6551`, `runset-20260923T093016Z-17b3bde08db7`,
`runset-20260923T093017Z-c584fbe446df`, `runset-20260923T093018Z-397f1c64cae1`.

Formal RunSets: `runset-20260923T093034Z-895a2745cdde`,
`runset-20260923T093047Z-66c295cc08fe`, `runset-20260923T093059Z-2af569689787`,
`runset-20260923T093111Z-b405d85a33f8`, `runset-20260923T093123Z-a79ebede6fa0`.
