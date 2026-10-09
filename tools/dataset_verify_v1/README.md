# Dataset_Verify v1 generator archive

`generate.py` is an exact source copy of the original local generator, SHA-256
`3cc975ab1b7da31f7e40a7256914ed0912a6793d1c47771b0708d809e3797991`.
Preserving these bytes preserves its generator identity. The location-only
`fixtures.py` shim points to the project's ignored `Dataset_Verify` directory;
it does not expose the historical loader that bypassed the source registry.

To recreate a missing v1 corpus (about 2.68 GiB), use the project environment:

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/dataset_verify_v1/generate.py
PYTHONPATH=src:tools /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/prepare_dataset_verify_v3.py
```

The default generator refuses existing data. Keep v1's historical `[N,1]` UTS
descriptor; the v3 generator creates a new `[N]` version instead of rewriting
the original. Runtime/package versions are recorded; replay checks must compare
payload and semantic hashes, not assume cross-version random-generator parity.
Do not format or edit the archived source under the same generator identity.
