# Optimization disposition

Status: `OPTIMIZATION_NOT_APPLICABLE`

The frozen Prometheus XOR byte stream is stateful at sample granularity:
timestamp delta-of-delta coding, value-window reuse and bit offsets all depend
on the preceding sample. There is no independent block boundary inside
`XORChunk.Bytes()` that can be vectorized or processed in parallel without
changing the bitstream or reset semantics.

The canonical implementation already uses allocation-free caller buffers for
the core encode/decode path and compiler-provided count-leading/trailing-zero
instructions when available. Architecture-specific SIMD or threading would
add dispatch and tail paths without removing the serial codeword dependency.
No distinct optimized variant is therefore shipped for this rewrite. The
scalar implementation remains the only execution path and is measured in
`validation/performance_result.json`.
