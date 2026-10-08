# Modern Stream VByte 1234 contract

This source is fast-pack/streamvbyte at the clean frozen commit in SOURCE_LOCK.json,
after review of the distinct old Benchmark variants. P0 `streamvbyte-modern-u32`
and P2 `delta-zigzag-streamvbyte-modern64` have separate identities from the
lzbench registrations. The registered backend is exactly 1234 with SSE4.1 encoding
and decoding, declared scalar tails, and no runtime fallback.

Input, lifecycle, checked int64 arithmetic, A/B/D switches, self-contained framing,
atomic rejection, independent validation, exact accounting, resource gates and
formal repetition requirements follow `../streamvbyte/contract.md`. Modern C-stage
identity and executor are independently pinned in `preprocess/streamvbyte_modern.py`.
No upstream delta32 or 0124 qualification is implied by the two registrations.

The original modern API omits count. The shim stores the four-byte word count
before the unchanged upstream bytes. This write/read and used-length adjustment
fall outside the optional native codec API interval. All bytes, including count,
remain in the pipeline stream, ledger and complete CORE/PIPELINE timing. Stage C
timing covers its FFI call, scratch work and count as well as the codec. The
auxiliary native interval measures `streamvbyte_encode` / `streamvbyte_decode` only.
It cannot be compared as complete P2 latency. Its rate denominator is the actual
uint32 word byte count, while semantic rates retain the original routed bytes.

Both original APIs require 16 bytes of internal scratch padding. The published
bound includes actual maximum control/data/count/framing bytes; scratch allocation
adds 16 bytes and the final commit copies only exact used bytes. No external
padding is required or charged as stream bytes. Decode independently checks exact
count, length and unused control bits before the upstream call. Misaligned typed
input/output is staged through memcpy, preserving all bits. The recorded safety
patch replaces a potentially unaligned control store with memcpy in the build
tree; vendor and source checkout remain unmodified.

Apache-2.0 and BSD-3-Clause notices apply. The admission card distinguishes pending
tests from completed evidence; construction of a manifest alone is not acceptance.
