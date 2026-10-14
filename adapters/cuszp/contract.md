# cuSZp 1D FIXED CUDA adapter

This is a new GPU member, separate from the retained 36 CPU codec keys. It exports
only genuine official cuSZp 3.0.0 1D FIXED f32/f64 kernels from commit
`f581dcf329c907c320f4743a9c6e7ee2fb9c5494`. The two upstream kernel translation
units and their headers are unmodified and frozen in `SOURCE_LOCK.json`; BSD
3-Clause notices are retained. The checked host wrapper replaces the unchecked
upstream entry functions, not the compression algorithm. There is no CPU fallback.

The public GPU ABI uses opaque owners. The existing CPU host-buffer ABI never
receives device pointers. `Session` owns its independent stream; prepared inputs,
encoded device payloads and decoded device arrays each own their allocation. A
session close does not free an output transferred to its owner. Every operation
checks allocation, memset, transfer, launch, event completion, synchronization and
explicit release. Failure cleanup is best effort; it does not prove failed-context
recovery or permit automatic device reset. The executor must stop the device
session if recovery cannot be confirmed.

Native owners retain their input/payload/decoded kind, and encoder/decoder reject
an owner of the wrong kind or typed configuration before launching a kernel.
Diagnostics record calling-thread checked allocation/release bytes and
stream/event creation/release counts. Balanced counters prove release of these
adapter objects on the observed path only, not CUDA context recovery or driver
memory reclamation. Use an owner on the same calling thread that created it.
The separate source/capability card is `registry/gpu/cuszp-fixed-1d.json`; it is
included in GPU build identity and never inserted into the CPU codec namespace.

The supported source domain is contiguous little-endian 1D `<f4`/`<f8`,
`1 <= N <= 16777216`, finite normal values or positive zero, a finite normal
positive error bound with finite reciprocal, and
`abs(value)/(2*actual_error_bound) <= 2**28`. Negative zero, subnormal, NaN and
infinity are rejected. f32 error bounds are canonicalized downward to an exactly
representable f32; f64 retains its double bound. Source-domain checking belongs to
host encode or device-input preparation. There is no silent special-value escape.
Complete independent reconstruction must still satisfy the requested benchmark
quality bound; upstream error-bound claims and sample `1.1*bound` checks do not
replace the benchmark's strict verifier.

The official FIXED format pads GPU tiles to `P=ceil(N/32768)*32768`, with one
width byte per 32 values and `4+4*width` bytes for a nonzero-width block. The
conservative domain ensures width <=30. Capacity is `125*(P/32)` bytes; even one
element needs a 1024-byte rate table. Zero-width decode blocks do not write
output, so the checked wrapper initializes the decoded array to positive zero.
All rate bytes, zero-width padding, and exact payload length are checked before
installing a persisted payload and after encoding. Grid indices and offset sums
fit the upstream signed/unsigned 32-bit fields under the declared bound.
For a one-tile grid, the upstream kernel publishes the complete local size in
`locOffset[1]` but does not write the final global `cmpOffset[1]`; the wrapper
reads the local total in that case. This fixes host size accounting without
changing the kernel or its payload format.

`CSP1` wire stores version, dtype, FIXED mode, element count, actual bound, payload
length, payload SHA-256 and metadata SHA-256, followed by native bytes. Decoder
configuration comes from persisted wire, not the encoder context. CSP1 is the
native GPU artifact; a benchmark TSB wrapper may add task/schema/implementation
identity and must count all of its bytes and packing work.

Host encode includes preflight, GPU allocation/control initialization, H2D,
kernel, size/rate D2H, completion, full payload D2H, wire hashing/packing and
output-owner release. Host decode includes wire parsing/hashes/rate validation,
H2D, a fresh decoder, zero initialization, kernel, completion, full restored D2H
and output-owner release. The executor includes session creation and checked
close within each independent-object wall interval.

Device encode takes an already prepared input and returns a completed device
payload owner plus host configuration/size. Device decode takes an independently
installed validated device payload and returns a completed decoded owner.
`materialize` and host wire packing are explicit separate work for these device
boundaries. Preparing/installing inputs and releasing retained output storage
must have declared setup/postprocess/close scopes; no host transfer is disguised
as device-only work. A persisted independent decoder should be proven by a fresh
process qualification in addition to trial recovery.

CUDA events use the actual operation's nonblocking stream. Encode event covers
control memsets, host-input H2D when applicable, the official kernel, and size/rate
D2H. Decode event covers control/output memsets and the official decode kernel.
Allocation, CPU source/rate checks, full payload/object materialization and
teardown are outside these event intervals but belong to the applicable wall
boundary. These event values are stream intervals, not isolated kernel time.
Owned allocation capacity/peak fields describe adapter-owned CUDA buffers only;
they exclude context/library allocations and other processes and are not whole
device memory measurements.

Build with `PYTHONPATH=benchmark/src python benchmark/tools/build_cuszp.py`.
The separate GPU build record captures source, bridge, toolchain, actual compile
commands/dependencies, runtime paths and binary hashes. Building does not execute
GPU work and does not establish qualification or measured performance.
