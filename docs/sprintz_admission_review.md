# Sprintz-Delta / Sprintz-FIRE admission review

## Admission result

The complete benchmark-derived Sprintz source path is admitted as two algorithms:
`sprintz-delta` and `sprintz-fire`. This is the upstream semantic boundary, not
an artificial proliferation of variants. `dblalock/sprintz` exposes separate
Delta and FIRE/XFF codec functions, and lzbench registers them separately as
`sprintzDelta` and `sprintzXff`. There is no predictor-neutral `Sprintz` function
or bitstream whose results could be assigned to an unambiguous single AlgorithmID.
Merging the predictors under one ID would mix two executable algorithms and violate
the benchmark's identity and fairness contracts.

The expanded registrations support lossless homogeneous `int8`, `uint8`,
little-endian `int16` and `uint16`; UTS and synchronous MTS; native row-major
matrices or SOA channel inputs; and 1--128 dimensions. Python drives the original
C++ through C ABI v1. MTS is encoded as one coupled row-major stream containing
all channels, not as one selected channel or a multiplied single-channel result.
The required execution path is single-threaded x86 AVX2/BMI2/LZCNT with no fallback.

The older `sprintz-delta-u8` and `sprintz-fire-u8` registrations and their evidence
remain intact as historical, restricted admissions. They must not be interpreted as
the capability limit of the new registrations or silently aggregated with them.

Spreadsheet `Value-Compress` rows 43/44 and `参考TSBench` row 5 resolve to the
clean local `dblalock/sprintz` checkout at commit
`a056cdb67d049669875ab5487359aca99ae873ea` (Apache-2.0). The TSBench
directory is a symlink to that checkout. The benchmark
`cpp/Compress/test/test_sprintz_8b.cpp` calls
`sprintz_compress_delta_8b` / `sprintz_decompress_delta_8b` and
`sprintz_compress_xff_8b` / `sprintz_decompress_xff_8b`; the latter is the
FIRE/XFF predictor variant. `sprintz.cpp` dispatches to low-dimensional and
general row-major RLE implementations; 16-bit paths also exist. These are
multi-channel integer codecs, not a generic float-byte entropy backend.

The original benchmark implementation lacked the mandatory native safety contract: the public
compress functions receive an output pointer but **no capacity**, and the
decompress functions receive neither compressed length nor output capacity.
The decompressor reads metadata from the stream before decoding. A Python
buffer allocation, a post-call length check, or an ASan pass on well-formed
streams cannot establish bounds safety for corrupted streams. An in-tree
wrapper must first prove a worst-case output allocation and validate the full
encoded grammar and expected decoded length before entering the vendor
decoder (or isolate it with a separately qualified worker protocol). It must
then distinguish 8/16-bit width, signed bit-pattern semantics, MTS channel
coupling, row layout and optional padding, charge all metadata, and pass
0/1/2, boundary, tail, truncation and sanitizer checks. The restricted u8 UTS
admission below addresses these requirements; it does not qualify other widths
or topologies.

## 2026-09-19: benchmark-fork audit and historical limited native candidate

The additional reference is `dblalock/lzbench` at commit
`580c4f085381f31b1ad669525ed04e63cbc385f3` in
`Source_Code/_repos/sprintz-lzbench` (clean checkout). Its
`_lzbench/compressors.cpp` wrappers use the 8/16-bit Delta and XFF vendor
functions, while `_lzbench/lzbench.h` registers `sprintzDelta` and
`sprintzXff`. The wrapper receives `outsize` but does not use it. The
`sprintz/sprintz.cpp` implementation agrees with the original Sprintz
checkout, not a safety-enhanced fork. The fork's labels identify XFF with
FIRE. The license notice is copied from the original Apache-2.0 checkout.

The project now retains only the required 8-bit low-dimension compilation
closure under `adapters/sprintz/vendor/sprintz`, byte-for-byte from the
benchmark fork. The Delta and XFF translation units have respective SHA-256
values `5a51d6c94a5df7a2fd66303a6eb0e823ff332127b71dedbac6c6af7079c0e11f`
and `ebd7345fbca90312067736406271bfb717bd46ec92559caa2de6a6c620977297`.
The original checkout and the benchmark fork remain unmodified. A separately
replayed patch (`adapters/sprintz/patches/0001-lowdim-byte-safety.patch`,
SHA-256 `a7cc59c688c2e7e75bc59a27dd0771c415d5fb7c205eab79658776cbde49a620`)
repairs low-dimensional header allocation, 8-bit unaligned wide accesses,
negative signed shifts in ZigZag and FIRE's coefficient expression, and
unchecked native heap allocations. The
unmodified 128-element Delta roundtrip is **not safe**: the upstream probe
reports an ASan heap-buffer-overflow in `sprintz_delta_lowdim.cpp:510`,
writing eight bytes to a one-byte allocation, plus UBSan alignment errors.

