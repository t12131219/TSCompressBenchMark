# Requested lossless rewrites

This adapter consumes frozen public APIs from six independently qualified C++17
standalone packages. `FROZEN_APIS.json` hashes the snapshots; `UPSTREAM_PROVENANCE.json`
records each source closure, original commit, qualification report and local license
decision. Canonical packages and their standalone releases remain under
`Compression_Rewrite/`; Benchmark code is outside those packages.

| Registry key | Input | Source behavior |
| --- | --- | --- |
| `chimp` | VALUE, binary32/64 | Chimp |
| `chimp128` | VALUE, binary32/64 | ChimpN, fixed history 128 |
| `elf` | VALUE, binary32/64 | VLDB2023 Elf, per-value beta |
| `elf-plus` | VALUE, binary32/64 | Elf+, beta reuse and implicit XOR bit |
| `elf-star` | VALUE, binary32/64 | Elf*, original block Huffman format |
| `self-star` | VALUE, binary32/64 | SElf*, adaptive state across all blocks of each column |
| `prometheus-xor-chunk` | SYSTEM/S0, signed int64 T + binary64 V | Joint timestamp second differences and value XOR |

`gorilla`, `delta-of-delta` and `second-order-difference` select
`prometheus-xor-chunk`, following the supplied spreadsheet source mapping. These
aliases share its AlgorithmID and add no independent codec or ranking entry.

## Build and qualify

Benchmark requires Python 3.14+, NumPy and the project dependencies. Build one
identity, or repeat the build command for the keys above:

```bash
python tools/build_codec.py chimp --profile all
python tools/qualify_rewrite_lossless_native.py
PYTHONPATH=src python tools/onboard_requested_lossless.py
PYTHONPATH=src python tools/qualify_requested_lossless.py --run-suffix local-review-1
```

The two `configs/experiments/requested-lossless-*-qualification.toml` files exercise
ETTh1, exchange_rate and weather through all five Benchmark layers. They use
`QUALIFICATION`, `PIPELINE`, one warmup and one repetition. Their records remain
ineligible for formal performance rankings. The native qualification executable
checks the C ABI directly under ASan/UBSan, including protected output pages and
short-capacity atomic failure. Sanitized shared libraries are not loaded into Python.

## Contract and accounting

The Python wrapper serializes a canonical JSON descriptor with SHA-256, then the
native adapter writes `RWF1` framing, record counts, complete standalone frames and
FNV64. Fresh decoders check identity, lengths, block geometry and the descriptor.
Input layout copies, descriptors, FFI calls and native framing are included in
`PIPELINE` timing. `E2E` is also supported through the standard Benchmark timing
boundary. Native `CORE` is rejected during planning with `TIMING_SCOPE_UNSUPPORTED`.

All physical bytes are charged. Descriptor, record headers and wrapper checksums
have exact costs. Complete standalone frames remain opaque; VALUE frames are
charged to `value_bits`, and joint Prometheus frames to `unallocated_shared_bits`.
No estimated split between timestamp and value codewords is reported.

Objects require one update and one zero-byte finalize. Reset mode 0 starts a new
object; decode uses an independent context. VALUE matrices and homogeneous SOA
columns are supported. SYSTEM requires paired int64 timestamps and binary64 SOA
values. No validity bitmap, query, random-access or incremental Benchmark streaming
profile is registered. SElf* preserves its original internal multi-block state.

Source-domain restrictions remain visible: Chimp canonical NaN is its END marker,
and Elf variants reject source NaN END, nonterminating significance searches and
nonlossless decimal recovery. Only exact declared encoder error reasons with
unchanged input and output can pass a boundary rejection check. Real datasets
outside this domain produce `UNSUPPORTED / SOURCE_DOMAIN_UNSUPPORTED`; no raw
fallback is present. Capacity limits, including SElf*'s 1024 blocks per column and
the wrapper's 16,777,216 value elements, are checked during planning and execution.

Elf* has a binary32 source block limit of 1000, so the shared registered block size
is at most 1000. Other block limits are declared in each registry manifest. Full
standalone contracts describe the larger binary64/source API domains separately.

## Evidence and local use

See `docs/requested_lossless_rewrite_review.md`, its JSON companion, the Benchmark
qualification JSON and the native ABI/release consumption reports. Re-freezing
changes source identities and requires refreshed build, onboarding and run evidence.

Chimp and Prometheus retain their original license notices. Elf, Elf+, Elf* and
SElf* remain `NOASSERTION` and use the user's recorded local audit/run/rewrite
exception; external publication is not authorized. Current qualification covers
Linux x86_64 with GCC 11 and Clang 14. ASan/UBSan passed with leak detection disabled
under the sandbox; no leak-clean or ARM/Windows/macOS claim is made.
