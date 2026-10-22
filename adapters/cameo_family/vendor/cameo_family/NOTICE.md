# Provenance and notices

CAMEO-family translation/API files: Apache-2.0, with modifications described in docs/SOURCE_MAP.md and docs/UPSTREAM_DEFECTS.md. CAMEO baseline damslab/reproducibility and TerseTS retain their frozen original notices. Source repositories are kept read-only; the unlicensed cmcuza/cameo code is discovery-only and was not translated.

- Apache-2.0: LICENSES/cameo-Apache-2.0.txt and tersets-Apache-2.0.txt.
- pocketfft C component: BSD-3-Clause; embedded notices retained and copied to LICENSES/pocketfft-BSD-3-Clause.txt.
- NumPy sort translation: MIT AND BSD-3-Clause as labelled in src/numpy_sort.cpp; original NumPy notices and source references retained. No compression algorithm is copied from another rewrite.
- nlohmann/json3.11.3: MIT; header and LICENSES/nlohmann-MIT.txt retained.
- Native NumPy-wheel dependency closure: OpenBLAS BSD-3-Clause, bundled LAPACK notices and GFortran/Quadmath runtime licenses/exceptions as fully reproduced in LICENSES/numpy-openblas-bundled.txt. Exact binary hashes and runtime configuration are in vendor/linear-algebra; the native binaries have not been rewritten or sanitizer-instrumented.
- LLVM validation tools: Apache-2.0 WITH LLVM-exception; Debian copyright documents and downloaded LLVM license/source retained with Source dependencies. They are validation-only.

Local natural-data snapshots are from the user-requested local CAMEO data directory; shared synthetic objects preserve Dataset_Verify metadata, CC0-1.0 and original payload identities. This is a local review/validation bundle, not a declaration that every external dataset can be publicly redistributed. No external publication, Benchmark integration or original-source FULL_PARITY is asserted. REWRITE_DONE applies only to the separately identified repaired-v1 target with its matching final evidence and archive audit.

User-authorized repaired-v1 modifications are documented in docs/REPAIRS.md; six modified Apache-2.0 reference files retain their original license closure and have separate identities. No patch is represented as the upstream authors' release.

2026-10-21 source dependency update: production now builds OpenBLAS 0.3.21
from vendor/openblas/OpenBLAS-0.3.21.tar.gz (BSD-3-Clause; source notices remain
inside the archive, root license in LICENSES/OpenBLAS-BSD-3-Clause.txt).
The NumPy-wheel OpenBLAS/GFortran/Quadmath copies remain historical/oracle assets
and are not installed or linked by the default production build. QEMU, Valgrind
and Intel SDE are validation tools, not production codec components. Their
archives and licenses are retained only for the local research/review workflow;
no public redistribution of datasets or proprietary validation tools is claimed.
