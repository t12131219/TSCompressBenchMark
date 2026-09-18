# Brotli stream source adapter

This adapter builds the Brotli 1.2.0 source closure vendored by the pinned local
`inikep/lzbench` checkout. Files under `vendor/brotli` remain byte-for-byte unmodified;
project behavior is isolated in the C ABI shim and Python driver.

The physical object is a versioned TSCB descriptor followed by one complete RFC 7932
Brotli stream. The shim uses `BROTLI_OPERATION_PROCESS` for update and loops
`BROTLI_OPERATION_FINISH` until `BrotliEncoderIsFinished`, so final markers enter time
and `FinalBits`. Decode uses an independent `BrotliDecoderDecompress` operation and the
descriptor's exact decoded length. The registered variant is quality 5, window 22,
generic mode, one CPU thread, no external dictionary, and no checksum.

Build with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py brotli-stream --profile all
```
