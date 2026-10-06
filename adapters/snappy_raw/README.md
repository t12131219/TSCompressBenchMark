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

Current build and run evidence is recorded in
[`docs/snappy_raw_evidence_refresh.json`](../../docs/snappy_raw_evidence_refresh.json).
Check both binary/build-record hashes against the onboarding card and audit the current
AlgorithmID run evidence without rebuilding:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/refresh_snappy_evidence.py --verify-card
```

For a future rebuild, use a new versioned `--report docs/snappy_raw_evidence_YYYYMMDD.json`
path, review its result, and update the card's build hashes and evidence references.
The tool runs release/sanitizer ABI smoke, existing adapter/timing tests, qualification
and a standalone formal profile. It retains resource-pressure runs; correctness PASS
does not make a rejected formal performance group eligible. Old reports are not overwritten.
