# Runtime guard independent recheck preparation

Status: prepared; execution authorized after the coordinating agent confirmed production source stability. Actual execution status is stored separately in the new result directory.

`runtime_fixed_recheck.py` creates a new output directory and compiles only harmless toy ELF libraries. The fixture has two libraries with the same SONAME returning 11 or 22, a wrapper depending on that SONAME, and a no-op ELF auditor. No compression function, actual codec, pytest, benchmark, historical audit CLI, or existing report is executed or modified.

The child uses the current production `create_adapter()`, `adapter_artifacts()`, saved build evidence, runtime guards, and `resolve_execution()` unchanged. Only the LZ4 adapter class is substituted inside the isolated process with a toy adapter. Like the real dataclass adapter, its constructor stores a path and its `create_session()` performs `CDLL`. The production factory now preloads, verifies actual maps, and retains the admitted library before returning that lazy adapter. The harmless toy native function is called only after session admission. Two explicit guard/load race-window cases inject the alternative library immediately before factory `CDLL` to verify post-load rejection.

Each case separately records independently verified saved artifact/source/runtime hashes, direct runtime guard results, adapter creation, session creation, post-load guard calls, operation calls, actual toy library mappings, and loader environment.

Expected cases:

| Case | Saved hashes | Adapter / session | First toy operation |
| --- | --- | --- | --- |
| Recorded runtime, no profile or admitted baseline profile | PASS | PASS / PASS | Return 11 |
| `LD_LIBRARY_PATH` selects unadmitted same-SONAME library | PASS | Rejected before adapter loading | Not called |
| Alternative same-SONAME library already loaded | PASS | Rejected before adapter loading | Not called |
| Actual `LD_PRELOAD` or no-op `LD_AUDIT` set | PASS | Rejected before adapter loading | Not called |
| Runtime changes between factory precheck and its actual load | PASS | Rejected by post-load check / not reached | Not called |
| Runtime profile reference has wrong digest | PASS | Rejected before adapter loading | Not called |
| Explicitly admitted alternative runtime profile | PASS | PASS / PASS | Return 22; new adapter, artifact and execution identities |

New result paths are exclusive and production source hashes are compared before/after the probes. The old `before/` counterexample remains immutable. Results cover these dynamic loader and execution identity scenarios only; they do not grant complete toolchain/static-link N1, full source parity, G0–G6/N0–N5, FULL_PARITY, codec safety, or current formal performance.

Execution after the source stability notice:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  docs/audits/20261011_porting_standard/final_independent_review/fixed/runtime_fixed_recheck.py \
  --output-directory docs/audits/20261011_porting_standard/final_independent_review/fixed/runtime_resolution_r1 \
  --execute-after-stability-notice
```
