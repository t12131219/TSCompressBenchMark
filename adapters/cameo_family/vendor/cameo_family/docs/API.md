# Independent API and representation

C++ header: `include/cameo_family.hpp`. `analyze(values, config)` returns masks, the source-style mutated working copy, retained points, sparse-transform stages or TerseTS raw bytes, reconstruction and safety diagnostic. The caller input is immutable. `encode` returns a complete CF01 object; `decode(pointer, byte_count)` uses only that object, with no original signal, previous encoder, refitting or Python state. Calls own all state.

C11 header: `include/cameo_family_c.h`. `cf_config_v1.version=1`; use the `CF_*` algorithm constants. Set all config fields explicitly. Status is CF_OK/CF_CAPACITY/CF_INVALID/CF_NOMEM/CF_INTERNAL. Output/produced/required capacities count bytes for encode and double elements for decode. Query with output NULL/capacity 0. Insufficient capacity or a validated-pointer failure leaves output unchanged and produced 0. Invalid counter pointers, overlap with counters, impossible ranges or out-of-contract capacities reject without writes, including to counters. Counters must be aligned, distinct writable size_t objects disjoint from buffers and config; numeric input/config/output buffers need no extra alignment or padding. Input and output may overlap because processing completes in private storage before committing output.

Algorithm IDs: 1 CAMEO/SIP, 2 VW, 3 PIP, 4 TP, 5 SWAB, 6 Sim-Piece, 7 PMC-Mean, 8 connected SWING, 9 DFT, 10 DWT(DCT-II). CLI accepts lower-case slugs, `sip`, and the exact display string `DWT(DCT-II)`.

Config defaults: error_bound .01, fraction .5, window_fraction .5, nlags 4, hops 2, kappa 1, threads 1. CAMEO flags 1/2 select FGC lookahead / integer ratio stopping (ratio in error_bound, no aggregate CR source path). SWAB flags 4/8 select Cython bottom-up / Python NumPy-lstsq bottom-up; otherwise sliding Cython is used. Flag16 selects the scalar DCT-II/III baseline; default DCT uses FFT. CLI config uses backend=lpc/fgc, criterion=error/cr, mode=sliding/bottom-up/python-bottom-up transform=fft/scalar and the numeric config names. The upstream public Python SWAB class selects its Python bottom-up path; choose that mode explicitly when comparing it. PMC/SWING/SimPiece bounds use the upstream float32 cast. CAMEO bounds refer to ACF error, not pointwise absolute error. Transform fractions retain Python slice semantics, including DWT fraction zero removing every coefficient.

Limits: 131072 values, 64MiB frame, 64 workers. ACF requires at least 8 aggregates, kappa divides N, 0<nlags<aggregate_count/2 and positive hops; planned N²×lags×min(hops,16) <=1e8. SWAB and DCT scalar work N²<=1e8. Empty/one/two-point line objects use an explicit native short-object extension; transforms reject empty input. SimPiece rejects zero bound for N>=2. Inputs/restored values must be finite. The default encoder uses repaired-v1: TP first spans interpolate from the origin to the first turn and normalize importance by that span. analyze reports tp-first-span-v1 when used; ordinary invalid-input failures still return CF_INVALID. Other native safety repairs have diagnostic text in analyze; see UPSTREAM_DEFECTS.md.

CF01 is little-endian: 4-byte magic, seven u64 fields (version=1, algorithm, representation_kind, input_count, restored_count, item_count, payload_bytes), payload, u64 CRC32 (upper 32 bits zero). Fixed overhead is **68 bytes**. Kind 1 stores ordered (u64 index, f64 value) points; kind 2 stores ordered (u64 index, f64 real[, f64 imaginary]) nonzero coefficients; kind 3 stores complete TerseTS raw bytes, including method trailer. Counts, kind/algorithm pairing, ordering, checksum, finite values and limits are checked. FinalBits = complete frame bytes ×8. No pickle or upstream point-count-only bit estimate is used.

CLI default input/output is one JSON object per line. Operations: analyze (default), encode, decode (frame byte array), raw-decode (source_bytes), argsort (diagnostic). encode reports frame/final_bits/reconstructed. File operations: `cameo_cli encode-file request.json output.cf` and `cameo_cli decode-file input.cf values.json`. JSON size/depth and binary size are bounded. Analyze/fitting and decode are separate; no continuous stream, reset/flush, seek, timestamp track or GPU API is advertised.

The installed C11 consumer is tested with:

```sh
cc -std=c11 tests/c_consumer.c -Istage/include -Lstage/lib -lcameo_family \
  -Wl,-rpath-link,stage/lib/linear-algebra '-Wl,-rpath,$ORIGIN/lib' -o stage/consumer
./stage/consumer
```

A static C++17 consumer is separately tested; its link closure includes libcf_pocketfft, OpenMP and the source-built libcf_lapack.a, libm and pthread. Static here describes the C++ core archive; it is not a promise of a fully static libc executable.

Implementation 1.1.0 keeps C ABI v1 and CF01. The appended C++ Config::canonical_dct changes the C++ object layout; rebuild C++ consumers. numeric-info reports the actual numerical backend and long-double mantissa. Linux AArch64 is executed under QEMU for API/interchange qualification; x86_64 is the source-parity platform. See NUMERICAL_DEPENDENCY.md for the exact native scope.
