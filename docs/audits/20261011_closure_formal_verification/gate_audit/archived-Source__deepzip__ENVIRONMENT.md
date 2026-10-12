# DeepZip reference environment

The original GPU encoder and decoder run on RTX 2070 (driver 535.288.01) with
Python 3.6.13, TensorFlow GPU 1.8.0, CUDA 9.0, cuDNN 7.1.2, NumPy 1.16.4,
Keras 2.2.2, Keras Applications 1.0.4 and Keras Preprocessing 1.0.2.
Keras 2.2.4 with its corresponding dependencies produces the same xor20 stream.

Use these environment settings for the source oracle:

```sh
export LD_LIBRARY_PATH=/tmp/tscb-deepzip-oracle/lib
export PYTHONPATH=/tmp/tscb-deepzip-keras222
export PYTHONDONTWRITEBYTECODE=1
export TF_FP16_RNN_USE_FP32_COMPUTE=0
```

GPU tests require host device access. A sandboxed device probe is not evidence
of absent hardware. Oracle sessions use one intra/inter-op thread and GPU
allow-growth. The original algorithm source is unchanged.

The last setting is a TensorFlow 1.8 supported environment flag, not an
algorithm patch. With its default value, half-precision RNNs fail in
`cudnnGetRNNLinLayerMatrixParams` because the RNN computation descriptor is
float32 while input/parameter descriptors are half. Setting it to zero makes
these descriptors consistent. All 17 reachable public model constructors
then pass finite, deterministic inference; float32 is unaffected. The
cuDNN 7.6.5 comparison alone does not fix this error.

`ORACLE_ENVIRONMENT_LOCK.json` records all 30 conda acquisition archives,
the 32 resolved Python distributions, installed file hashes, and the 31 pip
acquisition archives (including the Keras 2.2.4 comparison). The selected
package list is `oracle-requirements.txt`. Conda acquisition cache:
`/tmp/tscb-legacy-conda-pkgs`; pip acquisition cache:
`/tmp/tscb-deepzip-wheelhouse`. These paths are caches, not release dependencies.
The exact archive hashes must be verified before rebuilding the oracle.

The source toolchain is separate from the native rewrite. No Python,
TensorFlow or Keras runtime may be used to implement C++ prediction. NVIDIA
runtime libraries used by the oracle remain externally licensed tools and
are not redistributed in the release.
