# LZ4 Frame source adapter

This adapter uses the LZ4 1.10.0 source closure vendored by the frozen local
`inikep/lzbench` checkout.  The copied files under `vendor/lz4` are unmodified;
project-specific code is confined to `native/tscb_lz4_frame.c` and the Python C-ABI
driver.

The physical object is a small versioned TSCB buffer-descriptor header followed by one
complete LZ4 frame.  `compress_update` writes the LZ4 frame header/body and
`finalize` calls `LZ4F_compressEnd`, so the end mark and configured content checksum are
always included in `FinalBits`.  The Python wrapper serializes all routed logical
buffers in their declared order and records this as the adapter boundary; it does not
cast, reorder, sort, fill, or drop values.

Build the reviewed release and sanitizer artifacts with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py lz4-frame --profile all
```

The shared source checkout remains read-only.  No patch is applied to the vendored LZ4
files; `patches/` is reserved for future, explicitly hashed changes.
