# Stream VByte from the local lzbench source

The selected native compressor is the frozen `fastpfor/streamvbyte.c` from
`dblalock/lzbench` commit `580c4f085381f31b1ad669525ed04e63cbc385f3`, extracted from
the local `Source_Code/_repos/sprintz-lzbench` checkout. It is the older FastPFOR
variant with a four-byte count. It uses scalar encoding and SSE4.1 decoding with
a scalar remainder. The upstream function name containing `avx` does not mean
this build uses AVX2. The modern `fast-pack/streamvbyte` checkout at
`7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce` is a reference, not the selected build.

Vendor source, public header and Apache-2.0 license remain unmodified.
`SOURCE_LOCK.json` freezes their hashes and the replayed safety patch. Builds
fail on lock drift; execution rejects binary, binding, source and recipe drift.
The patch replaces unaligned scalar accesses and the aligned shuffle-table load;
it does not change the stream. There is no runtime fallback.

| Registered key | Object and input | Current verification |
| --- | --- | --- |
| `streamvbyte-u32` | P0, VALUE/V0, uint32 UTS vector | Five layers, formal repetitions and scoped audit passed |
| `delta-zigzag-streamvbyte64` | P2, TIMESTAMP/T1, checked int64 delta + ZigZag + interleaved u32 limbs + SVB | Independent stages/inverses; 96 switch qualification tasks passed; current formal acceptance is recorded in the self-check |

The uint32 fixture is explicitly synthetic. This P0 qualification does not claim
support for observed int64 epochs, arbitrary float values or the complete
timestamp pipeline named in the source list. The int64 pipeline preserves the
original unit/epoch, duplicates and order. Unrepresentable int64 differences
reject the whole object without changing input or output.

Use the `CompressBench14` environment from the project root:

```bash
python tools/build_codec.py streamvbyte-u32 --profile all
python tools/build_codec.py delta-zigzag-streamvbyte64 --profile all
python adapters/streamvbyte/tests/run_native_tests.py
PYTHONPATH=src python tools/onboard_streamvbyte.py
python tools/generate_streamvbyte_fixture.py
python -m pytest tests/adapters/test_streamvbyte.py tests/adapters/test_streamvbyte_pipeline.py tests/integration/test_streamvbyte_qualification.py
PYTHONPATH=src python -m tscompbench run validate configs/experiments/streamvbyte-u32-formal.toml --output-root runs --run-set-id svb-local
PYTHONPATH=src python -m tscompbench run report configs/experiments/streamvbyte-u32-formal.toml --output-root runs --run-set-id svb-local --resume
```

`all` builds release, debug and ASan/UBSan for these two keys. Sanitized libraries
are tested by native executables rather than loaded into an unsanitized Python
process. The verification currently covers Linux x86_64/GCC/SSE4.1; leak detection
is disabled in the native sanitizer run. No other platform qualification is claimed.

Read `contract.md` for stream, accounting, safety, lifecycle, copy telemetry and
timing boundaries. `docs/streamvbyte_self_check.md` records current scoped evidence
and outstanding workbook source parity. Generated builds, runs and reports stay
under ignored paths.

The P2 executor calls three independent native APIs. A/B/C switches are carried
in the stream; D is mandatory for its self-contained contract. Optional stage and
native instrumentation do not change bytes. Formal stage totals cover every inner
iteration and are exported in `pipeline_stages.csv`. A disabled compressor emits
an explicitly configured raw representation and has no native SVB timing.
System swap pressure remains in raw records and coverage, with false performance
eligibility; it is not attributed to the codec or hidden by selecting repetitions.

The workbook names modern `fast-pack/streamvbyte`, while the selected benchmark
variant is the frozen older lzbench implementation. Passing this P2 composition
does not establish complete source/variant parity for the workbook entry.
