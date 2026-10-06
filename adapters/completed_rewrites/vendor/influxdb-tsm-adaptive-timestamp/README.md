# Historical InfluxDB TSM Adaptive Timestamp — standalone C++17

This package translates the complete timestamp pipeline from InfluxDB Go
v1.12.4, commit `f9befe3459b689dc6dd1dd11e1e58e2943434ab1`. The release status
and capability closure are in `PORT_MANIFEST.yaml`. Delta, decimal scaling,
RLE, Simple8b, raw fallback and the adaptive selector remain one algorithm.
There is no Go/Python/TSDataCompressBenchMark runtime dependency in the library.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 3
ctest --test-dir build --output-on-failure
build/tsm_timestamp_cli encode stream < validation/source-oracle/two/input.txt
build/tsm_timestamp_cli decode batch < validation/source-oracle/two/stream.hex
```

`include/tsm_timestamp.hpp` exposes both original encoding profiles:
`Profile::Stream` models the old buffered Jason Wilder Simple8b encoder;
`Profile::Batch` models the InfluxDB fork's prefix-run packing. They can emit
different exact bytes and both are tested against their original source API.
The type nibble in output selects raw0/packed1/RLE2; `Cursor::encoding()` reports
the actual decoder path. Neither profile silently falls back to the other.
One-shot `encode` and the accumulating `Encoder` produce the selected profile.
There is no separate native SIMD/GPU or internal parallel path.

Inputs are contiguous aligned int64 timestamps, including duplicates, negative
values and reverse/wrap cases supported by source modulo arithmetic. No sorting
or implicit timestamp unit conversion occurs. Input is never modified.
`encode_bound` returns the exact serialized size; `encode_to` returns the needed
size through `written`, rejects capacity-1 without changing output and supports
empty input with zero bytes. `decode` owns its result; `Cursor` borrows immutable
input through the last traversal/reset. Byte streams need no alignment or
padding; safe overread is0. Caller synchronization is required for a shared
handle, while separate handles have no shared mutable state.

`Encoder::finish` caches bytes. Repeated `finish`/`finalize` is stable, and append
after terminal finalize fails until reset. An insufficient-capacity finalize
does not close an unfinished encoder. Source Bytes/TimeArrayEncodeAll overwrite
their internal/input scratch; the native safe ownership and terminal lifecycle
are explicitly defined in `contract.md`. This preserves fresh source encode and
decode bytes without repeating the source's destructive Bytes mutation.

`Cursor::reset` starts a clean independent decoder. `Cursor::source_init`
preserves a legacy source quirk: Init(empty) following RLE retains its old count
and delta and emits ghost values. It exists for exact observable compatibility;
ordinary new decode calls and clean reset of empty streams return no samples.
The quirk is qualified against an unmodified source oracle. Source decoder
panics and oversized allocations become explicit errors. The decoder accepts
scaling exponents0..15; encoding emits0..12. The default/hard native sample cap
is16777216; callers may lower it. Larger requested limits are clamped to that
hard cap. C++ constructors/copies can throw allocation exceptions; noexcept
status-returning codec operations report ResourceLimit.

`FinalBits = byte_length*8`, including type/scaling byte, first timestamp,
varints, packed/raw words and unused selector bits. Empty input has0 bits.
No external model, dictionary, timestamp seed, kind or checksum is needed.
Each buffer is one complete source byte slice. The format has no checksum;
some prefixes/mutations remain valid streams representing fewer/different
timestamps. Tests check structural rejection and zero overread without claiming
that every prefix can be detected as truncation.

The frozen real workloads retain complete date columns from three CSV files,
parsed to exact UTC nanoseconds using integer arithmetic in source row order.
They encode timestamps only. Their regular spacing mostly exercises RLE;
synthetic and seeded properties cover the other two adaptive branches and all
sixteen Simple8b selectors. Performance observations retain full timing
distributions, caller/transport copies, process scope and peak RSS. ARM64 tests
run under QEMU and do not establish native ARM hardware performance.

Go files and Python scripts are reference/qualification tools only. The source
oracle's minimal module preserves original timestamp/primitive/test files and
projects exact upstream support helpers; its provenance is retained under
`validation/source-identity`. Native CMake/CTest is fully standalone. Read
`LICENSES`, `NOTICE`, `SBOM.json`, dataset and capability reports before
redistribution. No benchmark adapter, registry or experiment integration is made.
