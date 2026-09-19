# Huff0 / FSE source admission and five-layer check

Spreadsheet `Value-Compress` rows 85 and 61 and `参考TSBench` row 23 identify
`Cyan4973/FiniteStateEntropy`. The TSBench directory is a symlink to the clean
local checkout at commit `9f30e0918f87bd835fa040d922a208d7b219e50b`.
`programs/fullbench.c` calls `HUF_compress` / `HUF_decompress` and
`FSE_compress` / `FSE_decompress`. The unmodified library closure and BSD license
are in `adapters/entropy_fse/vendor/`; the project wrapper is separate. The
closure digest is in `registry/sources/entropy-fse-benchmark.artifact.json`.

1. Data: the registered Value track uses canonical dtype and full logical
   buffers. No timestamp or validity bytes enter the codec. Each buffer's
   dtype, shape, name and bit count are in the charged descriptor.
2. Capability: both are P1, conventional, lossless, CPU scalar, single thread.
   The 128 KiB *total encoded object* ceiling is checked by the C ABI; no
   segmentation is performed. `block_size` is a benchmark boundary parameter,
   not an invisible native chunking control. Out-of-range tasks fail preflight.
3. Execution: each repetition creates an independent session. A single native
   update produces the complete block, followed by mandatory zero-byte
   Finalize. The mode byte distinguishes compressed, raw and (FSE) RLE output.
   FSE's return value 0 is never passed to `FSE_decompress`; vendor errors are
   not treated as incompressibility. Reconstructed buffers are checked by the
   common lossless validator. The native qualification harness ran 39 cases
   per variant under both ASan and UBSan.
4. Measurement: CORE/PIPELINE/E2E and resources are collected by the existing
   repetition executor; native API timing is auxiliary. Raw fallback has no
   vendor call to time. The same repetition supplies correctness and timing.
5. Reporting: the mode/length header (9 bytes), container prefix (12 bytes),
   JSON descriptor and payload are all charged, and `FinalBits == 8 * physical
   stream length`. Qualification yielded two PASS records; the formal runset
   `runset-20260919T071949Z-dccb8e46941f` yielded 20 PASS repetitions,
   20 eligible rows and two summary records.

The upstream `make check` passed from an isolated copy (FSE and Huff0 CLI
roundtrips with bytewise `diff`); `test-all`/fuzzers were not run. The
`fullbench.c` timing loop is not imported; it does not satisfy the project's
raw repetition or comparability contract. Large datasets and validity
buffers need explicit future chunking and a separate, fully charged stream
format. The fixed manifest `max_n` alone does not express the total byte
bound for arbitrary channel counts, so the native length gate remains binding.