`adapters/sprintz/native/bounded_lowdim.cc` is the bounded implementation
behind the registered u8 UTS adapter. It permits
only one channel, unsigned 8-bit integer bit patterns, at most 131072
elements, and fixed AVX2/BMI2; it does not claim signed, 16-bit, float,
multi-channel, generic byte-entropy, or runtime ISA fallback support. It
checks the complete 8-byte metadata, group headers, packed byte widths,
run-length operands (including the terminal zero filler), exact stream
consumption and exact expected output length before vendor decode. A decoder
scratch buffer supplies 16 bytes of safe input overread and 64 bytes of
output overwrite margin; only the validated logical output is copied to the
caller. The encoder similarly uses a private buffer and never exposes its
nonsemantic wide stores. The conservative private/output bound is
`8 + 4*N + 64`: under the 8-bit one-channel format a block consumes eight
elements and emits at most eight packed bytes or two RLE bytes, with at most
one additional header byte per begun block, plus an uncompressed tail. The
same validation is applied to freshly encoded output before it is returned.

Reproduction: `conda run -n CompressBench14 python tools/qualify_sprintz_native.py`.
The script reconstructs the patched compilation closure from unmodified
vendor files, then compiles and runs release and ASan/UBSan tests. Both
profiles currently pass 136 boundary/pattern roundtrips and 4096 randomized
roundtrips per algorithm, with truncation, tampered channel metadata,
capacity/canary checks, mutated streams, randomized hostile input and the
131072-element limit. A separate wrapped-allocator test injects each vendor
allocation failure for both codecs under both profiles. An independent
release build of the unmodified benchmark fork and the patched closure
produced byte-identical output on 128 specified input/variant combinations
(comparison corpus SHA-256
`6ca493cc197ac72b79f2735ca2597d51e24ca5a72287b1e3b5818edda19f86d7`).
This is **native-layer evidence only**, not a claim that arbitrary semantic
corruption is detectable (the format has no checksum).

### Restricted admission: five-layer evidence

The C ABI v1 wrapper (`native/tscb_sprintz8.cc`) and Python ctypes adapter
(`src/tscompbench/adapters/sprintz8.py`) are registered as
`sprintz-delta-u8` and `sprintz-fire-u8`. They reject other dtypes, multiple
channels, validity and unsupported ISA at the relevant gates. The
self-contained container charges the 12-byte prefix, JSON descriptor,
eight-byte native header and entire payload; `FinalBits` equals eight times
the physical stream length. Its Finalize emits zero bytes. Both codecs have
separate binary and execution-path hashes, while their semantic and execution
comparability keys agree on this task.

Layer 1 uses `registry/datasets/sprintz_u8_uts.json`, a **synthetic**, exact
`uint8` 2048-element UTS dataset, not float values cast to integers. The NPZ
is git-ignored; regenerate with
`conda run -n CompressBench14 python tools/generate_sprintz_fixture.py` before
preparing a fresh checkout. Its declared SHA-256 is
`0899a823ee1e50c7680a608a3af08f9bfe7e68e70b67e761c2753c99b9ca2cb2`.
The generator's reproducibility is covered by `test_synthetic_u8_fixture_reproduces_manifest`.
Layer 2 planned two `DIRECT_SUPPORTED` tasks. Layer 3 preflight passed
correctness and 28 required boundary cases for each. Layers 3/4 of
`runs/sprintz-u8-formal-12000-20260919` retain 10 formal PASS and eligible
repetitions per variant, all correctness PASS and bit accounting closed.
Layer 5 includes two summaries, two PASS coverage tasks and 20 eligible raw
runs in `report/report.md` and `report/report.json` (report ID
`v2:report:sha256:e27afdd6657b11351f9bfcab12d4a71e7e2172e3b161f3af0cd79ea1724aa97a`).
The source identity and observed release/sanitizer build hashes are recorded
in `registry/onboarding/sprintz-u8.json`.

The earlier `runs/sprintz-u8-formal-20260919` has **20 RESOURCE_PRESSURE**
raw repetitions: the 2000-inner-iteration ceiling was reached before the
one-second minimum. These failures remain intact, without being aggregated
or reclassified. The new formal configuration permits 12000 iterations;
this is a separate run set with its own frozen experiment config. Qualification
and synthetic-corpus PASS do not establish performance on real-world datasets.
That historical admission remains valid for those two `-u8` AlgorithmIDs. Its final
sentence is superseded only for the new `sprintz-delta` and `sprintz-fire` IDs by the
expanded review below; float, lossy and non-AVX2/BMI2/LZCNT paths remain unqualified.

## Expanded 8/16-bit UTS/MTS source and safety review

The expanded closure copies the required files byte-for-byte from lzbench commit
`580c4f085381f31b1ad669525ed04e63cbc385f3`; it is cross-identified with Sprintz
commit `a056cdb67d049669875ab5487359aca99ae873ea`. The immutable vendor closure hash is
`8535c526f5cdd430f15a9ce0ccc8bdcdd4fd820575ed67a5fe785e4dae011c4a`.
Two build-time patches, with combined hash
`c8c5372d97bfee9c665c71c85fc5f8887431483b8cc14fc1371a5261750f1771`,
repair unchecked allocations and leaks, a low-dimensional heap overflow, a generic
16-bit header-vector overread, signed left-shift UB in FIRE, and unsafe encoded-length
sizing for 16-bit odd dimensions. Vendor files themselves remain unchanged.

