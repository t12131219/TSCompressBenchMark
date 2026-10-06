# DeepZip C/C++ rewrite

Native C++17/CUDA implementation of the complete DeepZip byte-file codec.
All 17 reachable upstream predictor architectures are covered. The standalone
runtime performs no Python, TensorFlow or Keras calls. See `PORT_MANIFEST.yaml`
for the gate result and `contract_v1.md` for the SEMANTIC contract.

The first-batch recommendation order selects `deepzip` after the completed
Prometheus XOR, ABBA, and fABBA tasks. G0 is complete: the full DeepZip
compressor/decompressor pipeline owns this AlgorithmID, while
`DeepZip_RNN_Predictor` is a duplicate stage and is not a separate rewrite.

The original oracle was restored and hash-locked under `../../Source/deepzip/`.
Its Python 3.6 / TensorFlow GPU 1.8 / CUDA 9 / cuDNN 7 dependencies are
validation tools, separate from the native runtime. `FC_16bit` and
`LSTM_multi_selu` raise upstream NameError before model construction and are
explicitly unsupported; all remaining constructors run and are tested.

Build the complete GPU-capable package with native HDF5 and CUDA 11.8:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DDEEPZIP_WITH_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DHDF5_ROOT=/path/to/native/hdf5
cmake --build build -j4
ctest --test-dir build --output-on-failure
build/deepzip_tests tests/fixtures/biGRU.dzm cuda
```

Scalar builds use `-DDEEPZIP_WITH_CUDA=OFF`; portable-model-only builds can use
`-DDEEPZIP_WITH_HDF5=OFF`. Disabled features return explicit unsupported errors;
CUDA requests never silently fall back to CPU.

Public API: `include/deepzip/deepzip.hpp`. `Model::from_hdf5` imports frozen
Keras 2.2.x fixed-width-attribute checkpoints. `Model::load` loads a bounded
portable model. `Config::alphabet` contains the complete ID-to-byte dictionary,
with the model's width and the original symbol order.

```sh
build/deepzip_cli import weights.hdf5 biGRU weights.dzm
build/deepzip_cli encode weights.dzm input.bin output.dzc 1000 alphabet.bytes cuda
build/deepzip_cli decode output.dzc restored.bin
```

`alphabet.bytes` has one literal byte per symbol in ID order. The container
embeds dictionary, model, length, lane count, numeric profile, stream lengths
and checksums. Decoding needs the declared backend and no external checkpoint
or sidecar. FinalBits includes all model bytes, even when that cost exceeds
entropy savings. CPU/CUDA containers identify their numerical profile.

Use `Codec::append/finalize/reset` for fragmented input. Repeat finalize is
idempotent; append after finalize requires reset. The buffer API checks its
declared bound before writing; insufficient output remains untouched. Safe
overread is zero.

`validation/` records all-model differential/pipeline tests, three raw CSV-file
byte datasets, exact source-table arithmetic replay, ASan/UBSan/LSan and GPU
checks, AArch64/QEMU cross decoding and reproducible build hashes. These are
byte-codec correctness tests with no numeric casts or training on test data.
The deterministic local release archive and its hashes are in `release/`.

No adapter, registry, benchmark configuration, or framework source was changed.
