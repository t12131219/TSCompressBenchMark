# CAMEO family repaired-v1 Benchmark binding

Ten distinct entries: cameo (CAMEO/SIP), vw, pip, tp, swab, sim-piece,
pmc-mean, swing-connected, dft, dwt-dct-ii. The final transform is orthonormal
DCT-II, not a wavelet. See docs/cameo_family_integration/README.md at project root.

vendor/cameo_family is an unchanged, per-member hash-frozen subset of the
full-parity-20261021 release (FROZEN_SOURCES.json). Includes complete production
C++/C sources, numerical source archive, numerical overlay/build recipes,
licenses and reference test objects. No historical wheel/Fortran binaries or
validation toolchains enter the production build. Native reuse: pocketfft,
OpenBLAS 0.3.21 C LAPACK ILP64. The binding additionally uses the released MIT
nlohmann/json header to parse configuration; it is included in the measured
create path according to prepared/fresh lifecycle. No original-source parity
or performance claim follows automatically from the standalone qualification.

native/binding.cc implements owning native_core and atomic C ABI v1. A bound
query performs arithmetic only. CF01 frames are unchanged; CFM1 is an independent
column collection whose full header/lengths/CRC are charged. Encoder and decoder
share no context/model; the core decoder accepts empty config only. Input domain
and source reconstruction length changes are rejected, never repaired by filling.

The offline CMake build hides numerical/JSON symbols and hashes actual compiler
closure, toolchain, static archives and runtime dependencies. A locked, verified
content-addressed shared closure avoids rebuilding the same numerical library
for each key. Rebuild entry: PYTHONPATH=benchmark/src python -m tsbench build cameo.
