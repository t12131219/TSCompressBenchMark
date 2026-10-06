# DeepZip contract draft

This historical draft is superseded by the frozen [contract_v1.md](contract_v1.md).
G1/G2 passed on 2026-10-03 after the original runtime was restored. The new
contract covers all 17 reachable model constructors and required GPU execution.

This draft records the source behavior that is already observable and prevents
scope drift when the oracle environment becomes available.

## Selected semantic profile

- Pipeline: preprocessing, `biGRU` probability prediction, probability-to-count
  conversion, 32-bit arithmetic coding, lane framing, and lossless decoding.
- Checkpoint: `xor20/biGRU.hdf5`, SHA-256
  `11c83907881b14ed3c670b6b37cacad06fc9657872c520bd772693cb04919fe2`.
- Input: a one-dimensional byte sequence whose alphabet contains exactly two
  symbols and whose byte-to-ID mapping is supplied by the preprocessing state.
- Context: 64 symbols. Source batch size: 1000 lanes.
- Compatibility target: semantic equivalence. The upstream representation is
  not a self-describing public standard.

## Predictor and integer frequencies

The selected model is Embedding(2,32), two bidirectional CuDNNGRU(32) layers,
Dense(64, ReLU), and Dense(2, softmax), with IEEE-754 binary32 weights. Initial
symbols use a uniform distribution. Later symbols use model probabilities.
The source computes counts as `probability * 10000000 + 1`, then applies NumPy
`cumsum` into a `uint64` destination. Exact casting, CuDNN gate order, the two
96-element GRU bias halves, softmax numerics, and GPU determinism remain oracle
questions and are not guessed here.

## Arithmetic stream

Each lane has an independent 32-bit arithmetic coder. Bits are emitted most
significant bit first. `finish()` emits one bit and closing the bit stream pads
the last byte with zeros. End-of-input during decode supplies trailing zero
bits, matching the upstream implementation.

## Framing and side information

The `.combined` source file is the ordered concatenation of 1000 lane streams
and one tail stream. Every stream is preceded by the source's custom base-128
length encoding. The `.params` JSON sidecar carries `len_series`, `bs`,
`timesteps`, and `id2char_dict`. The HDF5 checkpoint is additional external
state. A future standalone container must account for the model, dictionary,
parameters, per-lane lengths, arithmetic bytes, and padding in FinalBits.

## Invalid and unresolved cases

Empty input, a one-symbol alphabet, alphabets other than checkpoint width two,
malformed varints, truncated streams, inconsistent sidecars, model hash
mismatch, and size overflow need explicit G2 decisions. No behavior is frozen
until the source oracle runs under the locked runtime.
