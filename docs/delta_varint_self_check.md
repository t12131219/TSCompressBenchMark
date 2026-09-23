# Delta + VarInt five-layer self-check

## Scope and source evidence

- [x] Source is frozen at `mattsta/varint@81ba89cd76f0`; only the unmodified
  `varintDelta`, `varintExternal`, shared header, and endian helper are vendored.
- [x] The implementation was selected from the local benchmark/source inventory,
  not recreated from a prose description.
- [x] It is P0 `TIMESTAMP/T0`, scalar, single-thread, lossless. It is not
  presented as a self-contained upstream codec or streaming API.

## Layer gates

- [x] Layer 1 uses the canonical ETTh1 `int64` UNIX-second timeline without
  sorting, casting, resampling, or routing Value columns into the codec.
- [x] Layer 2 freezes source/manifest/onboarding/build evidence and keeps the
  primitive in its own semantic and execution comparison groups.
- [x] Layer 3 validates N=0/1/2, regular/jitter/duplicate/out-of-order/negative
  delta/epoch extremes, capacity canaries, determinism, exact reconstruction,
  and exact descriptor plus payload accounting.
- [x] Layer 4 records NATIVE, CORE, and PIPELINE observations from the same
  repetition. Finalize is mandatory and correctly returns zero bytes.
- [x] Layer 5 generates report, coverage, eligibility, and summary artifacts;
  qualification records remain ineligible for formal ranking by design. The
  formal ETTh1 run produced 10/10 PASS and 10 eligible repetitions, with
  419,720 FinalBits from 1,114,880 canonical raw bits (factor 2.656247).

## Verified commands

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py delta-varint --profile all
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/adapters/test_delta_varint.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/integration/test_delta_varint_qualification.py
# Formal execution uses configs/experiments/delta-varint-formal.toml.
```
