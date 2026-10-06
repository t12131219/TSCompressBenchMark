# Supplement to the frozen raw-stream contract

The G2 raw-stream contract and source corpus remain byte-identical. This
additive storage API makes the transport accounting required there concrete:
one source encoding byte (5 integer or 6 floating), an eight-byte big-endian
unsigned raw length, then the unchanged raw source chunk. The encoding byte
must be 5/6 and the length must exactly equal frame size minus9. The minimum
frame size is12. Raw finalize/CLI operations retain the frozen source format.

For each stored frame, FinalBits = raw-byte-count*8 +72. Raw physical bytes
already include all source headers, layout, ST, buckets and final padding;
they are not payload entropy bits alone. Multiple chunks each pay72 bits.
No out-of-band type, length, model, dictionary or initial value is required to
decode a frame. There is no checksum or claim to upstream envelope compatibility.

`Cursor::reset_frame` validates the envelope and borrows its raw buffer;
`Chunk::reset_frame` validates the complete raw decode transactionally and
adopts its kind. The frame reader uses the encoded length and cannot read past
it. `serialize_frame` reports the required bytes through `written` and rejects
capacity-1 without touching output. Raw and frame APIs are tested separately.

The supplementary integer-to-float option preserves both source nil-output and
reused-output arithmetic. It does not alter raw source encoding or the default
nil-output getter. These API additions were completed before final qualification.
