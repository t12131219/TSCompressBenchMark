# MaskedVByte native source and direct Python SDK

The two workbook entries share an unmodified Apache-2.0 source snapshot at
`fast-pack/MaskedVByte@e2298b7a28002e08f3f74755353b7229bfe6475b`.
See `SOURCE_ADMISSION.md` for the FastPFOR comparison and current limitations.

Original full-range decode exposes signed-shift UB. The explicit unsigned-shift
patch is applied only to generated build files. Original failures remain in the
report; patched release/debug/ASan+UBSan source API tests pass. Exact buffers and
protected pages cover both encoders, four decoders, seeds and scalar tails.
Select/search are separately checked against scalar queries.

```bash
python adapters/maskedvbyte/tests/run_source_tests.py --source-kind both
python tools/audit_maskedvbyte_source.py
python adapters/maskedvbyte/tests/run_native_tests.py
PYTHONPATH=src python tools/audit_maskedvbyte_native.py
PYTHONPATH=src python tools/qualify_maskedvbyte_sdk.py
PYTHONPATH=src python tools/audit_maskedvbyte_sdk.py
python -m pytest tests/unit/test_maskedvbyte_source_evidence.py tests/unit/test_maskedvbyte_native_evidence.py -q
```

Reports and compiled dependency closures live under `build/source-audits/`.
The bounded MVB1 C ABI retains the original two encoders and four decoders.
Its release/debug/ASan+UBSan shared binaries and same-object fault executables
each pass 9360 independent scalar/guard/coding/seed/decoder/alignment scenarios.
Malformed canonical LEB128, capacity/alias/lifecycle, allocation failures, source
return-length faults and native timer faults are checked before admission.

The direct Python SDK supports `maskedvbyte-u32` and `delta-maskedvbyte-u32`.
159 tests cover exact ledger, original wire bytes, independent decode, layout,
capacity, reset/close, semantic identity and execution-choice invariance. Its
checked descriptor includes coding/seed and stages; decoder API/timing do not
change serialized bytes. Native telemetry exposes actual allocation/copy requests.
Python decode borrows immutable frame bytes without a payload copy. The SDK
qualification records its actual 75 imported project files, with drift rejection.

Current qualification is scoped to Linux x86_64/SSE4.1 uint32; leak detection
is disabled. Registry/factory admission, five-layer tasks and formal evidence
remain pending. No int64 timestamp conversion, query workload registration,
ARM build or whole-workbook-entry qualification is claimed.
