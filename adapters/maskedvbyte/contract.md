# Bounded MaskedVByte public-source API contract v1

The unmodified Apache-2.0 snapshot and separately recorded unsigned-shift patch
are mandatory inputs. Encoder bytes match the original scalar LEB128 encoder.
The shim owns neither caller buffers nor cross-boundary allocations. All lengths
are uint64; count is limited to 16,777,216. Little-endian Linux x86_64/SSE4.1 is
the currently qualified target. Baseline shim and encoder are separate from the
SSE4.1 decoder translation unit; runtime ISA admission precedes source calls.

Input is exactly one contiguous uint32 vector. External alignment=1 is accepted
through typed staging; input remains immutable. No int64/float conversion,
sorting, dropped values, fallback or hidden backend is permitted. Plain coding
requires starting_point=0; original modular uint32 delta permits every uint32
starting point, duplicates, arbitrary order and wrap. P0 plain and the original
delta+VByte composition require distinct semantic identities at registration.
The delta composition is P2 with explicit A (modular D1), B (LEB128) and D
(checked descriptor/MVB1) stages. A/B execute through the original fused API;
individual stage times are unavailable. Selecting the distinct plain P0 identity
disables A. There is no additional backend C; D is required for self-contained
recovery. An independent stage validator checks emitted residuals, scalar
LEB128, modular inverse, original native recovery and all descriptor/frame bytes.

Native configuration is canonical ASCII JSON with coding=PLAIN/DELTA,
decoder_api=COUNT/COMPRESSED_SIZE, isa=SSE4_1 and uint32 starting_point.
Unknown, duplicate, noncanonical, invalid or irrelevant parameter values fail.
The decoder API is an execution choice and does not change encoded bytes.

MVB1 consists of magic TSCBMVB1 (8 bytes), count u32, seed u32, coding u32
(0 plain / 1 delta), reserved zero u32, payload length u64, original payload and
FNV1a64 trailer. Overhead is 40 bytes: container8, metadata24, checksum8.
Payload has 1–5 bytes per integer, including full-range uint32. Worst-case bound
is 40+5N; native encode accepts exact actual capacity as well. No padding is
serialized or required outside caller extents. Empty payload has a 40-byte frame.

The decoder checks header, count, full physical length, reserved bits, plain
seed, checksum and canonical uint32 LEB128 grammar before any unbounded source
call. It rejects truncated/overlong/nonminimal/overflow codewords and mismatched
count. This scanner validates syntax; actual reconstruction uses one of the four
original APIs selected by frame coding and the configured decoder API. Fresh
decoders use frame seed/coding, including configurations different from encoder.

Output capacity/descriptor/alias and allocation failures leave output bytes,
used length and lifecycle unchanged. Encode stages typed input and exact payload;
decode stages typed output. The shim copies to caller output only after successful
original API length checks. Failed attempted API calls still contribute native
time; failures caught before the source call do not. There is one update followed
by required zero-byte Finalize. Repeat update/finalize fail. Reset0 preserves
parameters/timing enablement and clears state/totals/telemetry; other modes fail.

Native timing wraps only the selected original encode/decode call, using the
shared CLOCK_MONOTONIC contract. Staging, copies, syntax scanning, descriptor,
checksum, framing, FFI and Python gather remain in CORE/PIPELINE. Timer switches
do not alter serialized objects. Counters are cumulative and nondestructive;
unavailable clocks return UNSUPPORTED and Python null, never fabricated zero.
Telemetry reports actual allocation requests and copy sizes for the last
successful operation; these are not RSS or peak-memory measurements.

Python framing must add a checked canonical descriptor with algorithm, stage
sequence, dtype/shape/name/units and wire parameters. It charges every physical
byte, including variable payload, count/seed/coding/length, descriptor and checksums.
The selected decoder API and timer are omitted from wire parameters, so decoder
performance choices do not inflate object size. Caller-owned headers are written
after native success; Finalize precedes accounting; a fresh decoder is required.

Source select/search APIs remain in the frozen translation unit and have separate
source qualification. Benchmark query workloads and streaming are not admitted
by this ABI. C callers must respect opaque handle lifetime; Python rejects calls
after close. Native qualification must test shared binaries plus fault injection
against the same compiled objects, source API routing, guard pages, canaries,
misalignment, corruption, capacities, resets, allocation failures and timer faults.
Source tests alone do not establish this contract or five-layer qualification.
