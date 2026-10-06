# DeepZip standalone semantic contract, version 1

This contract covers the complete byte-file compression pipeline at upstream
commit `8c35502397a1488c89fa282ed033cc9d5fd4b4dc`, not just an RNN primitive.
Compatibility target is SEMANTIC. All 17 reachable public model constructors
are required; GPU prediction, lane partitioning, float16/float32 weights,
batch normalization and all activation choices remain required capabilities.
Training is a separate external model-authoring tool, not codec execution.
The two constructors that raise NameError before building a model are
documented as unsupported upstream paths, not emulated repaired algorithms.

## Input and model state

Input is contiguous uint8, not numeric floating-point CSV values. A caller
supplies the complete ID-to-byte alphabet in the source's order. The mapping
must be injective, contain 1 through 256 entries, agree with the model's input
embedding/output dimensions, and cover every input byte. Preserve this
dictionary in the stream. No normalization, rounding, sorting or implicit
training is performed. Context length is 64, recurrent state resets to zero
on each prediction. Batch size is a positive lane count with resource limits.

Model loading preserves every HDF5 tensor and its float16/float32 values.
Native HDF5 import covers the frozen Keras 2.2.x fixed-width byte-attribute
checkpoint profile. Variable-length name attributes are explicitly unsupported
because HDF5 attribute reads cannot apply a bounded allocation manager; they
must be repacked into the bounded portable representation before import.
The portable test representation DZMODEL1 is little endian: eight-byte magic,
u32 ASCII model-name length, name, u32 layer count; each layer has u32 kind,
u32 flags, u32 activation, u32 tensor count, f32 epsilon; each tensor has
u32 rank, rank u32 dimensions and row-major f32 values. Conversion of a
float16 weight to f32 is exact; flag bit 2 preserves half arithmetic mode.
Kinds are embedding=1, GRU=2, LSTM=3, dense=4, flatten=5, batchnorm=6.
Flag bits 0/1 mean return-sequences/bidirectional. Activations are linear=0,
ReLU=1, ELU(alpha=1)=2, SELU=3, softmax=4. Unknown versions, dimensions,
flags, profiles or nonfinite weights must fail before inference.

CuDNNGRU weights use Keras z/r/h gate order, reset-after equations and separate
input/recurrent bias halves; the recurrent candidate contribution is reset
after matrix multiplication. CuDNNLSTM uses i/f/c/o order and two bias halves.
Backward sequence outputs are restored to forward time order before concat;
when return-sequences is false the final hidden state of each direction is
concatenated. Dense/flatten use Keras row-major order. Batchnorm is inference
with frozen moving mean/variance, gamma/beta and epsilon=0.001.

Keras 2.2.2 `_canonical_to_params` directly flattens each gate slice with shape
[input,units] into cuDNN's packed [units,input] matrix without transposing it.
This legacy packing is part of the actual source behavior. The native importer
preserves stored Keras tensors; inference applies this packing when indexing
them. Using a modern Keras GRU matrix interpretation changes probabilities.

The canonical predictor uses scalar f32 operations and explicit round-to-even
half conversions at half layer boundaries, with FP contraction and fast-math
disabled. Source-vs-rewrite probability tolerances are 3e-5 (float32) and 3e-3
(float16); these are frozen before implementation. Lossless output has no
tolerance: decoded bytes must be identical. A GPU variant is explicit and
must be tested without silent CPU fallback. Its floating-point execution
profile is stream state if it affects arithmetic frequencies. Do not claim
cross-device or source byte compatibility solely from close probabilities.

## Probability conversion and entropy coding

Observed NumPy 1.16.4 evaluates `prob * 10000000 + 1` in **float64**, for both
float32 and float16 probabilities. Sum these float64 terms in symbol order
and only then truncate each cumulative sum to uint64; do not truncate each
individual frequency, accumulate in f32, or force the final sum to 10000000.
Uniform bootstrapping uses the same float64 expression. Counts must strictly
increase and total must not exceed 2^30+2. Nonfinite or invalid probabilities
produce a diagnostic error before any arithmetic update.

Use the original 32-bit inclusive low/high arithmetic range, uint64 products
and integer division. Emit MSB first, propagate pending underflow bits when
shifting, and finish by emitting a single one bit (without artificially
draining pending underflow bits). Zero-pad the final physical byte. Decoding
supplies virtual zeros after arithmetic EOF. Framing must detect physical
truncation before invoking this rule; virtual zeros are not permission to
accept a truncated container.

## Partitions, tail and stream lifetime

For N input bytes and B lanes, each primary lane has floor(N/B) consecutive
symbols. The first min(64,lane_length) symbols are uniform. Each later symbol
is predicted from its preceding 64 symbols in that lane. The final N mod B
symbols are another independent arithmetic stream with the same bootstrap
and prediction rule. Emit all B lane streams, then the tail, even when empty.
The upstream custom length encoding emits low 7 bits with continuation, then
shifts by seven and subtracts one; its inverse adds the next radix place on
continuation. Reject overflow, noncanonical encodings and missing lane bytes.

The source main entrypoints build 65-wide strided arrays and cannot safely
serve N<65. The native API defines N=0/1/2 and other short blocks by the same
uniform arithmetic bootstrap, independently verified against the source
arithmetic coder; no source pipeline success is claimed for invalid strides.

Each independent codec object owns model/configuration and buffered input.
Append preserves byte order; finalize returns the complete ordered container;
repeated finalize returns the same bytes. Append after finalize is invalid;
reset discards prior buffered data and coder state while retaining configuration.
No caller input is modified or overread. Capacity-bound errors leave output
unchanged. Declared limits bound model, input, lanes, dimensions and allocation.

## Container and accounting

The native versioned container must include original length, B, dictionary,
model representation and numeric profile, all arithmetic stream lengths,
streams/padding, and checksums needed to reject corruption. Embedding model
state makes decoding self-contained. If an external model mode is exposed,
its full model bits and identity must enter the external-side-information
ledger. Full FinalBits is physical container bytes times eight plus external
state; report model, metadata/dictionary, entropy payload, lengths, padding
and checksum components separately and verify their exact sum.

SEMANTIC does not require source/rewrite cross decoding. Identical frozen
cumulative tables must nevertheless produce exactly the original arithmetic
bytes and lane framing. Native encode/decode and canonical/GPU independent
round trips must restore identical input, and all required model/partition
paths must be directly callable through the standalone API.

Public errors distinguish invalid parameter, invalid input/model,
unsupported numeric profile, resource limit, insufficient output capacity,
corrupt/truncated stream and device failure. No fallback changes an explicitly
selected execution path. The rewrite has no benchmark adapter dependencies.
