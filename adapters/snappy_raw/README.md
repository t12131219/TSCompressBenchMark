# Snappy raw source adapter

This adapter uses the Snappy source vendored by the pinned local `inikep/lzbench`
checkout. Files under `vendor/snappy` are copied byte-for-byte and remain unmodified;
project behavior is isolated in `native/tscb_snappy_raw.cc` and the Python ABI driver.

The physical object is a versioned TSCB buffer-descriptor header followed by exactly one
Snappy raw stream. Snappy raw embeds the uncompressed length and literal/copy commands,
but has no framing layer, footer, or checksum. It therefore remains a separate semantic
profile from LZ4 Frame and Zstd Frame. `finalize` is a required one-shot no-op that writes
zero bytes; repeated finalize is rejected.

Build the release and sanitizer artifacts with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py snappy-raw --profile all
```

The registered variant is scalar, single-threaded, dictionary-free, and fixed to Snappy
compression level 1. The wrapper preserves routed buffer order and raw IEEE bytes and
does not cast, reorder, fill, interpolate, or drop values.
