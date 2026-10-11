# Requested lossless rewrites

This adapter registers six entry points from five frozen C++17 package APIs.
`FROZEN_APIS.json` hashes the snapshots; `UPSTREAM_PROVENANCE.json`
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

## Build and qualify

Benchmark requires Python 3.14+, NumPy and the project dependencies. Build one
identity, or repeat the build command for the keys above:

```bash
python tools/build_codec.py chimp --profile all --output-root build/lossless-review-new/native
PYTHONPATH=src python tools/verify_general_native_builds.py \
  --build-root build/lossless-review-new/native \
  --report-root build/lossless-review-new/native-qualification \
  --expected-record-count 12
PYTHONPATH=src python tools/onboard_requested_lossless.py \
  --build-root build/lossless-review-new/native \
  --native-qualification build/lossless-review-new/native-qualification/qualification.json \
  --source-qualification build/source-oracles-new/report.json \
  --output-directory build/lossless-review-new/admission
PYTHONPATH=src python tools/qualify_requested_lossless.py --run-suffix local-review-1
```

Repeat the build for all six keys before the 12-profile qualification. Use new
output directories. A current general qualification of the wider existing codec
scope is also accepted when it contains exactly one release and one sanitizer
result for each of these six keys. Independently generate the source report with
`tools/verify_preserved_source_oracles.py --output-root build/source-oracles-new
--completed-build-root BUILD_ROOT`, after its declared Java dependencies and
ABBA/fABBA CLI builds are available.

Admission requires the current native driver, build records, actual declared
compiler/runtime dependencies, nonempty finite ABI tests, source and executable
hashes, successful compile/run commands, and fresh source differential results.
It saves before/candidate cards, compares evidence before and after application,
and rolls back failed application. Existing codec fields, including runtime
profiles, remain registered. Native ABI and source CLI evidence retain their
separate scopes; neither grants all source capabilities, complete G0–G6/N1,
`REWRITE_DONE`, or formal performance acceptance. Old reports are preserved.

`qualify_rewrite_lossless_native.py --output-directory NEW_DIRECTORY` is a
separate source-only ABI probe. It compiles its own executable and does not
qualify the current registered libraries or feed the strict admission tool.

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
boundary. `CORE` uses the registered harness boundary; internal staging, framing
and materialization remain included, and optional native timing is unavailable.

All physical bytes are charged. Descriptor, record headers and wrapper checksums
have exact costs. Complete standalone frames remain opaque; VALUE frames are
charged to `value_bits`.

Objects require one update and one zero-byte finalize. Reset mode 0 starts a new
object; decode uses an independent context. VALUE matrices and homogeneous SOA
columns are supported. No validity bitmap, query, random-access or incremental Benchmark streaming
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

Chimp retains its original license notices. Elf, Elf+, Elf* and
SElf* remain `NOASSERTION` and use the user's recorded local audit/run/rewrite
exception; external publication is not authorized. The new finite native tests cover
Linux x86_64 with the actual compiler/version recorded in each build. ASan/UBSan run with leak detection disabled
under the sandbox; no leak-clean or ARM/Windows/macOS claim is made.
