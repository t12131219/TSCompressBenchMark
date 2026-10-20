# Native consumer handoff v1

Methods: ALP adaptive and ALP-RD forced; VALUE codec, binary32/binary64, lossless
bitpatterns. Implementation: cwida-ALP-native-safe-v1, NATIVE_PORT. Source commit,
license, exact vendor patch and per-file hashes are frozen in SOURCE_LOCK,
patches/INDEX, BUILD_LOCK and SBOM. `alp_port.h` is the C ABI v1 consumption
boundary; compile CMake target `alp_port` or install library/header/CLI.
No STL or C++ exception crosses the ABI. Library owns temporary allocation;
caller owns input/output. Decode needs only the complete encoded object.

Configuration whitelist: dtype 4/8, method 0/1, n<=2^24. FP and ISA constraints
are contractual and checked where applicable. Portable and compiled AVX2 are
separate BuildIDs; no runtime ISA fallback. Existing external adapters, including
any same-name ALP code in TSDataCompressBenchMark, were neither used nor modified.
Source remains outside production runtime; Python and QEMU are verification
tools only. `dist/x86_64-portable` is a prebuilt local LP64 Linux consumer install.

Complete objects include length/dtype/method, rowgroup descriptors/dictionaries,
all padded blocks, decimal exceptions and CRC. FinalBits=8*file bytes, no hidden
dictionary or model cost. Encode/decode API timing includes its full temporary
allocation, input copy, padding, sampling, native codec and integrity work;
CLI file I/O and caller buffer allocation are outside that timer.

Fresh-source differential, cross-decode and bitpattern evidence is scoped per
case. Source-UB frames and expected refusals are separately accounted. Safety
does not imply original output identity on UB paths. Sanitizer system libraries
remain external/uninstrumented. AArch64 results are QEMU runs, not physical
hardware performance. AVX-512/publication intrinsic kernels remain unopened.

Bench consumption is a separate stage: freeze this exact native package/version,
write and qualify a binding, verify negotiation/input/ownership/FinalBits/timers,
then separately qualify any pipeline and formal comparisons. Changes to vendor,
patches, FP/ISA, frame or binding invalidate corresponding evidence. Nothing in
this handoff signs existing Bench entries, a formal comparison or FULL_PARITY.
