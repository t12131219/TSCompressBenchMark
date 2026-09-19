# SprintzFIRE+Huf admission review

## Admission result

`sprintz-fire-huff0` is admitted as the paper's full lossless pipeline and is
classified as `P2_PIPELINE`. It is not an alias for `sprintz-fire`: the latter ends
after FIRE/XFF prediction, bit packing and zero-block RLE, while this algorithm feeds
that exact native byte stream to Huff0. The implementation is Python-driven through
C ABI v1 and uses the existing benchmark-vendored Sprintz and Huff0 source closures.

The registered domain is homogeneous signed or unsigned 8-bit and little-endian
16-bit integer VALUE data, UTS or synchronous MTS, 1--128 dimensions, at most
120 KiB of canonical raw input, one CPU thread, and AVX2/BMI2/LZCNT. Float, lossy
quantization, validity masks, asynchronous MTS and heterogeneous element widths are
unsupported.

## Paper and benchmark mapping

The paper (arXiv:1808.02515) defines Sprintz in Section 4.1 as forecasting, bit
packing, zero-block run-length encoding and entropy coding. Section 4.4 names Huff0
as the entropy coder. Section 5.2 labels the complete FIRE pipeline
`SprintzFIRE+Huf`, distinguishes `SprintzFIRE` by removing Huffman, and distinguishes
`SprintzDelta` by replacing FIRE prediction.

The benchmark reference is `dblalock/lzbench` commit
`580c4f085381f31b1ad669525ed04e63cbc385f3`, whose
`_lzbench/compressors.cpp` exposes `sprintzXff_HUF` and
`sprintzXff_HUF_16b`. The project does not copy those wrappers verbatim: they do not
enforce destination capacity, and the 16-bit wrapper contains an unresolved `* 2 + 1`
length TODO. Instead, the project composes the same source APIs behind its bounded
adapter contract.

The immutable Sprintz closure hash is
`8535c526f5cdd430f15a9ce0ccc8bdcdd4fd820575ed67a5fe785e4dae011c4a`.
The retained Huff0 closure hash, including its license and path names, is
`af5899be99f7f09551bed864832f9b80be2069a4bb8798b30486296e4d17aa8a`.
The three replayed Sprintz patches have combined hash
`31b403a9428147a59d8c41e2527ffac4db6e72f4eed8de16c4f2511bc874c699`.
The third patch promotes low-dimensional 16-bit FIRE prediction multiplication to
64 bits after UBSan exposed signed overflow; vendor files remain unchanged.

## Native contract and accounting

The private `TSH1` frame has a 32-byte header containing element width, entropy mode,
dimension count, exact element count, exact native Sprintz length and exact serialized
payload length. The payload is one of:

- mode 0: the exact Sprintz byte stream when Huff0 returns zero;
- mode 1: a Huff0-compressed block;
- mode 2: one byte representing a constant Sprintz stream.

The raw and constant cases are explicit serialized modes, not silent fallback. The
outer 12-byte prefix, JSON descriptor, 32-byte native header and entire payload are
charged to `FinalBits`. The 32-byte header is necessary because Huff0 does not report
compressed input consumption during decode; the declared payload length makes both
truncation and appended bytes rejectable before decompression.

Sprintz's 16-bit API reports compressed length in `int16_t` units and can end on an
odd byte. The bounded wrapper parses the complete Sprintz grammar and requires the
measured length to differ from the vendor unit count by less than one element. It
also applies separate packed-length rules for low-dimensional and generic kernels.
This resolves, rather than copies, lzbench's `* 2 + 1` ambiguity.

Huff0 accepts at most one 128 KiB block. The manifest and negotiation layer enforce a
120 KiB canonical raw-input ceiling, and native code repeats the limit. No segmentation
is introduced because that would create a different pipeline lifecycle and metadata
contract. Compression candidates are written to scratch storage so a failed Huff0
attempt cannot mutate bytes beyond the final raw-fallback length.

## Native qualification

Run:

```bash
conda run -n CompressBench14 python tools/qualify_sprintz_fire_huff0.py
```

The release and ASan/UBSan profiles pass direct Sprintz and composed-pipeline
roundtrips across 8/16-bit widths, 1/4/128 dimensions, boundary row counts, patterned
and random inputs. The suite observes Huff0 and raw modes, verifies exact capacity and
canaries, and rejects truncation, suffix bytes and invalid mode values. Constant mode
is a defined response to Huff0's one-byte return, but is not claimed as observed for a
valid Sprintz intermediate stream.
The release artifact SHA-256 is
`aadba7e509b067932aa915e09b6ba7ce550923a9aeada522d9740b765dc49315`;
its compile-command SHA-256 is
`30c12b13d083cb5769f3ddefcf404f1cf14a04fb056f4d8b07601cabc9116fb7`.
The sanitizer artifact and compile-command hashes are respectively
`8038cfe2f9af14a1c85256cf90512408a375898d29766db6b86555bd08147441`
and `af76f1f3fc8a3f82afdd48e77cca7b450d99769c12fb5db8794bda58fa2cc8af`.

Alignment instrumentation is disabled because upstream deliberately performs packed
unaligned x86 accesses, and `-fno-strict-aliasing` is required. LeakSanitizer was not
run in the ptrace-managed environment. Neither is claimed as passing evidence.

## Five-layer evidence

Layer 1 uses the deterministic synthetic `<i2` MTS dataset `sprintz_i16_mts`, shape
`(4096, 4)`. Layer 2 negotiates one `DIRECT_SUPPORTED` task. Layer 3 preflight checks
correctness, immutability, determinism, output bounds and exact accounting. Layer 4
records ten independent-object formal repetitions. Layer 5 aggregates only eligible
PASS repetitions.

The qualification run set is
`runs/runset-20260919T104810Z-1b4f9ff0d416`. The formal run set is
`runs/runset-20260919T104830Z-d348067cf754`; it contains ten correctness PASS and
performance-eligible repetitions, one PASS coverage task and one summary. Report ID
`v2:report:sha256:f92cbd6da72fa3a03b78aa320c809b0b048dcc70b2bcd4584a97169727fd30b5`
records SizeRatio `0.478057861328125` and CompressionFactor
`2.0917969996808171` on this fixture.

The earlier PASS run sets `runset-20260919T104025Z-1b4f9ff0d416` and
`runset-20260919T104044Z-d348067cf754` remain append-only diagnostic evidence. They
froze an intermediate, narrower Huff0 closure-hash convention and are not the cited
admission runs; no raw record was rewritten.

These measurements establish framework integration and reproducibility, not general
performance. The dataset is synthetic and supplies no real-data performance claim.
The admission also makes no claim for scalar or non-x86 execution, streaming, query,
random access, checksums, multiple Huff0 blocks, float input or lossy Sprintz modes.
