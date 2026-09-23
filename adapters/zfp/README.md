# zfp fixed-accuracy 1D adapter

This adapter vendors the serial C source closure from LLNL zfp commit
`c0c2c40b30d99f1787664b51c593fb6e0d729253` under its BSD-3-Clause license.
It registers only fixed-accuracy, one-dimensional, per-column compression as
`zfp-accuracy-1d`. Fixed-rate, fixed-precision, reversible, OpenMP, CUDA and native
2D/3D/4D execution are different benchmark identities and are not silently exposed.

Every compressed column contains `ZFP_HEADER_FULL`. The benchmark frame additionally
records the requested and the power-of-two accuracy actually selected by
`zfp_stream_set_accuracy`, dimensions, dtype, mode, per-column lengths and a complete
frame checksum. Columns containing NaN, infinity, negative zero or subnormal values are
stored as fully charged raw IEEE exception records. Positive finite values are always
handled by upstream zfp; codec failures do not fall back to raw storage.

Build and qualify with:

```text
conda run -n CompressBench14 python tools/build_codec.py zfp-accuracy-1d --profile all
conda run -n CompressBench14 python adapters/zfp/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/adapters/test_zfp.py
```
