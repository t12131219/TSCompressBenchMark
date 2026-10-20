# Sprintz family — N2 frozen plan (2026-10-17)
Route: NATIVE_PORT, native Apache-2.0 Sprintz core and BSD-2-Clause Huff0.
Not a core translation, not REWRITE_DONE, not FULL_PARITY and no Bench integration.
Four AlgorithmIDs: sprintz-delta, sprintz-fire, sprintz-delta-huffman,
sprintz-fire-huffman. FIRE is upstream xff, not a renamed Delta predictor.

Target: x86_64 little endian, GCC/Clang, AVX2/BMI2/LZCNT/POPCNT; runtime
rejection on unavailable ISA. API uses unsigned 8/16-bit integer bit patterns,
row-major flat arrays, ndims 1..128, input bytes <=65536, any element count
including empty and incomplete rows. Signed integers use identical bit patterns;
no implicit float quantization. Batch, reset predictor every call, no global
mutable codec state. No timestamp coding, no streaming, no parallel core claim.

Required main paths: auto dispatch and forced general RLE, forced lowdim RLE
(8-bit dims1..4, 16-bit dims1..2), Delta/FIRE and optional author Huff0 envelope.
Additional ablations: bitpack-only and Delta without RLE (8/16); legacy FIRE
without RLE is 8-bit only. Raw codecs carry native metadata, no invented frame.
Huffman stage preserves upstream ret0/ret9 raw, ret1 constant, ordinary Huffman
branches. Upstream 16-bit Huffman +1 convention retained; non-Huffman native
16-bit length truncation is recorded as a format/length repair, not byte identity
with a truncated source stream. Expected output byte count and config are
explicit decoder inputs. Reject mismatched metadata, short/extra data, oversize,
unsupported configs, output exhaustion and malformed run/bitpack framing.

Safety: stage into owned zero-initialized padded buffers; prevalidate full native
structural grammar before native decode; output padding covers SIMD wide stores.
C API reports errors, sets produced=0, never writes caller output on failure;
alloc failures caught. Overlap permitted because staging precedes commit. Bound
is conservative and includes metadata, group headers, row padding and Huffman.
No checksum is used as a substitute for structural validation. Native allocation
failures require checked ownership or explicit blocking before qualification.

N3/N4 plan: untouched baseline build; exact bytes where source length is valid;
corrected 16-bit candidate size and both cross-decode directions separately;
seeded random/zero/ramp/extrema, RLE7/15-bit, short128 threshold, group/tail,
dims1..128 boundaries; invalid configs, capacities, truncations/mutations,
ASan+UBSan (no disabled categories), LSan, independent calls/thread checks,
compiler differential, deterministic forced dispatch, real integer data (not
synthetic canonical renamed real). Native primitive/in-place/query and obsolete
1D/other entropy paths inventoried separately; unqualified paths not exposed in
safe ABI. No silent ISA fallback. Failures block their capability/N gate.

N5 plan: installable C ABI/static+shared core, CLI, local frozen dependencies,
source manifest, replayable patch, four matrices, immutable test evidence,
clean offline rebuild, cold decode, standalone consumer and release hash index.
Performance if measured is standalone only, never Bench FORMAL qualification.
