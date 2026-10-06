# DZip native C++17 rewrite

Status: `REWRITE_DONE`, compatibility target `SEMANTIC`. This is a standalone package;
no benchmark adapter or registry integration is included. The local license
workflow override is recorded in `../../USER_DECISIONS.md`; the release retains
its own copy at `reproduction/USER_DECISIONS.md`.

The implementation contains the full 32-bit arithmetic coder, bootstrap and
combined CPU neural graphs, GRU forward/backward computation, online Adam,
native model construction, original Keras HDF5 import, libbsc model storage,
self-contained frames and bounded APIs. Every frame retains its complete initial
model, alphabet, mode, length and integrity information. Model state is charged
in FinalBits. Native code does not execute Python, Keras or TensorFlow.

Bootstrap training uses sigmoid GRUs, Keras Adam, global clipnorm 0.1, full
2048-sample batches, best-loss checkpoint selection and patience-three early
stopping. The original Keras 2.2.2 `workers=0` path shuffles once and reuses the
order in later epochs; the native trainer preserves this observed behavior.
Optional microbatches accumulate gradients at fixed weights before one Adam
update. Native initialization uses its separately declared seeded method; it
does not claim to reproduce NumPy/TensorFlow's seed stream. Full initial weights
are stored. Weight serialization intentionally excludes optimizer continuation
slots; it is a codec checkpoint, not a resumable Adam snapshot.

Numerical profile 1 requires Linux x86_64 with AVX. Native CPU execution checks
AVX support and rejects unsupported hosts. Its isolated CPU kernel uses the
frozen Eigen AVX contraction/reduction order and MKL-DNN 0.18. Other source
operations retain float32 precision and disabled FMA contraction/fast-math.
GCC and Clang builds are qualified; ARM, Windows and cross-ISA learned-stream
portability are not claimed.

Build with a native HDF5 development installation:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DHDF5_ROOT=/path/to/hdf5
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

`DZIP_WITH_HDF5=OFF` supports deployed native graph checkpoints; its original
HDF5 import entry point explicitly rejects requests. It does not implement the
import capability on that build.

Example complete native training/encoding workflow:

```sh
build/dzip_train INPUT.txt auto TRAINED.dzn 10
build/dzip_nn_cli codec-model TRAINED.dzn bootstrap 0 CPU.dzn
build/dzip_cli encode bootstrap CPU.dzn INPUT.txt FRAME.dzc
build/dzip_cli decode FRAME.dzc RESTORED.txt
```

Use `combined` instead of `bootstrap` in the last model/encode commands for the
online-learning codec. `dzip_train` normalizes latin-1 universal newlines;
`dzip_cli encode` operates on raw bytes. Supply the same normalized input to the
encoder when reproducing the source text workflow. The source CPU codec changes
sigmoid training gates to hard_sigmoid; `codec-model` performs that explicit
transition. Original HDF5 import is available with
`dzip_nn_cli import CHECKPOINT.h5 bootstrap|combined|training SEED OUTPUT.dzn`.

Native GPU bootstrap is implemented using cuDNN GRUs, cuBLAS contractions,
Eigen GPU reductions and source-compatible sparse embedding updates. Enable it
with `DZIP_WITH_CUDA=ON`, `DZIP_CUDA_RUNTIME_ROOT` pointing to the audited native
CUDA/cuDNN installation, and `CMAKE_CUDA_ARCHITECTURES=75` on the qualified
RTX 2070 host. The selected qualification uses CUDA Runtime 11.8.89, cuBLAS
11.11.3.6, cuDNN 8.4.0 and nvcc 11.8. The frozen source oracle still uses
CUDA 10/cuDNN 7.6.5; all source differential tolerances remain unchanged.
For cuDNN 8.4, explicitly select its retained v6 RNN descriptor API:

```sh
cmake -S . -B build-cuda -DCMAKE_BUILD_TYPE=Release \
  -DDZIP_WITH_HDF5=ON -DHDF5_ROOT=/path/to/hdf5 \
  -DDZIP_WITH_CUDA=ON -DDZIP_CUDA_RUNTIME_ROOT=/path/to/cuda-11.8 \
  -DCMAKE_CUDA_ARCHITECTURES=75 \
  -DCMAKE_CXX_FLAGS=-DcudnnSetRNNDescriptor=cudnnSetRNNDescriptor_v6
cmake --build build-cuda -j2
```

This alias selects the versioned library API; it does not change GRU algorithms
or arithmetic rules. Stable CUDA intermediate names permit byte-identical independent
builds. `dzip_train` accepts `cuda` as its final backend argument; a unavailable
CUDA request rejects rather than silently changing its execution backend.

Independent GPU API calls use a native mutex to serialize the frozen backend
across handles. Model/optimizer state remains private, and CPU handles execute
concurrently. Full GPU safety is qualified only by completed checker reports.
GPU overlap or parallel throughput is not promised; all
GPU kernels, full batch sizes and numerical rules remain in use.

The complete capability qualification requires both `DZIP_WITH_CUDA=ON` and
`DZIP_WITH_HDF5=ON`. A CPU-only build explicitly lacks GPU bootstrap execution.
Scalar sigmoid training and optional microbatches are native extensions; they
are not the qualified replacement for the original full-batch GPU trainer.

Latest CPU evidence is under `validation/native-finalized-*`; selected GPU
evidence retains its original `validation/native-diagnostic-cuda84` paths.
These paths identify the candidate evaluated against the frozen oracle, not a
waiver of complete qualification. Current evidence is selected in
`PORT_MANIFEST.yaml`. CPU three-step
updates, all four GPU training regimes, and three full real-input GPU schedules
pass frozen tolerances. All six complete real-data probability trajectories
and CPU three-step updated weights match source bit for bit. GCC, Clang and
dependency-instrumented ASan/UBSan/LSan preflight checks pass. Final dataset,
CUDA safety and release audit checks pass and are recorded by `PORT_MANIFEST.yaml`
and `validation/porting_report.md`; no completion is inferred from partial
checks. Historical failures remain available; thresholds are unchanged.

The frozen dataset plan retains the first 4096 raw bytes of each CSV, then
normalizes newlines. Weather's header has non-ASCII bytes despite the plan's
“ASCII” wording. Original latin-1 symbols decode into UTF-8 text on this host;
native byte frames restore the normalized bytes. Original raw streams are not
claimed universally compatible. Source-table entropy replay is a separate
exact witness from the full native roundtrip.

The immutable source closure is in `../../Source/dzip/upstream`. Native libbsc
portability and decoder-bound patches are recorded in `DEPENDENCY_PATCHES.json`
and `DEPENDENCY_PORTABILITY.patch`; the frozen upstream files are unchanged.
