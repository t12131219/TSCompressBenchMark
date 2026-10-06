# Histogram-ST / FloatHistogram-ST standalone C++17 port

Both complete Prometheus joint histogram codecs at commit
`8374d30cb3fe705773bbac72d7015eba17480557` are translated into native C++.
The release conclusion is recorded in `PORT_MANIFEST.yaml`; tests alone do not
promote a pending gate. There is no Go/Python dependency in the library or CLI.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 3
ctest --test-dir build --output-on-failure
build/histogram_st_cli encode int < validation/source-oracle/int.two/input.txt
build/histogram_st_cli decode int < validation/source-oracle/int.two/chunks.hex
```

The CLI is an oracle-compatible textual driver; each output hex line is one
raw source chunk. `include/histogram_st.hpp` is the independent public API.
`Chunk::append` returns whether the current chunk replaces an old chunk or
recodes it. Save the old bytes before append when retaining multiple chunks.
`append_only` rejects changes requiring replacement or recode. Capacity is
16383 samples; start another chunk when that limit is reached.

`Sample` carries paired signed ST/timestamp, schema, spans and binary64 bit
patterns. Integer count/zero fields are uint64 and buckets are signed adjacent
deltas represented as uint64 bit patterns. Floating count/zero/buckets are
binary64 bits. Sum/threshold/custom bounds always use binary64 bits. Hint values
are the source reset hints: 0 unknown, 1 reset, 2 not-reset, 3 gauge. Normal
NaN/Inf payloads and the distinct stale marker follow source semantics.
The port accepts source-known schemas -9..52 and -53; retrieval of schema>8
uses the source reduction to schema8.

`finalize` and `bytes()` expose exact raw upstream `Chunk.Bytes()` for
CROSS_DECODE; raw import requires a `Kind`, as does upstream `FromData`.
`serialize_frame` adds a concrete type/length envelope so a decoder can recover
the kind without external state. `reset_frame` reads that envelope. The envelope
is an extension, not a Prometheus raw chunk. See `frame_contract.md`.
`payload_bits = raw_bytes*8`; `final_bits = (raw_bytes+9)*8`; the 9-byte envelope
is counted for every chunk. Padding, ST, layout and reset metadata are already
included in raw bytes. There is no hidden model, dictionary or checksum.
`append_bound` bounds raw chunk storage; add 9 bytes when reserving a frame.

Append/import copy data and preserve caller input; errors preserve the chunk.
`Cursor` borrows immutable bytes until reset/destruction. Keep the buffer alive
and do not append to a chunk while a cursor borrows its `bytes()` buffer.
`next`/`seek` traverse forward. Integer-to-float retrieval exposes both source
arithmetic modes through `reusable_float_output`: false uses signed integer
accumulation then conversion; true adds converted binary64 deltas sequentially.
The modes can differ above 2^53 and are both tested. Constructors/copies may
throw `std::bad_alloc`; status-returning operations catch resource failures.
Moved-from handles support destruction, assignment and checked reset; do not
call `bytes()` on a moved-from chunk. Separate handles support concurrent use;
one shared handle requires caller synchronization. The implementation has no
internal threading, SIMD/GPU variant or mutable global codec state.

Resource limits are 100000 spans/custom bounds/buckets per side and 16383
samples. Safe overread is zero. Decoder errors detect malformed structure and
truncation; the upstream format has no integrity checksum, so a changed valid
stream can decode successfully. Byte alignment is unrestricted for streams.

`validation/` retains source vectors, full measured-data-derived workloads,
cross-decode/property tests, guard pages, sanitizer logs, portability, timing
and reproducibility evidence. The CSVs supply scalar OT observations aggregated
into fixed histogram windows; the codec is lossless for those histograms,
not an invertible compressor of the original scalar CSV observations.
ARM64 checks use QEMU, not native ARM hardware performance.

Python qualification scripts are offline reference/evidence tools. Their Go
oracle/toolchain paths are the recorded local reference environment; ordinary
C++ build/CTest uses only files in this package. `tools/finalize_release.py`
validates retained evidence and makes the local release archive. Read
`LICENSES/`, `NOTICE` and `SBOM.json` before redistribution. GNU runtime
dependencies are external dynamic dependencies; ARM test runtimes are separate
verification components. No benchmark adapter or registry integration is included.
