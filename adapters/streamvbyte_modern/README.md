# Modern Stream VByte native integration

The workbook selects fast-pack/streamvbyte. Local lzbench/FastPFOR copies contain
an older variant, so they retain separate source and algorithm identities.
This directory freezes modern commit `7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce`.
Vendor files are unchanged; patches are replayed only in the build directories.

- `streamvbyte-modern-u32`: uint32 UTS, VALUE/V0, P0 primitive, 1234 format.
- `delta-zigzag-streamvbyte-modern64`: checked int64 Delta/ZigZag/limb32,
  TIMESTAMP/T1, explicit P2 A/B/C/D pipeline with independent stage validation.

Both registered paths encode/decode with SSE4.1 and declared scalar tails.
The original API omits count; the bounded shim includes count in the complete
stream and accounting, outside its optional native codec API timing.
Native scratch padding is internal and never included in FinalBits or RawBits.
0124, upstream modular delta32, ARM and scalar fallback remain unregistered.

The original full upstream unit passes release/debug but its sanitizer reports
signed overflow in a ZigZag-delta helper. Failure evidence is retained. A separate
patch preserves modular32 arithmetic and fixes a delta32 unaligned control store.
The patched full unit and registered ABI/stage tests pass all three profiles.
This does not qualify the unregistered helper variants as Benchmark algorithms.

Build and native qualification in the CompressBench14 environment:

```bash
python tools/build_codec.py streamvbyte-modern-u32 --profile all
python tools/build_codec.py delta-zigzag-streamvbyte-modern64 --profile all
PYTHONPATH=src python adapters/streamvbyte_modern/tests/run_native_tests.py
PYTHONPATH=src python tools/onboard_streamvbyte_modern.py
```

Five-layer experiments are under `configs/experiments/*streamvbyte-modern*.toml`.
Use `run validate` to execute and `run report --resume` to report an existing run;
the report command alone does not execute tasks. Preplanned formal profiles use
20 repetitions per configuration, minimum one second, three warmups plus 0.5 s,
and CPU 0. Formal experiments must run serially without competing benchmark jobs.

`tools/audit_streamvbyte_run.py --key streamvbyte-modern-u32` and
`tools/audit_streamvbyte_pipeline_run.py --key delta-zigzag-streamvbyte-modern64`
audit complete current-source run evidence. Run IDs are their positional arguments.
Source admission and semantics are in SOURCE_ADMISSION.md and contract.md. Current
five-layer qualification must be distinguished from formal acceptance; consult
`docs/streamvbyte_modern_self_check.md` for the signed scope and remaining work.
