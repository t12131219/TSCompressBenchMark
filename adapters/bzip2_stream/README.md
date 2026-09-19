# bzip2 1.0.8 source adapter

This adapter builds libbzip2 1.0.8 from the source tree vendored by the pinned
local `inikep/lzbench` checkout. The 12 files under `vendor/bzip2` are copied
byte-for-byte; project behavior remains in the C ABI shim and Python driver.

The registered physical object is a versioned TSCB descriptor followed by one
complete bzip2 stream. It is a standalone BWT, MTF/RLE, and Huffman pipeline,
not a pure Huffman primitive. The registered default is compression level 9
(900,000-byte internal blocks), work factor 30 (the libbz2 value selected by
API argument 0), normal-memory decode, one CPU thread, and no concatenation.
Decode must reach `BZ_STREAM_END`, consume all input, and emit exactly the
descriptor-declared number of bytes.

Build and test with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py bzip2-stream --profile all
conda run -n CompressBench14 python adapters/bzip2_stream/tests/run_native_tests.py
```

The closure digest is SHA-256 over each sorted relative POSIX path, one NUL,
and its unmodified bytes. GCC warnings caused by the upstream coroutine-style
decoder macros and intentionally unused diagnostic/allocator values are
disabled explicitly; all other warnings remain errors. The ELF build uses
`-Wl,-Bsymbolic-functions`, and the native runner verifies that a competing
global `BZ2_bzCompressInit` cannot interpose the vendored implementation.
