# FastDifferentialCoding source adapter

This consumes the unmodified four public APIs pinned in `SOURCE_LOCK.json`.
`SOURCE_ADMISSION.md` records why the local Benchmark's default D4 path is not
the workbook's D1 source. `contract.md` defines bounded buffers, framing,
mode/seed preservation, lifecycle, timing and byte accounting.

Current stage: registered source, bounded native ABI, direct Python SDK and
five-layer qualification of the uint32 D1 scope. This is a uint32 transform
primitive; it does not reduce payload
size and does not implicitly accept int64 timestamps or floating-point values.

Run from the project root with CompressBench14:

```bash
python adapters/fast_differential/tests/run_source_tests.py
python adapters/fast_differential/tests/run_native_tests.py
PYTHONPATH=src python tools/audit_fast_differential_native.py
PYTHONPATH=src python tools/qualify_fast_differential_sdk.py
python -m pytest tests/unit/test_fast_differential_evidence.py -q
python tools/build_codec.py fast-differential-u32 --profile all
PYTHONPATH=src python tools/onboard_fast_differential.py
PYTHONPATH=src python -m pytest tests/integration/test_fast_differential_qualification.py -q
```

The preplanned 16 configurations cover both API modes, four edge seeds and
native timing on/off. Formal run `fast-differential-u32-formal-20261007-1`
retains all 320 attempts: 314 eligible PASS and six RESOURCE_PRESSURE attempts
excluded after system VMSTAT swap detection. Each configuration has 17–20
eligible observations. Qualification retains another 16 nonranking PASS and
32 unexecuted ETTh1 capability rejections. No attempts were replaced.

Audit the saved objects, independent modular D1 math, physical ledger,
fresh decoders, frozen provenance and raw-to-report statistics:

```bash
PYTHONPATH=src python tools/audit_fast_differential_run.py \
  fast-differential-u32-formal-20261007-1 \
  fast-differential-u32-qualification-20261007-1
PYTHONPATH=src python tools/build_native_integration_plan.py
```

This scope uses a synthetic full-range uint32 UTS fixture of 8193 elements.
It does not qualify int64 timestamp data, backend pipelines or the entire
workbook entry. See `docs/fast_differential_self_check.md` for all five layers.

The native test driver builds three profiles and tests the actual shared library
and instrumented copies of the same compiled objects. Original API routing,
allocation failure and clock faults are tested separately from the untouched
source oracle. Compiler `-MD` records actual translation-unit/header dependencies,
including system headers. The shim uses baseline x86_64; only the original source
translation unit is compiled with SSE4.1, and the shim checks CPU support first.

Reports go to `build/source-audits/`. Rebuilding or changing bindings invalidates
the saved qualification; re-run it before using evidence for admission. Linux
x86_64/SSE4.1 is the tested platform. ASan leak detection is disabled; there is
no leak-clean or cross-platform claim. Source license: Apache-2.0.
