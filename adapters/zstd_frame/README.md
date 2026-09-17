# Zstd Frame source adapter

This adapter uses the Zstd 1.5.7 source closure vendored by the frozen local
`inikep/lzbench` checkout. The copied files under `vendor/zstd` are unmodified;
project-specific code is confined to `native/tscb_zstd_frame.c` and the Python C-ABI
driver.

The physical object is a versioned TSCB buffer-descriptor header followed by one complete
Zstd frame. `compress_update` calls `ZSTD_compressStream2(..., ZSTD_e_continue)` and
`finalize` repeatedly calls `ZSTD_compressStream2(..., ZSTD_e_end)` until it returns zero.
The frame epilogue and configured content checksum therefore enter both measured time and
`FinalBits`. The adapter is single-threaded, dictionary-free, and uses a new native context
for every independently measured object.

Build the reviewed release and sanitizer artifacts with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py zstd-frame --profile all
```

The Python wrapper serializes routed logical buffers in their declared order and includes
descriptor/FFI work in the declared pipeline boundary. It does not cast, reorder, sort,
fill, interpolate, or drop values. No patch is applied to the benchmark-vendored source.
