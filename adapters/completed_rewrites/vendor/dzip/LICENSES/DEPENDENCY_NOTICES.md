# Native dependency notices

The DZip algorithm source has no concluded license grant (`NOASSERTION`). The
user-authorized local workflow is recorded in `../../USER_DECISIONS.md`, with a
release copy at `reproduction/USER_DECISIONS.md`; it is
not an upstream redistribution license. This package is a local deliverable.

- Eigen: frozen TensorFlow 1.14 wheel headers, with original per-file notices.
  `Eigen-MPL-2.0.txt` is retained. Production defines `EIGEN_MPL2_ONLY`.
- libbsc: frozen DZip native dependency, Apache-2.0; see
  `libbsc-Apache-2.0.txt`. Native decoder changes are listed in
  `DEPENDENCY_PATCHES.json` and `DEPENDENCY_PORTABILITY.patch`.
- MKL-DNN 0.18: immutable TensorFlow dependency archive; see
  `third_party/mkldnn/LICENSE` (Apache-2.0) and `MKLDNN_DEPENDENCIES.json`.
  Embedded Xbyak retains Intel Apache-2.0 and MITSUNARI Shigeo BSD-3-Clause
  notices in `third_party/mkldnn/src/cpu/xbyak/`. Google Test's BSD-3-Clause
  license is retained in `third_party/mkldnn/tests/gtests/gtest/LICENSE`;
  these tests are not linked into production.
- TensorFlow 1.14 native contraction header: Apache-2.0, original Google
  copyright notices retained in `third_party/tf_cpu/`. Adaptations are
  explicitly recorded by `CPU_DEPENDENCY.json` and `CPU_DEPENDENCY.patch`.
  Apache-2.0 license text is in `third_party/mkldnn/LICENSE`. The header uses
  native Eigen/MKL-DNN only; no TensorFlow runtime is linked or executed.
- HDF5 and its transitive dependencies: externally installed native checkpoint
  parser. SBOM records the installed library hashes and package metadata.
- CUDA Runtime 10, cuBLAS 10, cuDNN 7.6.5 and NVIDIA driver: external native GPU
  dependencies subject to NVIDIA license terms. Their binaries are not bundled.
- Compiler, libstdc++, libgcc, glibc and system libraries: external toolchain
  and native runtime; SBOM records their identities and hashes.

Python, TensorFlow and Keras are test-only oracle dependencies. They are not
part of the deployed native execution path or the packaged native runtime.
