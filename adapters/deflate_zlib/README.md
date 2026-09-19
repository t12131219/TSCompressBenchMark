# DEFLATE zlib source adapter

This adapter builds zlib 1.3.2 from the source tree vendored by the pinned local
`inikep/lzbench` checkout. All 48 files under `vendor/zlib` remain byte-for-byte
unmodified. Project behavior is isolated in the C ABI shim and Python driver.

The physical object is a versioned TSCB descriptor followed by one RFC 1950 zlib
stream containing an RFC 1951 DEFLATE payload and Adler-32 footer. The registered
variant uses level 6, a 32-KiB window, default strategy, one CPU thread, and no preset
dictionary. The shim uses `Z_NO_FLUSH` for update and loops `Z_FINISH` until
`Z_STREAM_END`; independent decode must consume the whole stream and produce exactly
the descriptor-declared byte count.

Build with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py deflate-zlib --profile all
conda run -n CompressBench14 python adapters/deflate_zlib/tests/run_native_tests.py
```

Closure SHA-256 is computed over files sorted by relative POSIX path: append the
UTF-8 relative path, one NUL byte, and the unmodified file bytes for each file.
`tests/adapters/test_deflate_zlib.py` pins all 48 files to this digest. Sanitizer
tests disable LeakSanitizer due to the host ptrace policy; ASan and UBSan remain enabled.
The ELF build uses `-Wl,-Bsymbolic-functions` so a previously loaded zlib cannot
interpose its codec functions. The native runner verifies this with a competing
`deflateInit2_` loaded through `LD_PRELOAD`.
