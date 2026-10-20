# Four-layer capability mapping

| Layer | Current claim | Evidence / boundary |
|---|---|---|
| SourceCapabilityMatrix | float32/64, adaptive decimal/RD, forced RD, rowgroups, exceptions, FFOR/FALP, compile-time ISA, TLS concurrency; full inventory retained | NATIVE_CAPABILITY_MATRIX.yaml; original snapshot |
| StandaloneVerificationMatrix | bounded safe-v1 C ABI, portable GCC/Clang and AVX2, one-shot frame, bitpattern recovery, safe refusals and concurrent calls; AArch64 QEMU additional subset | QUALIFICATION.json, verification-qualified, profiles-*-qualified, sanitizer logs |
| BenchProfileMatrix | no entry opened or modified by this task | no binding/registry integration; no existing adapter qualification inherited |
| PipelineMatrix | explicit wrapper padding-to-1024, original logical-length recovery and new complete frame | CONTRACT.md; all copies/padding/dictionary/CRC included in API cost and FinalBits; no RAW, timestamp, missing-value mask or implicit numeric conversion |

Native §114.1 permits a frozen bounded profile. Required source capabilities
outside it remain required in the upstream inventory, and are NOT signed PASS.
No waiver is invented and no FULL_PARITY label is signed. No G0–G6 rewrite
qualification is substituted for N0–N5. C ABI input dtype is native; Python's
CSV->binary32 conversion belongs only to independent dataset preparation, and
its converted bits are the exact input oracle for that dtype.

Resource-bound proof: a decimal vector has at most 8192 FFOR bytes + 10240
exception bytes + 16 header bytes; RD at most (63+3)*128 + 4096 + 16 bytes.
At most one 32-byte rowgroup header per vector. Thus
`32 + ceil(n/1024)*32800` safely includes every promised byte for both dtypes,
including the zero-length finalized frame. Checked count <=2^24 bounds all
size_t/narrowing arithmetic on frozen LP64 platforms. Large-count preflight is
tested without pretending to allocate or benchmark the maximum size.
