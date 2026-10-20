# ALP safe-v1 Bench binding

Consumes the frozen `alp-cwida-safe-v1-20261017` native release through
`alp_port.h`; see `FROZEN_SOURCES.json` for archive and per-file identities.
The port's source and vendor are unchanged. Its recorded safety patches are
already applied and must not be applied again.

`alp` selects adaptive decimal/RD; `alp-rd` forces RD. The active implementation
contains no legacy ALP1/ARD1 encoder or decoder. Historical source is archived
in `docs/alp_integration/legacy-alp-before-safe-v1.tar.gz`.

The direct `tsbench_core_*` API returns complete ALPRW001 objects, using caller
buffers in both directions. The auxiliary `tscb_*` API accepts the established
TAI1 SOA input descriptor and produces an APS1 column container containing
complete ALPRW001 frames. Geometry, ownership, failure, accounting and timers
are specified in `docs/alp_integration/PLAN.md`; verification and limitations
are in `docs/alp_integration/README.md` (paths relative to repository root).

Bench currently opens the portable profile only (`isa=SCALAR`), not the
standalone AVX2 profile. This NATIVE_PORT binding does not claim FULL_PARITY.
