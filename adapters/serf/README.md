# Serf-Qt and Serf-XOR native adapters

This adapter vendors the minimal float32/float64 source closure from
`Spatio-Temporal-Lab/Serf` commit `b38450b56825eabc96be8e25d6880127dc688c95`.
The source was selected from the upstream benchmark and correctness tests named in the
source artifact. Python drives two separately compiled C ABI v1 libraries.

The registered stream is a project container around the upstream Serf block payload. Each
record charges its logical count, exact valid-bit count, byte-rounded payload and frame
checksum. The outer descriptor charges names, shape, dtype, absolute error bound, block
size and Serf-XOR adjustment. Capacity and upstream estimated ratios never enter
`FinalBits`.

Qt resets for every block, matching its upstream block API. XOR state and adaptive zero
positions continue across finite blocks within a column, matching the upstream benchmark;
columns start independently. A non-finite or upstream-unrepresentable block is stored as
an explicit, fully charged raw exception block so the benchmark boundary suite cannot turn
NaN, infinity or an overflow into an unbounded lossy result. Formal finite-data runs report
whether this path was absent.

Three replayed patches replace undefined aliasing/shift operations, bound prefix-mask
indices, and prevent the bit reader from dereferencing a word after the physical input.
They do not change the selected approximation, valid bitstream, or entropy coding. The upstream
project declares CC BY-NC 4.0 in its README. Execution is allowed for evaluation, but
redistribution and commercial use remain restricted and require separate review.