The upstream 16-bit API returns compressed length in `int16_t` units. A valid stream
ending on an odd byte therefore cannot be represented exactly by that return value.
`bounded_sprintz.cc` uses the vendor return only for error detection, parses the full
RLE grammar independently, validates exact consumption and decoded element count,
and returns the measured byte length. A private 16-byte envelope records element
width, dimension count and exact element count. Decode validates the complete stream
before invoking vendor code and provides bounded scratch margins for the vendor's
wide accesses. The TSCB outer descriptor, envelope, native metadata, payload, tail
and padding are all included in `FinalBits`; Finalize emits zero bytes.

`conda run -n CompressBench14 python tools/qualify_sprintz.py` rebuilds both algorithms,
verifies the vendor closure against the local lzbench checkout, replays the two patches,
and runs release plus ASan/UBSan native suites. Boundary, pattern, randomized,
truncated/mutated-stream, capacity/canary, and every forced generic `malloc`/`calloc`
failure path pass. Alignment instrumentation is explicitly disabled because upstream
uses intentional packed unaligned x86 accesses; `-fno-strict-aliasing` is also required.
This is a disclosed sanitizer-coverage limitation. LeakSanitizer was not run because
it is incompatible with the ptrace-managed host, so no LSan PASS is claimed.

The recorded build identities are:

| Algorithm/profile | Artifact SHA-256 | Compile-command SHA-256 |
|---|---|---|
| Delta release | `546e3026ebad20a92a1d4dd31cf94b17e1ade10f14e9666d966292a483d18c50` | `db616be3abd56524bd23ef1e366b9f1437ded037e576fd094ef28f42ba5680d7` |
| Delta ASan/UBSan | `d184e1c97d5c2e1dd2fba52f84004a65ee27a7bfa7aaa282c33770ba81f6d571` | `b4346e79f92392cf0111c6966b4ba74ef5e988812f18f726ee6413bc63da1bc5` |
| FIRE release | `abb569818c9bf895aa8d27a5e2bf48012300ba1d895887412273f6e43fdb437d` | `06554557e0daf8faa8511c70cf09daac46d93f9b9b280f3f1312c000af6f0b78` |
| FIRE ASan/UBSan | `5b4ebe234493055b539854932d422726a73b2269b18f12d18bb94d4fb6516a87` | `9e8af57fcad7a0889f8afb39b6cbb11eef5ceeccc9ca5ff1d6f27ddae4064b10` |

## Expanded five-layer evidence

Layer 1 uses `registry/datasets/sprintz_i16_mts.json`, a deterministic synthetic
`<i2` matrix of shape `(4096, 4)`. Its source SHA-256 is
`c04e05ffcf388dc15a42159bd36d99615b0be873f19081b95493a5c4c7ad114c`;
the ignored NPZ can be regenerated with
`conda run -n CompressBench14 python tools/generate_sprintz_i16_mts_fixture.py`.
Layer 2 produces two `DIRECT_SUPPORTED` tasks with identical semantic requirements.
SOA-to-row-major interleaving is timed adapter marshaling, not an undeclared semantic
preprocess. Layer 3 preflight validates both codecs; Layers 3/4 share the formal
repetitions; Layer 5 aggregates only eligible PASS runs.

The formal run set `runs/runset-20260919T093811Z-e48ab64f58b0` contains 20 correctness
PASS and performance-eligible repetitions, 10 per algorithm, with two summaries and
two PASS coverage tasks. Report ID
`v2:report:sha256:b8741c32e389ef5ed6f0924827d160788104a61762917c6376020410f13d65b9`
records Delta (`v2:algorithm:sha256:4faf0f5b3b11523e095a919479d5f876b80d2c01c5f79210c0e70a51b5c8ffd2`)
at SizeRatio `0.526763916` / CF `1.89838`, and FIRE
(`v2:algorithm:sha256:5e804449a2abd1c9cba40efc21566258930f5b9d2f5a7fed575e77d6e2dd4499`)
at SizeRatio `0.527221680` / CF `1.89674` on this fixture.

The diagnostic run sets `runset-20260919T093603Z-6260425ffe47` and
`runset-20260919T093626Z-e48ab64f58b0` are preserved with
`PREPROCESS_EXECUTOR_NOT_REGISTERED`; their records were not rewritten. They exposed
the incorrect initial classification of layout marshaling as a semantic preprocess.
The successful qualification run is `runset-20260919T093746Z-6260425ffe47` and is
qualification-ineligible by design.

This admission does not cover floating point, lossy quantization, validity masks,
asynchronous or ragged MTS, heterogeneous element widths, scalar/non-x86 fallback,
streaming, query, random access or checksums. The formal dataset is synthetic, so it
cannot support a real-data performance conclusion.
