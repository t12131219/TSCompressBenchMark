# XZ LZMA2 source adapter

Spreadsheet `Value-Compress!B9` lists LZMA / xz. This adapter builds the reviewed
liblzma/common/CMake/tests/format closure from lzbench's pinned xz 5.8.3 source.
Vendor files remain unchanged; no CLI tools, installed scripts, translations or other algorithms
are copied. Public library APIs use the 0BSD license retained here.

The physical object is TSCB descriptors plus one complete .xz LZMA2 stream. The
registered path uses preset 6, no data check (matching lzbench's explicit setting),
mandatory structural CRC32, and one CPU thread. Presets 0-9 are separately identified
configurations. Extreme mode, raw LZMA/.lzma, multithreading, BCJ/delta filters and
external dictionaries are not registered. Internal LZMA2 history is not a trained
external dictionary and its properties are serialized in the block header.

Single-call `lzma_easy_buffer_encode` has a documented `lzma_stream_buffer_bound`
contract and writes the block/index/footer before returning. Mandatory project
Finalize acknowledges this completed object with zero bytes and rejects repetition;
it is not described as a streaming encoder. Internal finish work is inside native
encode API timing. Fresh-context decode checks exact output and complete input.

The Python parser uses the vendored .xz format specification to charge every stream
header, block header, structural CRC, block padding and index byte. It never treats
the mandatory .xz index as free. Internal index/header padding stays in those fields.

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py xz-stream --profile all
conda run -n CompressBench14 python adapters/xz_stream/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/xz-stream-formal.toml --output-root runs
```

Build commands include all CMake dependency translation units and archive hashes.
Specialized CRC dispatch/SIMD matching and SIMD decoder copies are disabled; generic
compiler flags are recorded. Static PIC liblzma is linked into the shim with local
ELF function binding; a competing globally loaded implementation cannot replace it.
Native timing excludes explicit prevalidation/context initialization but includes
all work internal to the single-call encode API. It is not lzbench-equivalent.

The closure digest uses sorted relative POSIX path UTF-8 bytes, NUL, then complete
file bytes. Tests pin 341 files and the digest. LeakSanitizer is disabled under the
host ptrace policy; ASan/UBSan stay enabled. Upstream library CTest currently has six
PASS and six SKIP (disabled features); these skips are not reported as passes.
